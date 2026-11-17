"""Curve offset with an explicit construction-plane side for straight paths."""
import math

from .arithmetic import finite_number
from .curves import cross, dot, scale, sub, unit, xyz


def straight_tangent(shape):
    """Recognize a line or a wire made entirely of collinear line edges."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED, TopAbs_WIRE
    from serpentine3d.core import geometry as g

    if shape.ShapeType() not in (TopAbs_EDGE, TopAbs_WIRE):
        return None
    first = g._ordered_edges(shape)[0]
    adaptor = BRepAdaptor_Curve(first)
    if adaptor.GetType() != GeomAbs_Line:
        return None
    origin = g.pnt_tuple(adaptor.Value(adaptor.FirstParameter()))
    tangent = g.pnt_tuple(adaptor.Line().Direction())
    if first.Orientation() == TopAbs_REVERSED:
        tangent = scale(tangent, -1.)
    for edge in g.edges_of(shape):
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() != GeomAbs_Line:
            return None
        direction = g.pnt_tuple(curve.Line().Direction())
        point = g.pnt_tuple(curve.Value(curve.FirstParameter()))
        if math.hypot(*cross(direction, tangent)) > 1e-10 or math.hypot(*cross(sub(point, origin), tangent)) > g.tol():
            return None
    return tangent


def straight_side(tangent, normal):
    side = cross(tangent, unit(xyz(normal)))
    if math.hypot(*side) <= 1e-12:
        raise ValueError('The line is parallel to the construction plane normal. Choose a different construction plane.')
    return unit(side)


def offset_curve_shape(shape, distance, normal=(0., 0., 1.)):
    from serpentine3d.core import geometry as g

    distance = finite_number(distance)
    shape = g.unwrap_compound(shape)
    if distance == 0.:
        return shape
    tangent = straight_tangent(shape)
    if tangent is not None:
        return g.translate(shape, scale(straight_side(tangent, normal), distance))
    return g.unwrap_compound(g.offset_curve(g.copy_shape(shape), distance))


def offset_geometry_shape(shape, distance, *, fill=False, solid=False, normal=None):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from serpentine3d.core import geometry as g
    from .operation_native import loft_shape

    shape = g.unwrap_compound(shape)
    distance = finite_number(distance)
    if not 1e-8 <= abs(distance) <= 1e7:
        raise ValueError('Offset Distance must be nonzero and have magnitude 1e-8 to 1e7.')
    kind = g.shape_kind(shape)
    if kind == 'surface':
        if fill:
            raise ValueError('Fill applies to curves. Use Solid for surfaces.')
        return offset_surface_shape(shape, distance, solid)
    if kind != 'curve':
        raise ValueError('Offset requires a planar curve or an open surface.')
    if solid:
        raise ValueError('Solid applies to surfaces. Use Fill for curves.')

    axis = (0., 0., 1.) if normal is None else unit(xyz(normal))
    if normal is not None and straight_tangent(shape) is None:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_FindPlane
        plane = BRepBuilderAPI_FindPlane(g.to_wire(shape))
        if not plane.Found():
            raise ValueError('Offset requires a planar curve.')
        alignment = dot(axis, g.pnt_tuple(plane.Plane().Pln().Axis().Direction()))
        if abs(alignment) < 1. - 1e-5:
            raise ValueError('The Offset Plane must be parallel to the curve plane.')
        if alignment < 0.:
            distance = -distance
    shifted = offset_curve_shape(shape, distance, axis)
    if fill:
        return loft_shape([shape, shifted], ruled=True)
    if not BRepCheck_Analyzer(shifted).IsValid() or g.shape_kind(shifted) != 'curve':
        raise ValueError('OpenCascade returned invalid offset curve geometry.')
    return shifted


def guard_surface_curvature(shape, distance):
    """Check directional fold-over at samples inside each trimmed face."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepLProp import BRepLProp_SLProps
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN, TopAbs_REVERSED
    from OCP.gp import gp_Pnt2d
    from serpentine3d.core import geometry as g
    from .surface_uv_native import uv_bounds

    fractions = (.04, .12, .25, .5, .75, .88, .96)
    for face in g.faces_of(shape):
        adaptor = BRepAdaptor_Surface(face, True)
        classifier = BRepTopAdaptor_FClass2d(face, 1e-9)
        u0, u1, v0, v1 = uv_bounds(face)
        signed = -distance if face.Orientation() == TopAbs_REVERSED else distance
        for ui in fractions:
            u = u0 + (u1-u0)*ui
            for vi in fractions:
                v = v0 + (v1-v0)*vi
                if classifier.Perform(gp_Pnt2d(u, v)) != TopAbs_IN:
                    continue
                props = BRepLProp_SLProps(adaptor, u, v, 2, 1e-7)
                if props.IsCurvatureDefined() and max(signed*props.MinCurvature(), signed*props.MaxCurvature()) >= .85:
                    raise ValueError('Surface offset risks folding at a tight curvature. Reduce the distance or reverse its sign.')


