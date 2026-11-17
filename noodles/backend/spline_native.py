"""Native spline fitting, reused from our Ryven InterpCurves shape algorithm."""
import math


_SUPPORTED_DEGREES = range(1, 6)


def _validate_xyz(points):
    if not isinstance(points, (list, tuple)) or not 3 <= len(points) <= 1200:
        raise ValueError('InterpCurve: 3..1200 interpolation points required')
    xyz = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise ValueError('InterpCurves: interpolation point must be XYZ')
        p = tuple(float(v) for v in point)
        if not all(math.isfinite(v) for v in p):
            raise ValueError('InterpCurves: coordinates must be finite')
        xyz.append(p)
    # Match deferred validation: the native worker must not silently discard a site.
    if len(xyz) > 1 and _distance(xyz[0], xyz[-1]) <= 1e-9:
        xyz.pop()  # duplicate endpoint specifies CLOSED, not an extra site
        has_duplicate_end = True
    else:
        has_duplicate_end = False
    if len(xyz) < 3:
        raise ValueError('InterpCurves: at least three distinct interpolation sites')
    if any(_distance(xyz[i - 1], xyz[i]) <= 1e-9 for i in range(1, len(xyz))):
        raise ValueError('InterpCurves: adjacent sites must be distinct')
    return xyz, has_duplicate_end


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _params(points, style, periodic):
    n = len(points)
    steps = []
    for i in range(n if periodic else n - 1):
        span = _distance(points[i], points[(i + 1) % n])
        if span <= 1e-9:
            raise ValueError('InterpCurves: consecutive points have zero distance')
        steps.append(1. if style == 0 else span if style == 1 else math.sqrt(span))
    acc = [0.]
    for step in steps:
        acc.append(acc[-1] + step)
    if not acc[-1] > 0:
        raise ValueError('InterpCurves: degenerate parametrization')
    # Periodic knots have n intervals; open sites end at 1.
    target = float(n) if periodic else 1.
    return [v * target / acc[-1] for v in acc]


def _solve(matrix, targets):
    """Solve all XYZ dimensions with partial pivoting; no SciPy dependency.

    NumPy, if already installed in Serpentine, accelerates large grids. The
    pure-Python fallback remains available for small/medium point lists.
    """
    try:
        import numpy as np
        m = np.asarray(matrix, dtype=float)
        b = np.asarray(targets, dtype=float)
        coeff = np.linalg.solve(m, b)
        if not np.isfinite(coeff).all():
            raise ValueError('Non-finite spline coefficients')
        return coeff.tolist()
    except ImportError:
        pass
    n = len(matrix)
    if n > 128:
        raise ValueError('InterpCurves: >128 points require NumPy for degree-specific interpolation')
    a = [list(row) + list(rhs) for row, rhs in zip(matrix, targets)]
    for k in range(n):
        pivot = max(range(k, n), key=lambda i: abs(a[i][k]))
        if abs(a[pivot][k]) < 1e-12:
            raise ValueError('InterpCurves: interpolation system is singular')
        a[pivot], a[k] = a[k], a[pivot]
        for i in range(k + 1, n):
            q = a[i][k] / a[k][k]
            if not q:
                continue
            for j in range(k, n + 3):
                a[i][j] -= q * a[k][j]
    x = [[0.] * 3 for _ in range(n)]
    for k in range(n - 1, -1, -1):
        for dim in range(3):
            x[k][dim] = (a[k][n + dim] - sum(a[k][i] * x[i][dim]
                                                 for i in range(k + 1, n))) / a[k][k]
    return x


def _occ_curve(poles, knots, mults, degree, periodic):
    from OCP.gp import gp_Pnt
    from OCP.Geom import Geom_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    pp = TColgp_Array1OfPnt(1, len(poles))
    kk = TColStd_Array1OfReal(1, len(knots))
    mm = TColStd_Array1OfInteger(1, len(mults))
    for i, p in enumerate(poles, 1):
        pp.SetValue(i, gp_Pnt(*p))
    for i, value in enumerate(knots, 1):
        kk.SetValue(i, float(value))
    for i, value in enumerate(mults, 1):
        mm.SetValue(i, int(value))
    return Geom_BSplineCurve(pp, kk, mm, degree, periodic)


def _interpolate_curve(sites, degree, style, periodic):
    n = len(sites)
    if not 1 <= degree <= 5 or degree >= n:
        raise ValueError('InterpCurves: Degree must be 1..5 and < number of interpolation sites')
    parameters = _params(sites, style, periodic)
    if periodic:
        # One unique knot per site plus the final period endpoint; the
        # interpolation sites are placed at a quarter of each knot span.
        # This phase avoids singular cyclic collocation for even/odd degrees.
        knots = list(parameters)
        multiplicities = [1] * len(knots)
        arguments = [knots[i] + 0.25 * (knots[i + 1] - knots[i])
                     for i in range(n)]
    else:
        # Open clamped knot vector, Schoenberg-Whitney interpolation.
        interior = [sum(parameters[i:i + degree]) / degree
                    for i in range(1, n - degree)]
        knots = [parameters[0]] + interior + [parameters[-1]]
        multiplicities = [degree + 1] + [1] * len(interior) + [degree + 1]
        arguments = parameters
    # Build a *native OCC basis*, rather than approximate points with sampled
    # polylines. Every column is the native periodic/clamped BSpline produced
    # from one unit pole. Solve its interpolation equations for exact poles.
    matrix = [[0.] * n for _ in range(n)]
    for pole in range(n):
        unit = [(1., 0., 0.) if i == pole else (0., 0., 0.)
                for i in range(n)]
        basis = _occ_curve(unit, knots, multiplicities, degree, periodic)
        for row, value in enumerate(arguments):
            matrix[row][pole] = float(basis.Value(value).X())
    fitted = _solve(matrix, sites)
    curve = _occ_curve(fitted, knots, multiplicities, degree, periodic)
    for pos, xyz in zip(arguments, sites):
        actual = curve.Value(pos)
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(
            (actual.X(), actual.Y(), actual.Z()), xyz)))
        if error > max(1e-6, max(abs(v) for v in xyz) * 1e-8):
            raise ValueError('InterpCurves: OCC spline does not pass through its points')
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepCheck import BRepCheck_Analyzer
    made = BRepBuilderAPI_MakeEdge(curve)
    if not made.IsDone():
        raise ValueError('InterpCurves: OCC could not make spline edge')
    edge = made.Edge()
    if edge.IsNull() or not BRepCheck_Analyzer(edge).IsValid():
        raise ValueError('InterpCurves: native spline edge is invalid')
    return edge


