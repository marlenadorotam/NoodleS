"""Exact OCC ellipsoids and inspection of affine-transformed native spheres."""
import math
from functools import lru_cache

from .curves import PlaneValue
from .solids import SolidValue


def make_ellipsoid(value):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
    from serpentine3d.core import geometry as g

    frame = value.frame
    x, y, z = value.dimensions
    uniform = x == y == z
    axes = gp_Ax2(gp_Pnt(*frame.origin), gp_Dir(*frame.normal), gp_Dir(*frame.axis_x)) if uniform else gp_Ax2()
    maker = BRepPrimAPI_MakeSphere(axes, x if uniform else 1.)
    shape = maker.Solid() if value.solid else maker.Shell()
    if not uniform:
        shape = g.scale(shape, (0., 0., 0.), 1., factors=(x, y, z))
        transform = gp_Trsf()
        transform.SetValues(*(component for row in zip(frame.axis_x, frame.axis_y, frame.normal, frame.origin)
                              for component in row))
        shape = BRepBuilderAPI_Transform(shape, transform, True).Shape()
    if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError('OpenCascade could not build a valid Ellipsoid.')
    return shape


def _full_sphere_face(shape):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d, BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from serpentine3d.core import geometry as g

    error = 'Reference Ellipsoid requires a complete sphere or ellipsoid without cuts or holes.'
    faces = g.faces_of(shape)
    if len(faces) != 1 or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError(error)
    face = faces[0]
    wires = TopExp_Explorer(face, TopAbs_WIRE)
    if not wires.More():
        raise ValueError(error)
    wires.Next()
    edges = g.edges_of(face)
    poles = [edge for edge in edges if BRep_Tool.Degenerated_s(edge)]
    seams = [edge for edge in edges if BRep_Tool.IsClosed_s(edge, face)]
    if wires.More() or len(edges) != 3 or len(poles) != 2 or len(seams) != 1:
        raise ValueError(error)
    surface = BRepAdaptor_Surface(face)
    u0, u1 = surface.FirstUParameter(), surface.LastUParameter()
    v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
    if not (math.isclose(u1-u0, math.tau, abs_tol=1e-8)
            and math.isclose(v0, -math.pi/2, abs_tol=1e-8)
            and math.isclose(v1, math.pi/2, abs_tol=1e-8)):
        raise ValueError(error)
    curve = BRepAdaptor_Curve2d(seams[0], face)
    start, end = curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())
    if not (math.isclose(start.X(), end.X(), abs_tol=1e-8)
            and math.isclose(abs(end.Y()-start.Y()), math.pi, abs_tol=1e-8)):
        raise ValueError(error)
    return surface


def _knots(surface, axis):
    count = getattr(surface, 'Nb'+axis+'Knots')()
    knot = getattr(surface, axis+'Knot')
    multiplicity = getattr(surface, axis+'Multiplicity')
    return tuple((knot(i), multiplicity(i)) for i in range(1, count+1))


def _control_net(surface):
    return [surface.Pole(u, v).Coord() for u in range(1, surface.NbUPoles()+1)
            for v in range(1, surface.NbVPoles()+1)]


def _weights(surface):
    return [surface.Weight(u, v) for u in range(1, surface.NbUPoles()+1)
            for v in range(1, surface.NbVPoles()+1)]


@lru_cache(maxsize=1)
def _unit_sphere_control_net():
    import numpy as np
    from OCP.Geom import Geom_SphericalSurface
    from OCP.GeomConvert import GeomConvert
    from OCP.gp import gp_Ax3

    surface = GeomConvert.SurfaceToBSplineSurface_s(Geom_SphericalSurface(gp_Ax3(), 1.))
    poles = np.asarray(_control_net(surface))
    design = np.column_stack((poles, np.ones(len(poles))))
    return design, np.linalg.pinv(design), np.asarray(_weights(surface)), (_knots(surface, 'U'), _knots(surface, 'V'))


def _affine_axes(surface):
    from itertools import permutations
    import numpy as np

    design, inverse, weights, knots = _unit_sphere_control_net()
    error = 'Reference Ellipsoid requires an affine-scaled native sphere.'
    if (surface.UDegree() != 2 or surface.VDegree() != 2 or not surface.IsUPeriodic()
            or (surface.NbUPoles(), surface.NbVPoles()) != (6, 5)
            or any(len(actual) != len(expected) or not np.allclose(actual, expected, atol=1e-9, rtol=0.)
                   for actual, expected in zip((_knots(surface, 'U'), _knots(surface, 'V')), knots))):
        raise ValueError(error)
    native_weights = np.asarray(_weights(surface))
    if not np.allclose(native_weights/native_weights[0], weights/weights[0], atol=1e-9, rtol=0.):
        raise ValueError(error)
    poles = np.asarray(_control_net(surface))
    origin = poles[0]
    # An affine transform preserves the weights and transforms every pole.
    matrix = inverse @ (poles-origin)
    if not np.isfinite(matrix).all() or not np.allclose(design @ matrix, poles-origin,
            atol=max(1e-8, np.max(np.abs(matrix[:3]))*1e-9), rtol=0.):
        raise ValueError(error)
    center = origin + matrix[3]
    axes = matrix[:3].T
    radii = np.linalg.norm(axes, axis=0)
    if np.min(radii) <= 1e-9:
        raise ValueError(error)
    directions = axes/radii
    if not np.allclose(directions.T @ directions, np.eye(3), atol=1e-9, rtol=0.):
        # A further scale along unrelated axes can skew the original parameter frame.
        # The left singular vectors still give the geometric principal axes.
        principal, lengths, _ = np.linalg.svd(axes)
        order = max(permutations(range(3)), key=lambda p: sum(
            abs(directions[:, i] @ principal[:, j]) for i, j in enumerate(p)))
        principal = principal[:, order]
        signs = np.where(np.sum(principal*directions, axis=0) < 0., -1., 1.)
        directions, radii = principal*signs, lengths[list(order)]
    return PlaneValue(tuple(map(float, center)), tuple(map(float, directions[:, 0])),
                      tuple(map(float, directions[:, 2]))), tuple(map(float, radii))


def inspect_ellipsoid(shape, key):
    from OCP.GeomAbs import GeomAbs_BSplineSurface, GeomAbs_Sphere
    from OCP.TopAbs import TopAbs_SOLID

    surface = _full_sphere_face(shape)
    if surface.GetType() == GeomAbs_Sphere:
        sphere = surface.Sphere()
        axis = sphere.Position()
        frame = PlaneValue(sphere.Location().Coord(), axis.XDirection().Coord(), axis.Direction().Coord())
        radii = (sphere.Radius(),)*3
    elif surface.GetType() == GeomAbs_BSplineSurface:
        frame, radii = _affine_axes(surface.BSpline())
    else:
        raise ValueError('Reference Ellipsoid requires a sphere or an affine-scaled native sphere.')
    return SolidValue(key, 'ellipsoid', frame, radii, shape.ShapeType() == TopAbs_SOLID)
