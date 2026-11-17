"""OCC curve domains, samples and planes, without scene writes."""
import math

from .arithmetic import finite_number
from .curve_sampling import (
    FRAME_OPERATIONS, MAX_DIVISIONS, MAX_FRAME_PARAMETERS, MAX_FRAMES, MAX_SAMPLES,
    CLOSEST_POINT, CURVATURE, CURVE_LENGTH, DIVIDE_BY_LENGTH, EXPLICIT_SAMPLING, POINT_IN_CURVE,
    SAMPLING_SPECS, is_sample_curve,
)
from .curves import dot, scale, sub, unit, xyz
from .datatree import MAX_ITEMS


def curve_adaptor(shape):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_CompCurve
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE
    from OCP.TopoDS import TopoDS

    if shape.ShapeType() == TopAbs_EDGE:
        return BRepAdaptor_Curve(TopoDS.Edge_s(shape)), None, BRep_Tool.IsClosed_s(shape)
    if shape.ShapeType() == TopAbs_WIRE:
        wire = TopoDS.Wire_s(shape)
        # Use the same cumulative edge-length knots as the Ryven adapter.
        return BRepAdaptor_CompCurve(wire, True), wire, BRep_Tool.IsClosed_s(wire)
    raise ValueError('Curve sampling requires an OpenCascade edge or wire.')


def parameter_domain(adaptor):
    start, end = adaptor.FirstParameter(), adaptor.LastParameter()
    if not all(map(math.isfinite, (start, end, end - start))) or not start < end:
        raise ValueError('Curve has an invalid native parameter domain.')
    return start, end


def arc_length(adaptor):
    from OCP.GCPnts import GCPnts_AbscissaPoint

    first, last = parameter_domain(adaptor)
    return finite_number(GCPnts_AbscissaPoint.Length_s(adaptor, first, last, 1e-9))


def division_parameters(adaptor, wire, closed, count, kinks):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_UniformAbscissa
    first, last = parameter_domain(adaptor)
    uniform = GCPnts_UniformAbscissa(adaptor, count + 1, first, last)
    if not uniform.IsDone() or uniform.NbPoints() != count + 1:
        raise ValueError('OpenCascade could not divide this curve into equal lengths.')
    params = [first, *(uniform.Parameter(i) for i in range(2, count + 1))]
    if not closed:
        params.append(last)
    if kinks and wire is not None:
        cursor = first
        joints = []
        walker = BRepTools_WireExplorer(wire)
        while walker.More():
            size = GCPnts_AbscissaPoint.Length_s(BRepAdaptor_Curve(walker.Current()))
            if not math.isfinite(size) or size <= 1e-10:
                raise ValueError('Curve wire contains a zero-length edge.')
            joints.append(cursor)
            cursor += size
            walker.Next()
        tolerance = (last - first) * 1e-9
        ordered = sorted([*params, *joints[1:]])
        params = [ordered[0]]
        for t in ordered[1:]:
            if t - params[-1] > tolerance and t < last - tolerance:
                params.append(t)
        if not closed:
            params.append(last)
    return params


def length_parameters(adaptor, closed, length, remainder, available):
    from OCP.GCPnts import GCPnts_AbscissaPoint

    length = finite_number(length)
    if length <= 0 or type(remainder) is not bool:
        raise ValueError('Use a positive Segment Length and a Boolean Include Remainder.')
    first, last = parameter_domain(adaptor)
    total = arc_length(adaptor)
    if total <= 0:
        raise ValueError('Divide by Length requires a nonzero curve length.')
    ratio = total / length
    if not math.isfinite(ratio) or ratio > available + 1:
        raise ValueError(f'Divide by Length exceeds the {MAX_SAMPLES:,}-sample limit.')
    full = math.floor(ratio)
    exact = full > 0 and math.isclose(ratio, round(ratio), rel_tol=1e-12, abs_tol=0.)
    if exact:
        full = round(ratio)
    count = full - int(exact)
    append_end = not closed and (exact or remainder)
    if 1 + count + append_end > available:
        raise ValueError(f'Divide by Length exceeds the {MAX_SAMPLES:,}-sample limit.')
    params = [first]
    for index in range(1, count + 1):
        point = GCPnts_AbscissaPoint(1e-9, adaptor, index*length, first)
        if not point.IsDone() or not params[-1] < point.Parameter() < last:
            raise ValueError('OpenCascade could not locate an equal-length sample.')
        params.append(point.Parameter())
    if append_end:
        params.append(last)
    return params


