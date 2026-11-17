"""Exact OCC profile pieces and orientation checks."""
import math

from .curve_sampling_native import curve_adaptor, explicit_parameters, parameter_domain, projection_segments
from .profile_operations import FLIP_CURVE, MOVE_SEAM


def _edge(curve, start, end):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

    if start > end:
        start, end = curve.ReversedParameter(start), curve.ReversedParameter(end)
        curve = curve.Reversed()
    builder = BRepBuilderAPI_MakeEdge(curve, start, end)
    if not builder.IsDone():
        raise ValueError('OpenCascade could not trim a curve fragment.')
    return builder.Edge()


def _piece(edges):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
    from OCP.BRepCheck import BRepCheck_Analyzer

    if len(edges) == 1:
        shape = edges[0]
    else:
        builder = BRepBuilderAPI_MakeWire()
        for edge in edges:
            builder.Add(edge)
            if not builder.IsDone():
                raise ValueError('OpenCascade could not reconnect the curve fragments.')
        shape = builder.Wire()
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError('OpenCascade returned an invalid curve fragment.')
    return shape


def _interval_edges(segments, start, end):
    from OCP.BRep import BRep_Tool

    for adaptor, left, right, reverse in segments:
        a, b = max(left, start), min(right, end)
        if a >= b:
            continue
        first, last = parameter_domain(adaptor)
        start_fraction, end_fraction = (a-left)/(right-left), (b-left)/(right-left)
        if reverse:
            start_fraction, end_fraction = 1-start_fraction, 1-end_fraction
        curve = BRep_Tool.Curve_s(adaptor.Edge(), 0., 0.)
        yield _edge(curve, first+(last-first)*start_fraction, first+(last-first)*end_fraction)


def _cut_parameters(adaptor, options, name):
    first, last = parameter_domain(adaptor)
    normalized, values = options
    params = explicit_parameters(adaptor, values, normalized, name) if values else []
    tolerance = max((last-first)*1e-12, 8*math.ulp(first), 8*math.ulp(last))
    return first, last, params, tolerance


def shatter_intervals(adaptor, options):
    first, last, params, tolerance = _cut_parameters(adaptor, options, 'Shatter')
    cuts = [first]
    for parameter in sorted(params):
        if parameter-cuts[-1] > tolerance and last-parameter > tolerance:
            cuts.append(parameter)
    return tuple(zip(cuts, (*cuts[1:], last)))


def shatter_fragment(shape, span):
    adaptor, wire, _ = curve_adaptor(shape)
    first, last = parameter_domain(adaptor)
    start, end = span
    if not first <= start < end <= last:
        raise ValueError('Shatter fragment is outside the native curve domain.')
    if (start, end) == (first, last):
        return shape
    return _piece(list(_interval_edges(projection_segments(adaptor, wire), start, end)))


def seam_parameter(adaptor, closed, options):
    if not closed:
        raise ValueError('Move Seam requires a closed curve.')
    first, last, params, tolerance = _cut_parameters(adaptor, options, 'Move Seam')
    parameter = params[0]
    return first if min(parameter-first, last-parameter) <= tolerance else parameter


def flip_required(shape, guide=None):
    if guide is None:
        return True
    a, _, a_closed = curve_adaptor(shape)
    b, _, b_closed = curve_adaptor(guide)
    if a_closed != b_closed:
        raise ValueError('Flip Curve needs a guide with matching open or closed status.')
    first, last = parameter_domain(a)
    start, end = parameter_domain(b)
    if not a_closed:
        a0, a1, b0, b1 = a.Value(first), a.Value(last), b.Value(start), b.Value(end)
        return a0.SquareDistance(b1) + a1.SquareDistance(b0) < a0.SquareDistance(b0) + a1.SquareDistance(b1)
    count = 24
    points = [a.Value(first + (last-first)*i/count) for i in range(count)]
    guides = [b.Value(start + (end-start)*i/count) for i in range(count)]

    def cost(direction):
        return min(sum(p.SquareDistance(guides[(offset+direction*i) % count]) for i, p in enumerate(points))
                   for offset in range(count))

    forward, reverse = cost(1), cost(-1)
    return reverse < forward and not math.isclose(forward, reverse, rel_tol=1e-12, abs_tol=1e-16)


def profile_geometry(operation, shapes, options):
    from OCP.BRep import BRep_Tool
    from serpentine3d.core import geometry as g

    shape = shapes[0]
    if operation == FLIP_CURVE:
        if not flip_required(*shapes):
            return (shape,)
        _, wire, _ = curve_adaptor(shape)
        return (wire.Reversed() if wire is not None else g.reverse_curve(shape),)
    adaptor, wire, closed = curve_adaptor(shape)
    first, last = parameter_domain(adaptor)
    if operation == MOVE_SEAM:
        seam = seam_parameter(adaptor, closed, options)
        if seam == first:
            return (shape,)
        if wire is None:
            curve = BRep_Tool.Curve_s(adaptor.Edge(), 0., 0.)
            if curve.IsPeriodic() and math.isclose(last-first, curve.Period(), rel_tol=1e-12):
                return (_piece([_edge(curve, seam, seam+curve.Period())]),)
        segments = projection_segments(adaptor, wire)
        edges = [*_interval_edges(segments, seam, last), *_interval_edges(segments, first, seam)]
        result = _piece(edges)
        if not BRep_Tool.IsClosed_s(result):
            raise ValueError('OpenCascade could not keep the shifted profile closed.')
        return (result,)
    intervals = shatter_intervals(adaptor, options)
    if len(intervals) == 1:
        return (shape,)
    segments = projection_segments(adaptor, wire)
    return tuple(_piece(list(_interval_edges(segments, a, b))) for a, b in intervals)


def profile_metadata(operation, shapes, options):
    if operation == FLIP_CURVE:
        return flip_required(*shapes)
    adaptor, _, closed = curve_adaptor(shapes[0])
    if operation == MOVE_SEAM:
        return adaptor.Value(seam_parameter(adaptor, closed, options)).Coord()
    return shatter_intervals(adaptor, options)
