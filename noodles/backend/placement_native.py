"""Native object placement and transform factories."""
from functools import lru_cache
import math

from .curves import PlaneValue, add, cross, dot, scale, sub, unit, xyz


@lru_cache(maxsize=64)
def _anchor(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Sphere, GeomAbs_Torus
    from serpentine3d.core import geometry as g

    shape = g.unwrap_compound(shape)
    kind = g.shape_kind(shape)
    z = (0., 0., 1.)
    if kind == 'point':
        return xyz(tuple(g.point_coords(shape))), z
    if kind == 'curve':
        edges = g.edges_of(shape)
        if len(edges) == 1 and g.is_closed_curve(shape):
            curve = BRepAdaptor_Curve(edges[0])
            if curve.GetType() == GeomAbs_Circle:
                circle = curve.Circle()
                return g.pnt_tuple(circle.Location()), g.pnt_tuple(circle.Axis().Direction())
        if not g.is_closed_curve(shape):
            return g.curve_endpoints(shape)[0], z
    if kind in ('surface', 'solid'):
        for face in g.faces_of(shape):
            surface = BRepAdaptor_Surface(face, True)
            if surface.GetType() == GeomAbs_Sphere:
                return g.pnt_tuple(surface.Sphere().Location()), z
            if surface.GetType() == GeomAbs_Torus:
                torus = surface.Torus()
                return g.pnt_tuple(torus.Location()), g.pnt_tuple(torus.Axis().Direction())
    low, high = g.bbox(shape)
    return tuple((a+b)/2 for a, b in zip(low, high)), z


@lru_cache(maxsize=128)
def _oriented(shape, normal, factors):
    from serpentine3d.core import geometry as g

    anchor, source_normal = _anchor(shape)
    centered = g.translate(shape, scale(anchor, -1))
    zero = (0., 0., 0.)
    if len(set(factors)) > 1:
        centered = g.scale(centered, zero, 1., factors=factors)
    elif factors[0] != 1.:
        centered = g.scale(centered, zero, factors[0])
    axis = cross(source_normal, normal)
    sine = math.hypot(*axis)
    cosine = dot(source_normal, normal)
    if sine > 1e-10:
        return g.rotate(centered, zero, scale(axis, 1/sine), math.degrees(math.atan2(sine, cosine)))
    if cosine < 0:
        trial = (1., 0., 0.) if abs(source_normal[0]) < .9 else (0., 1., 0.)
        return g.rotate(centered, zero, unit(cross(source_normal, trial)), 180.)
    return centered


def place_shape(shape, destination, normal, factors):
    return _translate(_oriented(shape, normal, factors), destination)


def _translate(shape, offset):
    from OCP.gp import gp_Trsf, gp_Vec
    from serpentine3d.core import geometry as g

    motion = gp_Trsf()
    motion.SetTranslation(gp_Vec(*offset))
    return g._apply_trsf(shape, motion, copy=False)


def materialize(value, shape):
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf
    from serpentine3d.core import geometry as g

    if value.kind == 'array':
        return _translate(shape, value.vector)
    if value.kind == 'array_polar':
        motion = gp_Trsf()
        motion.SetRotation(gp_Ax1(gp_Pnt(*value.axis.origin), gp_Dir(*value.axis.normal)), math.radians(value.angle))
        return g._apply_trsf(shape, motion, copy=False)
    return place_shape(shape, value.vector, *value.placement)


def _curve_array_motions(shape, count, orientation, wanted):
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
    from serpentine3d.core import geometry as g
    from .curve_sampling_native import curve_adaptor, division_parameters, sample_at
    from .rigid_motion import IDENTITY, RigidMotion

    adaptor, wire, closed = curve_adaptor(shape)
    if count == 1:
        return (IDENTITY,)
    reverse = shape.ShapeType() == TopAbs_EDGE and shape.Orientation() == TopAbs_REVERSED
    params = division_parameters(adaptor, wire, False, count - 1 + int(closed), False)
    if reverse:
        params.reverse()
    if closed:
        params.pop()
    if orientation == 0:
        points = tuple(g.pnt_tuple(adaptor.Value(t)) for t in params)
        return tuple(RigidMotion(offset=sub(p, points[0])) for p in points)

    samples = sample_at(adaptor, params, wanted)
    if not samples:
        return ()
    positions = tuple(row[:3] for row in samples)
    tangents = tuple(scale(row[3:6], -1.) if reverse else row[3:6] for row in samples)
    if orientation == 1:
        # Match Serpentine's rotation-minimizing frame transport for free rotation.
        import numpy as np
        p, t = np.asarray(positions), np.asarray(tangents)
        up = g._seed_up(t[0])
        frames = [PlaneValue(positions[0], tuple(up.tolist()), tangents[0])]
        for i in range(1, count):
            up = g._carry_up(p[i-1], t[i-1], up, p[i], t[i])
            frames.append(PlaneValue(positions[i], tuple(up.tolist()), tangents[i]))
    else:
        z = (0., 0., 1.)
        headings = tuple((x, y, 0.) for x, y, _ in tangents)
        heading = next((unit(v) for v in headings if math.hypot(*v) > 1e-8), (1., 0., 0.))
        frames = []
        for point, tangent, projected in zip(positions, tangents, headings):
            if math.hypot(*projected) > 1e-8:
                heading = unit(projected)
            frame = (PlaneValue(point, cross(z, heading), tangent) if orientation == 2
                     else PlaneValue(point, heading, z))
            frames.append(frame)

    def pose(frame):
        return RigidMotion(tuple(zip(frame.axis_x, frame.axis_y, frame.normal)), frame.origin)

    first = pose(frames[0]).inverse()
    return (IDENTITY, *(pose(frame).after(first) for frame in frames[1:]))


def measure_curve_array(plan, wanted):
    from .array_along_curve import MAX_COPIES, ORIENTATIONS
    from .curve_sampling import MAX_DIVISIONS, is_sample_curve
    from .moves import geometry_from_wire
    from .scene_curves import materialize
    from .splines import integer

    rows = plan.get('rows')
    if not isinstance(rows, list) or len(rows) > MAX_COPIES:
        raise ValueError('Invalid curve array plan.')
    budget, count_total, shapes, results = [10000], 0, {}, []
    for row in rows:
        if not wanted():
            return []
        count = integer(row.get('count'), 'Count', 1, MAX_DIVISIONS)
        orientation = integer(row.get('orientation'), 'Orientation', 0, len(ORIENTATIONS) - 1)
        count_total += count
        if count_total > MAX_COPIES:
            raise ValueError(f'Array Along Curve supports up to {MAX_COPIES:,} placements per node.')
        curve = geometry_from_wire(row['curve'], budget=budget)
        if not is_sample_curve(curve):
            raise ValueError('Array Along Curve requires a rail curve.')
        if curve not in shapes:
            shapes[curve] = materialize(curve)
        results.append([motion.to_wire() for motion in _curve_array_motions(shapes[curve], count, orientation, wanted)])
    return results


def register_commands(ctx):
    from .operation_native import native_job
    from .placement import placement_scale

    req = ctx.requests()

    @ctx.command('objectsonpoints', mutates=False, label='Objects on Points')
    def objects_on_points(c):
        from serpentine3d.core import geometry as g

        source = yield req.SelectReq('Select object to place', max_count=1)
        points = yield req.SelectReq('Select placement points', kinds=('point',))
        factor = yield req.NumberReq('Uniform scale', default=1.)
        factors = placement_scale(factor)
        normal = unit(xyz(tuple(c.cplane.normal)))
        if not 1 <= len(points) <= 2000:
            raise ValueError('Select 1–2000 placement points.')

        def build(shapes):
            return [place_shape(shapes[0], g.point_coords(p), normal, factors) for p in shapes[1:]]

        native_job(ctx, c, [*source, *points], build, 'Objects on Points')