def explicit_parameters(adaptor, values, normalized, name='Frame'):
    if type(normalized) is not bool or not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_FRAME_PARAMETERS:
        raise ValueError(f'Invalid {name} parameter list or Normalized option.')
    first, last = parameter_domain(adaptor)
    low, high = (0., 1.) if normalized else (first, last)
    tolerance = max(1e-12, (high - low)*1e-12, 4*math.ulp(low), 4*math.ulp(high))
    params = []
    for value in values:
        t = finite_number(value)
        if not low - tolerance <= t <= high + tolerance:
            raise ValueError(f'{name} t must be within 0..1 in Normalized mode.' if normalized
                             else f'{name} t is outside the native curve domain.')
        t = min(high, max(low, t))
        if normalized:
            t = last if t == 1. else first + (last - first)*t
        params.append(t)
    return params


def frame_axis(adaptor, t, point, velocity, tangent, guide, align):
    from OCP.gp import gp_Vec

    def projected(direction):
        return sub(direction, scale(tangent, dot(direction, tangent)))

    if not align:
        acceleration = gp_Vec()
        try:
            adaptor.D2(t, point, velocity, acceleration)
        except RuntimeError:
            pass  # An unavailable second derivative falls back to the guide.
        else:
            principal = projected((acceleration.X(), acceleration.Y(), acceleration.Z()))
            length = math.hypot(*principal)
            if math.isfinite(length) and length > 1e-8:
                return scale(principal, 1 / length)

    axis = projected(guide)
    if math.hypot(*axis) <= 1e-8:
        # World axes in fixed order, as in the Ryven sampling plugin.
        axes = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
        axis = next(vector for vector in map(projected, axes) if math.hypot(*vector) > 1e-8)
    return unit(axis)


def sample_at(adaptor, params, wanted, guide=None, align=True):
    from OCP.gp import gp_Pnt, gp_Vec

    samples = []
    for t in params:
        if not wanted():
            return []
        point, velocity = gp_Pnt(), gp_Vec()
        adaptor.D1(t, point, velocity)
        speed = velocity.Magnitude()
        if not math.isfinite(speed) or speed <= 1e-15:
            raise ValueError('Curve tangent is undefined at a sampling point.')
        position = (point.X(), point.Y(), point.Z())
        tangent = (velocity.X()/speed, velocity.Y()/speed, velocity.Z()/speed)
        axis = () if guide is None else frame_axis(adaptor, t, point, velocity, tangent, guide, align)
        samples.append((*position, *tangent, t, *axis))
    return samples


def curvature_samples(adaptor, params, wanted):
    from OCP.gp import gp_Pnt, gp_Vec

    samples = []
    for t in params:
        if not wanted():
            return []
        point, velocity, acceleration = gp_Pnt(), gp_Vec(), gp_Vec()
        try:
            adaptor.D2(t, point, velocity, acceleration)
        except RuntimeError as exc:
            raise ValueError('Curve curvature is undefined at a sampling parameter.') from exc
        speed = velocity.Magnitude()
        if not math.isfinite(speed) or speed <= 1e-15:
            raise ValueError('Curve curvature needs a nonzero tangent.')
        tangent = (velocity.X()/speed, velocity.Y()/speed, velocity.Z()/speed)
        second = (acceleration.X(), acceleration.Y(), acceleration.Z())
        perpendicular = sub(second, scale(tangent, dot(second, tangent)))
        vector = tuple(finite_number(v / speed / speed) for v in perpendicular)
        samples.append((point.X(), point.Y(), point.Z(), *vector))
    return samples