def offset_surface_shape(shape, distance, solid):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape, BRepOffsetAPI_MakeThickSolid
    from serpentine3d.core import geometry as g
    from .operation_native import checked

    shape = checked(g.copy_shape(shape))
    guard_surface_curvature(shape, distance)
    if solid:
        maker = BRepOffsetAPI_MakeThickSolid()
        maker.MakeThickSolidBySimple(shape, distance)
    else:
        maker = BRepOffsetAPI_MakeOffsetShape()
        maker.PerformBySimple(shape, distance)
    if not maker.IsDone():
        raise ValueError('OpenCascade could not complete Surface Offset.')
    result = checked(maker.Shape())
    if g.shape_kind(result) != ('solid' if solid else 'surface'):
        raise ValueError('Surface Offset did not produce the requested geometry type.')
    return result.Reversed() if solid and g.volume(result) < 0. else result


def register_commands(ctx):
    from .operation_native import native_job
    req = ctx.requests()

    @ctx.command('offsetfix', mutates=False, label='Offset Fix')
    def offsetfix(c):
        from serpentine3d.commands import dragging
        from serpentine3d.core import geometry as g

        source = yield req.SelectReq('Select curve to offset', kinds=('curve',), max_count=1)
        shape = g.unwrap_compound(source[0].shape)
        normal = tuple(map(float, c.cplane.normal))
        tangent = straight_tangent(shape)
        try:
            side = straight_side(tangent, normal) if tangent is not None else dragging.offset_direction(shape, normal)
        except (ValueError, g.GeometryError) as exc:
            c.echo(str(exc))
            return
        origin = dragging.curve_middle(shape)
        read_distance = dragging.signed_along(origin, side)

        def preview_straight(point):
            from OCP.gp import gp_Trsf, gp_Vec
            from OCP.TopLoc import TopLoc_Location
            distance = read_distance(point)
            if abs(distance) < 1e-9:
                return None
            transform = gp_Trsf()
            transform.SetTranslation(gp_Vec(*scale(side, distance)))
            return shape.Moved(TopLoc_Location(transform))

        point = yield req.PointReq('Offset distance (click a side, or type a signed number)',
                                   axis_lock=(origin, side), number_from=(origin, side), rubber_from=origin,
                                   preview_fn=preview_straight if tangent is not None else None)
        distance = read_distance(point)
        if abs(distance) < 1e-9:
            c.echo('Zero offset.')
            return
        native_job(ctx, c, source, lambda shapes: [offset_curve_shape(shapes[0], distance, normal)],
                   'Offset Fix', single_on_source_layer=True)

    @ctx.command('offsetcurvefill', mutates=False, label='Offset Curve Fill')
    def curve_fill(c):
        from serpentine3d.core import geometry as g
        source = yield req.SelectReq('Select planar curve', kinds=('curve',), max_count=1)
        distance = yield req.NumberReq('Signed offset distance', default=1.)
        plane_normal = tuple(map(float, c.cplane.normal))

        def build(shapes):
            normal = plane_normal if straight_tangent(g.unwrap_compound(shapes[0])) is not None else None
            return [offset_geometry_shape(shapes[0], distance, fill=True, normal=normal)]

        native_job(ctx, c, source, build, 'Offset Curve Fill', single_on_source_layer=True)

    @ctx.command('offsetsurfacev2', mutates=False, label='Offset Surface')
    def surface_offset(c):
        source = yield req.SelectReq('Select surface or open shell', kinds=('surface',), max_count=1)
        distance = yield req.NumberReq('Signed offset distance', default=1.)
        mode = yield req.OptionReq('Result type', options=['Surface', 'Solid'], default='Surface')
        native_job(ctx, c, source,
                   lambda shapes: [offset_geometry_shape(shapes[0], distance, solid=mode == 'Solid')],
                   'Offset Surface', single_on_source_layer=True)
