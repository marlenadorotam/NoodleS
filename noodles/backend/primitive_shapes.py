"""Serpentine extension factories and CLI commands. Shared by native tools and NoodleS."""
import math

from .solids import SolidValue, truncated_cone_dimensions

TRUNCATED_CONE_DIRECTION = 'NoodleS.TruncatedCone.HeightSign'
HEIGHT_SIGN_KEYS = {'truncated_cone': TRUNCATED_CONE_DIRECTION, 'pyramid': 'NoodleS.Pyramid.HeightSign'}


def make_axial(kind, origin, frame, radius, height, solid=True, *, top_radius=0.):
    """Exact Cylinder v.2 / Cone / quadratic Paraboloid from our former plugins."""
    from .curves import PlaneValue, scale
    from .datatree import finite
    if kind not in ('cylinder', 'cone', 'truncated_cone', 'paraboloid') or type(solid) is not bool:
        raise ValueError('Invalid axial primitive or Solid flag.')
    radius, height = finite(radius), finite(height)
    if kind == 'truncated_cone':
        radius, top_radius, height = truncated_cone_dimensions(radius, top_radius, height)
    normal = frame.normal
    if kind in ('cone', 'truncated_cone') and height < 0:
        normal = scale(normal, -1)
        height = -height
    if min(radius, height) <= 1e-9:
        raise ValueError('Radius and Height must be greater than 1e-9.')
    frame = PlaneValue(origin, frame.axis_x, normal)
    from OCP.gp import gp_Ax2, gp_Ax1, gp_Dir, gp_Pnt
    ax = gp_Ax2(gp_Pnt(*frame.origin), gp_Dir(*frame.normal), gp_Dir(*frame.axis_x))
    if kind in ('cylinder', 'cone', 'truncated_cone'):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone
        maker = (BRepPrimAPI_MakeCylinder(ax, radius, height) if kind == 'cylinder'
                 else BRepPrimAPI_MakeCone(ax, radius, top_radius, height))
        maker.Build()
        if not maker.IsDone():
            raise ValueError('OpenCascade could not build '+kind+'.')
        return maker.Solid() if solid else maker.Face()
    # Quadratic Bezier meridian: radial(t)=R*t, axial(t)=H*t*t exactly.
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.Geom import Geom_BezierCurve, Geom_SurfaceOfRevolution
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from .curves import add
    poles = TColgp_Array1OfPnt(1, 3)
    for i, (r, z) in enumerate(((0., 0.), (radius/2, 0.), (radius, height)), 1):
        poles.SetValue(i, gp_Pnt(*add(frame.origin, add(scale(frame.axis_x, r), scale(frame.normal, z)))))
    surface = Geom_SurfaceOfRevolution(Geom_BezierCurve(poles), gp_Ax1(gp_Pnt(*frame.origin), gp_Dir(*frame.normal)))
    maker = BRepBuilderAPI_MakeFace(surface, 0., 2*math.pi, 0., 1., 1e-7)
    if not maker.IsDone():
        raise ValueError('OpenCascade could not build Paraboloid.')
    return maker.Face()