def measure_containment(plan, wanted):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT
    from OCP.gp import gp_Pnt2d
    from serpentine3d.core import geometry as g
    from .moves import geometry_from_wire
    from .operation_native import checked
    from .scene_curves import materialize

    sources, rows = plan.get('sources'), plan.get('rows')
    if (not isinstance(sources, list) or len(sources) > MAX_ITEMS or not isinstance(rows, list)
            or len(rows) > MAX_ITEMS or any(not isinstance(row, list) for row in rows)
            or sum(map(len, rows)) > MAX_ITEMS):
        raise ValueError('Invalid or oversized Point In Curve request.')
    regions, budget = {}, [MAX_ITEMS]
    tol = g.tol()
    classifier = BRepClass_FaceClassifier()
    output = []
    for row in rows:
        codes = []
        for index, position in row:
            if not wanted():
                return []
            if type(index) is not int or not 0 <= index < len(sources):
                raise ValueError('Invalid Point In Curve boundary index.')
            if index not in regions:
                curve = geometry_from_wire(sources[index], budget=budget)
                if not is_sample_curve(curve):
                    raise ValueError('Point In Curve needs a closed planar curve.')
                try:
                    boundary = materialize(curve)
                    face = checked(g.planar_face(boundary))
                except (ValueError, g.GeometryError) as exc:
                    raise ValueError('Point In Curve needs a valid closed planar curve.') from exc
                frame = BRepAdaptor_Surface(face).Plane().Position()
                regions[index] = (face, boundary, *(g.pnt_tuple(v) for v in
                    (frame.Location(), frame.XDirection(), frame.YDirection(), frame.Direction())))
            face, boundary, origin, axis_x, axis_y, normal = regions[index]
            position = xyz(position)
            delta = sub(position, origin)
            if abs(dot(delta, normal)) > tol:
                codes.append(0)
                continue
            classifier.Perform(face, gp_Pnt2d(dot(delta, axis_x), dot(delta, axis_y)), tol)
            state = classifier.State()
            if state != TopAbs_ON:
                # The UV classifier can miss exact edge points at a curve seam.
                nearest = BRepExtrema_DistShapeShape(g.make_point(position), boundary)
                if nearest.IsDone() and nearest.NbSolution() and nearest.Value() <= tol:
                    state = TopAbs_ON
            if state not in (TopAbs_OUT, TopAbs_ON, TopAbs_IN):
                raise ValueError('OpenCascade could not classify the point.')
            codes.append({TopAbs_OUT: 0, TopAbs_ON: 1, TopAbs_IN: 2}[state])
        output.append(codes)
    return output


def projection_segments(adaptor, wire):
    """Map the trimmed OCC edges to the parameter space used by Evaluate Curve."""
    start, end = parameter_domain(adaptor)
    if wire is None:
        return ((adaptor, start, end, False),)
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_C0
    from OCP.TColStd import TColStd_Array1OfReal
    from OCP.TopoDS import TopoDS_Edge

    count = adaptor.NbIntervals(GeomAbs_C0)
    knots = TColStd_Array1OfReal(1, count + 1)
    adaptor.Intervals(knots, GeomAbs_C0)
    segments = []
    for i in range(1, count + 1):
        left, right = knots.Value(i), knots.Value(i + 1)
        if left >= right:
            raise ValueError('Curve wire contains a zero-length parameter interval.')
        edge = TopoDS_Edge()
        (first,) = adaptor.Edge(left + (right - left) / 3, edge)
        (second,) = adaptor.Edge(right - (right - left) / 3, edge)
        segments.append((BRepAdaptor_Curve(edge), left, right, second < first))
    return tuple(segments)


def closest_on_curve(adaptor, segments, xyz_point, normalized, wanted):
    from OCP.Extrema import Extrema_ExtPC
    from OCP.gp import gp_Pnt

    target = gp_Pnt(*xyz_point)
    best = None
    for edge, start, end, reverse in segments:
        if not wanted():
            return None
        first, last = parameter_domain(edge)
        extrema = Extrema_ExtPC(target, edge, first, last, 1e-10)
        params = [first, last]
        if extrema.IsDone():
            params.extend(extrema.Point(i).Parameter() for i in range(1, extrema.NbExt() + 1))
        for parameter in params:
            fraction = (parameter - first) / (last - first)
            t = start + (end - start) * (1 - fraction if reverse else fraction)
            point = edge.Value(parameter)
            candidate = (target.SquareDistance(point), t, point)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    distance, parameter, point = best
    if normalized:
        start, end = parameter_domain(adaptor)
        parameter = (parameter - start) / (end - start)
    return (*point.Coord(), parameter, math.sqrt(distance))


