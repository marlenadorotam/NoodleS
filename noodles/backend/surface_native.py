"""Native surface factories shared by deferred recipes and independent CAD commands.

Point interpolation adapts the project's former surface_from_points plugin.
No scene objects, scheduling, or batch-engine dependencies belong here.
"""
import math


def planar_surface_shape(shapes):
    from serpentine3d.core import geometry as g
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from .operation_native import checked
    if not 1<=len(shapes)<=240:
        raise ValueError('Planar Surface needs 1..240 closed boundaries.')
    faces=[checked(g.planar_face(s)) for s in shapes]
    planes=[BRepAdaptor_Surface(f).Plane() for f in faces]
    base=planes[0]
    for plane in planes[1:]:
        if abs(base.Axis().Direction().Dot(plane.Axis().Direction()))<1-1e-9 or base.Distance(plane.Location())>1e-6:
            raise ValueError('Planar Surface boundaries in one branch must be coplanar.')
    areas=[g.surface_area(face) for face in faces]
    for i,a in enumerate(faces):
        for j in range(i):
            common=g.surface_area(g.boolean_intersection(a,faces[j]))
            tolerance=max(1e-10,min(areas[i],areas[j])*1e-7)
            if common>tolerance and abs(common-min(areas[i],areas[j]))>tolerance:
                raise ValueError('Planar boundaries overlap without containment.')
            if abs(areas[i]-areas[j])<=tolerance and abs(common-areas[i])<=tolerance:
                raise ValueError('Coincident planar boundaries are ambiguous.')
    regions=g.planar_regions(shapes)
    if not regions:
        raise ValueError('No planar surface region was produced.')
    return checked(regions[0] if len(regions)==1 else g.make_compound(regions))


def patch_shape(shapes):
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    if not 1<=len(shapes)<=240 or any(g.shape_kind(s)!='curve' for s in shapes):
        raise ValueError('Patch needs 1..240 boundary Curves per branch.')
    # Use one connected closed outline. Several regions/holes are a different
    # construction; do not let MakeFilling invent bridges across gaps.
    try:
        wire=g.join_curves([g.copy_shape(s) for s in shapes])
    except g.GeometryError as exc:
        raise ValueError('Patch needs one connected closed outline, without separate loops or holes.') from exc
    edges=g.edges_of(wire)
    if not 2<=len(edges)<=240 or not g.is_closed_curve(wire):
        raise ValueError('Patch needs one closed connected outline with 2..240 edges.')
    return checked(g.patch_surface([wire],continuity=0))


def edge_surface_shape(shapes):
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    if len(shapes) not in (2,3,4) or any(len(g.edges_of(s))!=1 for s in shapes):
        raise ValueError('Edge Surface needs 2–4 single-edge curves; explode multi-edge wires first.')
    # Native ordering may reverse its converted curves. Protect the shared
    # source cache and native Reference shapes from any in-place kernel edits.
    return checked(g.edge_surface([g.copy_shape(s) for s in shapes]))


def _preserve_planar_periodic_rims(surface, points, width):
    from OCP.gp import gp_Pnt
    from .curves import dot, scale, sub
    from .delaunay import site_frame

    if (surface.VMultiplicity(1) != surface.VDegree()+1
            or surface.VMultiplicity(surface.NbVKnots()) != surface.VDegree()+1):
        raise ValueError('OpenCascade returned unclamped rims for the periodic grid.')
    for row, pole in ((points[:width], 1), (points[-width:], surface.NbVPoles())):
        try:
            plane = site_frame(row)
        except ValueError:
            continue
        tolerance = max(1e-9, max(math.dist(p, plane.origin) for p in row)*1e-12)
        if any(abs(dot(sub(p, plane.origin), plane.normal)) > tolerance for p in row):
            continue
        # A planar row should interpolate to a planar isocurve. On dense
        # periodic rows OCC can introduce out-of-plane poles between samples.
        for index in range(1, surface.NbUPoles()+1):
            point = surface.Pole(index, pole).Coord()
            height = dot(sub(point, plane.origin), plane.normal)
            surface.SetPole(index, pole, gp_Pnt(*sub(point, scale(plane.normal, height))))