def make_pyramid(value):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g
    from .curves import add, scale

    width, depth, height = value.dimensions
    frame = value.frame
    base = [frame.at(x*width/2, y*depth/2) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    tip = add(frame.origin, scale(frame.normal, height))
    sides = [[a, b, tip] for a, b in zip(base, base[1:] + base[:1])]
    polygons = [*sides, base[::-1]] if value.solid else sides
    if height < 0:
        polygons = [polygon[::-1] for polygon in polygons]
    faces = [g.planar_face(g.make_polyline(points, closed=True)) for points in polygons]
    shape = g.join_surfaces(faces)
    expected = TopAbs_SOLID if value.solid else TopAbs_SHELL
    if (shape.ShapeType() != expected or not BRepCheck_Analyzer(shape).IsValid()
            or value.solid and not BRepLib.OrientClosedSolid_s(TopoDS.Solid_s(shape))):
        raise ValueError('OpenCascade could not build a valid Pyramid.')
    return shape


def materialize(value):
    from serpentine3d.core import geometry as g
    frame = value.frame
    if value.kind in ('cylinder', 'cone', 'paraboloid'):
        return make_axial(value.kind, frame.origin, frame, *value.dimensions, value.solid)
    if value.kind == 'truncated_cone':
        base_radius, top_radius, height = value.dimensions
        return make_axial(value.kind, frame.origin, frame, base_radius, height, value.solid, top_radius=top_radius)
    if value.kind == 'sphere':
        return g.make_sphere(frame.origin, value.dimensions[0])
    if value.kind == 'ellipsoid':
        from .ellipsoid_native import make_ellipsoid
        return make_ellipsoid(value)
    if value.kind == 'torus':
        return g.make_torus(frame.origin, *value.dimensions, axis=frame.normal)
    if value.kind == 'pyramid':
        return make_pyramid(value)
    if value.kind not in ('box', 'box_from_center'):
        raise ValueError('Unknown solid recipe.')
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    shape = g.make_box((0., 0., 0.), *value.dimensions)
    x, y, z, origin = frame.axis_x, frame.axis_y, frame.normal, frame.origin
    if value.kind == 'box_from_center':
        origin = frame.at(-value.dimensions[0]/2, -value.dimensions[1]/2)
    transform = gp_Trsf()
    transform.SetValues(x[0], y[0], z[0], origin[0], x[1], y[1], z[1], origin[1], x[2], y[2], z[2], origin[2])
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def register_commands(ctx):
    """Add missing tools without overriding Serpentine's own cylinder/cone commands."""
    req = ctx.requests()
    from .curves import PlaneValue
    from serpentine3d.core import geometry as g

    @ctx.command('pointcylindrical', label='Point Cylindrical')
    def point_cylindrical(c):
        from .data_helpers import cylindrical_coordinates
        cp = c.cplane
        frame = PlaneValue(tuple(map(float, cp.origin)), tuple(map(float, cp.xdir)), tuple(map(float, cp.normal)))
        angle = yield req.NumberReq('Angle in radians', default=0.)
        radius = yield req.NumberReq('Radius', default=1., minimum=0.)
        elevation = yield req.NumberReq('Elevation', default=0.)
        c.scene.add(g.make_point(cylindrical_coordinates(frame, angle, radius, elevation)))

    @ctx.command('pyramid', label='Pyramid · NoodleS primitives')
    def pyramid(c):
        from .curves import dot, sub
        from serpentine3d.core.user_text import with_value

        mode = yield req.OptionReq('Pyramid type', options=['Solid', 'Shell'], default='Solid')
        if mode not in ('Solid', 'Shell'):
            c.echo('Choose Solid or Shell.')
            return
        center = yield req.PointReq('Base center (click or type X,Y,Z)')
        cp = c.cplane
        frame = PlaneValue(tuple(map(float, center)), tuple(map(float, cp.xdir)), tuple(map(float, cp.normal)))
        width = yield req.NumberReq('Base Width', default=10., minimum=1e-8)
        depth = yield req.NumberReq('Base Depth', default=10., minimum=1e-8)

        def build(point):
            height = dot(sub(point, frame.origin), frame.normal)
            if not math.isfinite(height) or abs(height) <= 1e-9:
                return None, height
            value = SolidValue('pyramid', 'pyramid', frame, (width, depth, height), mode == 'Solid')
            return make_pyramid(value), height

        axis = frame.origin, frame.normal
        picked = yield req.PointReq('Height (click or type a signed number)', axis_lock=axis,
            number_from=axis, rubber_from=frame.origin, preview_fn=lambda p: build(p)[0])
        shape, height = build(picked)
        if shape is None:
            c.echo('Height must be nonzero.')
            return
        with c.scene.batched():
            obj = c.scene.add(shape)
            if height < 0:
                c.scene.update(obj.id, user_text=with_value(obj.user_text, HEIGHT_SIGN_KEYS['pyramid'], '-1'))
        c.echo('Created '+obj.name+'.')

    @ctx.command('ellipsoideparam', label='Ellipsoid · NoodleS primitives')
    def ellipsoid(c):
        from .ellipsoid_native import make_ellipsoid

        mode = yield req.OptionReq('Ellipsoid type', options=['Solid', 'Shell'], default='Solid')
        if mode not in ('Solid', 'Shell'):
            c.echo('Choose Solid or Shell.')
            return
        center = yield req.PointReq('Center (click or type X,Y,Z)')
        cp = c.cplane
        frame = PlaneValue(tuple(map(float, center)), tuple(map(float, cp.xdir)), tuple(map(float, cp.normal)))
        x = yield req.NumberReq('Radius X', default=10., minimum=1e-8)
        y = yield req.NumberReq('Radius Y', default=7., minimum=1e-8)
        z = yield req.NumberReq('Radius Z', default=5., minimum=1e-8)
        value = SolidValue('ellipsoid', 'ellipsoid', frame, (x, y, z), mode == 'Solid')
        obj = c.scene.add(make_ellipsoid(value))
        c.echo('Created '+obj.name+'.')

    def command(kind, label):
        def run(c):
            truncated = kind == 'truncated_cone'
            signed = truncated or kind == 'cone'
            solid = False
            if kind != 'paraboloid':
                mode = yield req.OptionReq(label+' type', options=['Solid', 'Shell'], default='Solid')
                if mode not in ('Solid', 'Shell'):
                    c.echo('Choose Solid or Shell.')
                    return
                solid = mode == 'Solid'
            origin_label = 'Vertex' if kind == 'paraboloid' else 'Base center'
            picked = yield req.PointReq(origin_label + ' (click or type X,Y,Z)')
            cp = c.cplane
            # The viewport and CPlane can supply NumPy arrays/scalars.
            # Keep those types out of the shared recipe validators.
            base = tuple(map(float, picked))
            frame = PlaneValue(base, tuple(map(float, cp.xdir)), tuple(map(float, cp.normal)))
            def radius_preview(point):
                radius = math.dist(base, point)
                return g.make_circle(base, radius, frame.normal) if radius > 1e-9 else None
            radius_label = 'Base Radius' if truncated else 'Radius'
            rim = yield req.PointReq(radius_label + ' (click or type number)', number_from=(base, frame.axis_x),
                                    rubber_from=base, preview_fn=radius_preview)
            radius = math.dist(base, rim)
            if not math.isfinite(radius) or radius <= 1e-9:
                c.echo('Radius must be positive.')
                return
            top_radius = 0.
            if truncated:
                top_point = yield req.PointReq('Top Radius (click or type number)',
                    number_from=(base, frame.axis_x), rubber_from=base, preview_fn=radius_preview)
                try:
                    _, top_radius, _ = truncated_cone_dimensions(radius, math.dist(base, top_point), 1.)
                except ValueError as exc:
                    c.echo(str(exc))
                    return
            def height_at(point):
                return math.fsum((point[i]-base[i])*frame.normal[i] for i in range(3))
            def valid_height(height):
                magnitude = abs(height) if signed else height
                return math.isfinite(height) and magnitude > 1e-9
            def height_preview(point):
                height = height_at(point)
                return (make_axial(kind, base, frame, radius, height, solid, top_radius=top_radius)
                        if valid_height(height) else None)
            height_label = 'Apex height' if kind == 'cone' else 'Height'
            prompt = height_label + (' (click or type a signed number)' if signed else ' (click or type number)')
            top = yield req.PointReq(prompt, axis_lock=(base, frame.normal),
                number_from=(base, frame.normal), rubber_from=base, preview_fn=height_preview)
            height = height_at(top)
            if not valid_height(height):
                c.echo('Height must be nonzero.' if signed else 'Height must be positive.')
                return
            shape = make_axial(kind, base, frame, radius, height, solid, top_radius=top_radius)
            native = c.scene.add(shape)
            if truncated and height < 0:
                from serpentine3d.core.user_text import with_value
                c.scene.update(native.id, user_text=with_value(native.user_text, TRUNCATED_CONE_DIRECTION, '-1'))
            c.echo('Created '+native.name+'.')
        return run

    for name, kind, label, aliases in (('cylinderparam', 'cylinder', 'Cylinder', ('cylinderex',)),
            ('coneparam', 'cone', 'Cone', ('coneex',)),
            ('truncatedcone', 'truncated_cone', 'Truncated Cone', ()),
            ('paraboloid', 'paraboloid', 'Paraboloid', ())):
        ctx.command(name, aliases=aliases, label=label+' · NoodleS primitives')(command(kind, label))
