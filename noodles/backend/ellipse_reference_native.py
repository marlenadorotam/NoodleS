"""Recover analytic ellipses from OCC's affine-transformed rational conics."""
from functools import lru_cache
import math


@lru_cache(maxsize=256)
def inspect_rational_ellipse(shape):
    """Return a frame and radii only for one complete quadratic ellipse."""
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomConvert import GeomConvert_BSplineCurveToBezierCurve
    from OCP.TopAbs import TopAbs_REVERSED
    from serpentine3d.core import geometry as g
    from .curves import PlaneValue

    edge, = g.edges_of(shape)
    curve = BRepAdaptor_Curve(edge)
    spline = curve.BSpline()
    if spline.Degree() != 2 or not spline.IsRational() or spline.NbKnots() > 17:
        return None
    first, last = curve.FirstParameter(), curve.LastParameter()
    if not curve.Value(first).IsEqual(curve.Value(last), g.tol()):
        return None
    pieces = GeomConvert_BSplineCurveToBezierCurve(spline, first, last, 1e-10)
    if pieces.NbArcs() < 2:
        return None
    points = [g.pnt_tuple(pieces.Arc(1).Value(0.))]
    # Substitution in a quadratic implicit conic gives a degree-four
    # homogeneous polynomial. Five values per quadratic Bézier span test it.
    for index in range(1, pieces.NbArcs()+1):
        arc = pieces.Arc(index)
        points.extend(g.pnt_tuple(arc.Value(t)) for t in (.25, .5, .75, 1.))
    if edge.Orientation() == TopAbs_REVERSED:
        points.reverse()
    samples = np.asarray(points, dtype=float)
    origin = samples[:-1].mean(axis=0)
    offsets = samples - origin
    try:
        _, singular, basis = np.linalg.svd(offsets, full_matrices=False)
        if singular[1] <= 1e-9 or singular[2] > max(g.tol(), singular[1]*1e-8):
            return None
        size = singular[:2] / math.sqrt(len(samples))
        xy = (offsets @ basis[:2].T) / size
        x, y = xy.T
        terms = np.column_stack((x*x, 2*x*y, y*y, x, y, np.ones_like(x)))
        _, design_singular, coefficients = np.linalg.svd(terms, full_matrices=False)
        if design_singular[-1] > 1e-8 * design_singular[0]:
            return None
        a, b, c, d, e, f = coefficients[-1]
        if a < 0:
            a, b, c, d, e, f = -coefficients[-1]
        quadratic = np.array(((a, b), (b, c)))
        eigenvalues, axes = np.linalg.eigh(quadratic)
        if eigenvalues[0] <= 0:
            return None
        center = -.5 * np.linalg.solve(quadratic, (d, e))
        level = center @ quadratic @ center - f
        if level <= 0:
            return None
        circle_coordinates = ((xy - center) @ axes) * np.sqrt(eigenvalues/level)
        if np.max(np.abs(np.sum(circle_coordinates**2, axis=1) - 1.)) > 1e-8:
            return None
        u, v = circle_coordinates[:-1].T
        uu, vv = circle_coordinates[1:].T
        turns = np.arctan2(u*vv-v*uu, u*uu+v*vv)
        winding = float(turns.sum())
        if abs(abs(winding)-math.tau) > 1e-7 or np.any(turns*winding < -1e-10):
            return None
        world_axes, radii, _ = np.linalg.svd(size[:, None] * axes * np.sqrt(level/eigenvalues))
    except np.linalg.LinAlgError:
        return None
    axis_x = world_axes[:, 0] @ basis[:2]
    center = origin + (center*size) @ basis[:2]
    direction = np.dot(samples[0] - center, axis_x)
    if abs(direction) <= radii[0]*1e-8:
        direction = np.dot(samples[1] - samples[0], axis_x)
    if direction < 0:
        axis_x = -axis_x
    normal = np.cross(basis[0], basis[1]) * math.copysign(1., winding * np.linalg.det(axes))
    frame = PlaneValue(tuple(map(float, center)), tuple(map(float, axis_x)), tuple(map(float, normal)))
    return frame, tuple(map(float, radii))