def make_surface_from_points(points, u_count, *, periodic_u=False):
    """Interpolate a U-fastest rectangular grid, with no approximation fallback."""
    from .curves import xyz
    from .splines import integer
    from .operation_native import checked
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    # Serpentine's frozen build includes the extension but omits OCP.Approx.
    from OCP.OCP.Approx import Approx_IsoParametric
    if not isinstance(points,(tuple,list)) or not 4<=len(points)<=2500:
        raise ValueError('Surface from Points requires 4..2500 points.')
    if type(periodic_u) is not bool:
        raise ValueError('Periodic U must be Boolean.')
    u=integer(u_count,'Points per Row',4 if periodic_u else 2,1250)
    if len(points)%u or len(points)//u<2:
        raise ValueError('Point count must be U × V, with U and V at least 2.')
    v=len(points)//u
    points=tuple(xyz(p) for p in points)
    if periodic_u and any(math.dist(points[j*u], points[(j+1)*u-1]) <= 1e-9 for j in range(v)):
        raise ValueError('Periodic U closes each row. Supply its first point only once.')
    # Duplicate rows/columns and collapsed neighbouring samples can make OCC
    # emit a superficially valid face with a singular or folded parametrization.
    if len(set(points))!=len(points):
        raise ValueError('Point grid contains duplicate points.')
    for j in range(v):
        for i in range(u):
            p=points[j*u+i]
            for q in ([points[j*u+i+1]] if i+1<u else [])+([points[(j+1)*u+i]] if j+1<v else []):
                if math.dist(p,q)<=1e-9:
                    raise ValueError('Point grid contains collapsed neighbouring samples.')
    builder=GeomAPI_PointsToBSplineSurface()
    grid=TColgp_Array2OfPnt(1,u,1,v)
    for j in range(v):
        for i in range(u):
            grid.SetValue(i+1,j+1,gp_Pnt(*points[j*u+i]))
    # The former XY height overload produced invalid faces for several valid
    # small rectangular grids in OCP 7.9. Use one rotation-invariant uniform
    # parameter interpolation for every grid, including steep XY heightfields.
    builder.Interpolate(grid, Approx_IsoParametric, periodic_u)
    if not builder.IsDone():
        raise ValueError('OpenCascade could not interpolate this point grid.')
    surface = builder.Surface()
    if periodic_u:
        if not surface.IsUPeriodic():
            raise ValueError('OpenCascade could not close the surface in U.')
        _preserve_planar_periodic_rims(surface, points, u)
    face=BRepBuilderAPI_MakeFace(surface,1e-7)
    if not face.IsDone():
        raise ValueError('OpenCascade could not construct the interpolated face.')
    return checked(face.Face())


def register_commands(ctx):
    from .operation_native import native_job
    req=ctx.requests()
    @ctx.command('planesurface', mutates=False, label='Plane Surface')
    def plane_surface_command(c):
        from .curves import PlaneValue
        from .operations import plane_surface
        from .scene_curves import materialize
        origin = yield req.PointReq('Origin', default=tuple(map(float, c.cplane.origin)))
        frame = PlaneValue(tuple(map(float, origin)), tuple(map(float, c.cplane.xdir)),
                           tuple(map(float, c.cplane.normal)))
        x = yield req.NumberReq('X size', default=10, minimum=1e-8)
        y = yield req.NumberReq('Y size', default=10, minimum=1e-8)
        native_job(ctx, c, (), lambda _: [materialize(plane_surface('plane', frame, x, y))], 'Plane Surface')

    @ctx.command('patchparam',mutates=False,label='Patch')
    def patch(c):
        source=yield req.SelectReq('Select curves forming one closed outline',kinds=('curve',),min_count=1)
        native_job(ctx,c,source,lambda shapes:[patch_shape(shapes)],'Patch')
    @ctx.command('planarsurfaceparam',mutates=False,label='Planar Surface')
    def planar(c):
        source=yield req.SelectReq('Select closed coplanar boundaries (including holes)',kinds=('curve',),min_count=1)
        native_job(ctx,c,source,lambda shapes:[planar_surface_shape(shapes)],'Planar Surface')
    @ctx.command('edgesurfaceparam',mutates=False,label='Edge Surface')
    def edges(c):
        source=yield req.SelectReq('Select 2–4 single-edge boundary curves',kinds=('curve',),min_count=2,max_count=4)
        native_job(ctx,c,source,lambda shapes:[edge_surface_shape(shapes)],'Edge Surface')
    def surface_points(c, periodic):
        minimum = 4 if periodic else 2
        prompt = 'Select point rows without repeating the seam point' if periodic else 'Select native points row by row (U fastest)'
        source = yield req.SelectReq(prompt, kinds=('point',), min_count=2*minimum)
        u = yield req.NumberReq('U: points per row', default=minimum, minimum=minimum)
        def build(shapes):
            from serpentine3d.core import geometry as g
            points = [tuple(map(float, g.point_coords(shape))) for shape in shapes]
            return [make_surface_from_points(points, u, periodic_u=periodic)]
        native_job(ctx,c,source,build,'Surface from Points')

    @ctx.command('surfacefrompoints',mutates=False,label='Surface from Points')
    def points(c):
        yield from surface_points(c, False)

    @ctx.command('surfacefrompointsperiodic',mutates=False,label='Periodic Surface from Points')
    def periodic_points(c):
        yield from surface_points(c, True)