def measure_closest(plan, wanted):
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    sources, rows = plan.get('sources'), plan.get('rows')
    if (not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SAMPLES
            or not isinstance(rows, list) or len(rows) > MAX_ITEMS
            or any(not isinstance(row, list) for row in rows) or sum(map(len, rows)) > MAX_SAMPLES):
        raise ValueError('Invalid Curve Closest Point request.')
    budget, cached, comparisons, output = [MAX_ITEMS], {}, 0, []
    for row in rows:
        values = []
        for query in row:
            if not wanted():
                return []
            if (not isinstance(query, list) or len(query) != 3 or type(query[0]) is not int
                    or not 0 <= query[0] < len(sources) or type(query[2]) is not bool):
                raise ValueError('Invalid curve projection query.')
            index, point, normalized = query
            if index not in cached:
                recipe = geometry_from_wire(sources[index], budget=budget)
                if not is_sample_curve(recipe):
                    raise ValueError('Curve Closest Point requires curve data.')
                adaptor, wire, _ = curve_adaptor(materialize(recipe))
                cached[index] = adaptor, projection_segments(adaptor, wire)
            adaptor, segments = cached[index]
            comparisons += len(segments)
            if comparisons > 100_000:
                raise ValueError('Curve Closest Point exceeds the edge comparison limit.')
            value = closest_on_curve(adaptor, segments, xyz(point), normalized, wanted)
            if value is None:
                return []
            values.append(value)
        output.append(values)
    return output


def measure(plan, wanted):
    from .array_along_curve import ARRAY_ALONG_CURVE
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    operation, rows = plan.get('operation'), plan.get('rows')
    if operation == POINT_IN_CURVE:
        return measure_containment(plan, wanted)
    if operation == CLOSEST_POINT:
        return measure_closest(plan, wanted)
    if operation == ARRAY_ALONG_CURVE:
        from .placement_native import measure_curve_array
        return measure_curve_array(plan, wanted)
    if operation not in SAMPLING_SPECS or not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise ValueError('Invalid curve sampling request.')
    shapes, results = {}, []
    budget = [MAX_ITEMS]
    with_frames = operation in FRAME_OPERATIONS
    limit = available = MAX_FRAMES if with_frames else MAX_SAMPLES
    name = SAMPLING_SPECS[operation]['name']
    for row in rows:
        if not wanted():
            return []
        value = geometry_from_wire(row['curve'], budget=budget)
        if not is_sample_curve(value):
            raise ValueError('Curve sampling accepts only curve recipes.')
        if value not in shapes:
            shapes[value] = curve_adaptor(materialize(value))
        adaptor, wire, closed = shapes[value]
        if operation == 'curve_domain':
            results.append(parameter_domain(adaptor))
            continue
        if operation == CURVE_LENGTH:
            results.append(arc_length(adaptor))
            continue
        guide = unit(xyz(row.get('guide'))) if with_frames else None
        align = row.get('align', True)
        if type(align) is not bool:
            raise ValueError('Align must be Boolean.')
        if operation in EXPLICIT_SAMPLING:
            params = explicit_parameters(adaptor, row.get('parameters'), row.get('normalized'), name)
        elif operation == DIVIDE_BY_LENGTH:
            params = length_parameters(adaptor, closed, row.get('length'), row.get('remainder'), available)
        else:
            count, kinks = row.get('count'), row.get('kinks', False)
            if type(count) is not int or not 1 <= count <= MAX_DIVISIONS or type(kinks) is not bool:
                raise ValueError('Expected Count between 1 and 500 and Boolean Kinks.')
            if count + (not closed) > available:
                raise ValueError(f'{name} exceeds the {limit:,}-sample limit.')
            params = division_parameters(adaptor, wire, closed, count, kinks)
        available -= len(params)
        if available < 0:
            raise ValueError(f'{name} exceeds the {limit:,}-sample limit.')
        results.append(curvature_samples(adaptor, params, wanted) if operation == CURVATURE
                       else sample_at(adaptor, params, wanted, guide, align))
    return results