def make_interpcurves_extended(points, *, closed=False, degree=3,
                               periodic=False, knot_style=1,
                               legacy_builder=None):
    """Return an exact native OCC BSpline Edge; never modify SceneObjects.

    Old cases (degree=3, periodic=False, chord) explicitly delegate to
    the already proven Serpentine interpolation builder. This remains the
    source of truth for legacy saved projects and old Closed semantics.
    """
    if type(degree) is not int or degree not in _SUPPORTED_DEGREES:
        raise ValueError('InterpCurves Degree must be integer 1..5')
    if type(periodic) is not bool or type(closed) is not bool:
        raise ValueError('InterpCurves Closed/Periodic must be booleans')
    if type(knot_style) is not int or knot_style not in (0, 1, 2):
        raise ValueError('InterpCurves Knot Style: 0=Uniform, 1=Chord, 2=SqrtChord')
    sites, already_closed = _validate_xyz(points)
    closed = bool(closed or already_closed)
    if degree == 3 and knot_style == 1 and not periodic and legacy_builder is not None:
        return legacy_builder(points, closed)
    if degree >= len(sites) + int(closed and not periodic):
        raise ValueError('InterpCurves Degree exceeds interpolation point count')
    if periodic:
        return _interpolate_curve(sites, degree, knot_style, True)
    if closed:
        sites = sites + [sites[0]]
    return _interpolate_curve(sites, degree, knot_style, False)


def materialize_spline(value):
    from serpentine3d.core import geometry as g
    if not value.knots:
        if value.kind == 'curve':
            return g.make_control_curve(list(value.points), value.degree, value.closed)
        return make_interpcurves_extended(list(value.points), degree=value.degree,
            closed=value.closed, periodic=value.periodic, knot_style=value.knot_style,
            legacy_builder=g.make_interp_curve)
    from OCP.gp import gp_Pnt
    from OCP.Geom import Geom_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    poles = TColgp_Array1OfPnt(1, len(value.points))
    weights = TColStd_Array1OfReal(1, len(value.weights))
    knots = TColStd_Array1OfReal(1, len(value.knots))
    mults = TColStd_Array1OfInteger(1, len(value.knots))
    for i, (point, weight) in enumerate(zip(value.points, value.weights), 1):
        poles.SetValue(i, gp_Pnt(*point))
        weights.SetValue(i, weight)
    for i, (knot, mult) in enumerate(zip(value.knots, value.multiplicities), 1):
        knots.SetValue(i, knot)
        mults.SetValue(i, mult)
    curve = Geom_BSplineCurve(poles, weights, knots, mults, value.degree, value.periodic)
    return BRepBuilderAPI_MakeEdge(curve, *value.domain).Edge()


def describe_spline(shape, key, kind, measure=True):
    """Exact placed/oriented NURBS snapshot, including trimmed and rational edges."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_BezierCurve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from .splines import SplineValue
    if shape.ShapeType() != TopAbs_EDGE:
        raise ValueError('Select native NURBS curve edges, not compounds or subobjects.')
    adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
    if adaptor.GetType() == GeomAbs_BSplineCurve:
        curve = adaptor.BSpline().Copy()
    elif adaptor.GetType() == GeomAbs_BezierCurve:
        from OCP.GeomConvert import GeomConvert
        # Exact basis conversion: preserve rational weights and native placement.
        # The source SceneObject is neither converted nor replaced.
        curve = GeomConvert.CurveToBSplineCurve_s(adaptor.Bezier())
    else:
        raise ValueError('Select native NURBS/Bezier curves. Curve and InterpCurve accept the same native spline types in Reference mode.')
    first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    if abs(first-curve.FirstParameter()) > 1e-12 or abs(last-curve.LastParameter()) > 1e-12:
        curve.Segment(first, last)
    if shape.Orientation() == TopAbs_REVERSED:
        curve.Reverse()
    poles = tuple((curve.Pole(i).X(), curve.Pole(i).Y(), curve.Pole(i).Z()) for i in range(1, curve.NbPoles()+1))
    return SplineValue(key, kind, poles, closed=adaptor.IsClosed(), degree=curve.Degree(), periodic=curve.IsPeriodic(),
        knots=tuple(curve.Knot(i) for i in range(1, curve.NbKnots()+1)),
        multiplicities=tuple(curve.Multiplicity(i) for i in range(1, curve.NbKnots()+1)),
        weights=tuple(curve.Weight(i) for i in range(1, curve.NbPoles()+1)),
        domain=(curve.FirstParameter(), curve.LastParameter()),
        measured_length=GCPnts_AbscissaPoint.Length_s(adaptor, first, last, 1e-8) if measure else None)


