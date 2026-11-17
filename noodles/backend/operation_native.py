"""Shared OCC operation factories for graph expressions and native commands."""
import math


def checked(shape):
    from serpentine3d.core import geometry as g
    from OCP.BRepCheck import BRepCheck_Analyzer
    if shape is None or shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError('OpenCascade returned invalid operation geometry.')
    kind=g.shape_kind(shape)
    if kind not in ('surface','solid','compound') or g.surface_area(shape)<=1e-12:
        raise ValueError('Operation produced degenerate or zero-area geometry.')
    if kind=='solid' and abs(g.volume(shape))<=1e-12:
        raise ValueError('Operation produced a zero-volume solid.')
    return shape


def extrude_shape(shape,vector,cap):
    from serpentine3d.core import geometry as g
    if g.shape_kind(shape) not in ('curve','surface'):
        raise ValueError('Extrude requires Curve or Surface geometry.')
    distance=math.hypot(*vector)
    if distance<=1e-9:
        raise ValueError('Extrude needs a nonzero Vector.')
    return checked(g.extrude(shape,vector,distance,cap=cap and g.shape_kind(shape)=='curve'))


def revolve_shape(shape,origin,direction,angle):
    from serpentine3d.core import geometry as g
    if g.shape_kind(shape)!='curve' or not 1e-9<abs(angle)<=360:
        raise ValueError('Revolve needs a Curve and 0 < abs(angle) <= 360 degrees.')
    return checked(g.revolve(shape,origin,direction,angle_deg=angle))


def loft_shape(shapes,closed=False,ruled=False,adjust=True):
    from serpentine3d.core import geometry as g
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.TopoDS import TopoDS
    if not (3 if closed else 2)<=len(shapes)<=240:
        raise ValueError('Loft needs 2..240 sections; Closed needs at least 3.')
    if any(g.shape_kind(s)!='curve' for s in shapes):
        raise ValueError('Loft sections must be Curves.')
    wires=[TopoDS.Wire_s(g.to_wire(s)) for s in shapes]
    builder=BRepOffsetAPI_ThruSections(False,ruled,1e-6)
    builder.CheckCompatibility(adjust)
    for wire in wires:
        builder.AddWire(wire)
    if closed:
        builder.AddWire(wires[0])
    builder.Build()
    if not builder.IsDone():
        raise ValueError('OpenCascade could not construct the Loft.')
    return checked(builder.Shape())


def project_shape(shape, frame, direction=None):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.Geom import Geom_Plane, Geom_TrimmedCurve
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.GeomProjLib import GeomProjLib
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED, TopAbs_WIRE
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from serpentine3d.core import geometry as g
    from .operations import project_point, projection_direction

    direction = projection_direction(frame, direction)
    shape = g.unwrap_compound(shape)
    if g.shape_kind(shape) == 'point':
        point = tuple(map(float, g.point_coords(shape)))
        return g.make_point(project_point(point, frame, direction))
    plane = Geom_Plane(gp_Pln(gp_Pnt(*frame.origin), gp_Dir(*frame.normal)))
    along = gp_Dir(*direction)

    def checked_curve(curve):
        if not BRepCheck_Analyzer(curve).IsValid():
            raise ValueError('Project produced an invalid curve.')
        return curve

    def projected_edge(edge):
        adaptor = BRepAdaptor_Curve(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        if adaptor.GetType() == GeomAbs_Line:
            start, end = (gp_Pnt(*project_point(g.pnt_tuple(adaptor.Value(t)), frame, direction))
                          for t in (first, last))
            if start.Distance(end) <= 1e-9:
                return None
            maker = BRepBuilderAPI_MakeEdge(start, end)
        else:
            basis = BRep_Tool.Curve_s(edge, first, last)
            trim = Geom_TrimmedCurve(basis, first, last, True, False)
            projected = GeomProjLib.ProjectOnPlane_s(trim, plane, along, True)
            if projected is None:
                raise ValueError('OpenCascade could not project this curve onto the plane.')
            maker = BRepBuilderAPI_MakeEdge(projected, first, last)
        if not maker.IsDone():
            raise ValueError('Project could not construct the projected edge.')
        result = maker.Edge()
        return TopoDS.Edge_s(result.Reversed()) if edge.Orientation() == TopAbs_REVERSED else result

    if shape.ShapeType() == TopAbs_EDGE:
        edge = projected_edge(TopoDS.Edge_s(shape))
        if edge is None:
            raise ValueError('The projected line collapses to a point.')
        return checked_curve(edge)
    if shape.ShapeType() != TopAbs_WIRE:
        raise ValueError('Project accepts points and single curves (edges or wires).')
    wire = TopoDS.Wire_s(shape)
    walker = BRepTools_WireExplorer(wire)
    result = BRepBuilderAPI_MakeWire()
    while walker.More():
        edge = projected_edge(walker.Current())
        if edge is not None:
            result.Add(edge)
            if not result.IsDone():
                raise ValueError('The projected wire is disconnected.')
        walker.Next()
    if not result.IsDone():
        raise ValueError('The projected wire collapses to a point.')
    projected = result.Wire()
    if BRep_Tool.IsClosed_s(wire) and not BRep_Tool.IsClosed_s(projected):
        raise ValueError('Project could not preserve the closed wire.')
    return checked_curve(projected)


def materialize(value,resolve,topology_cache=None):
    from .surface_native import planar_surface_shape,edge_surface_shape,make_surface_from_points,patch_shape
    from .booleans import PARAMETRIC_BOOLEANS
    if value.kind=='surface_from_points':
        return make_surface_from_points(value.points, value.u_count, periodic_u=value.periodic_u)
    if value.kind == 'isotrim':
        from .isotrim_native import isotrim_shape
        if not value.uv_view and topology_cache is not None:
            from .surface_structure import UV_PANELS
            cache_key = UV_PANELS, value.sources[0], value.face_index
            cached = topology_cache.get(cache_key, {}).get(value.uv_trim)
            if cached is not None:
                topology_cache.move_to_end(cache_key)
                return cached
        return isotrim_shape(resolve(value.sources[0]), value.uv_trim, value.face_index, value.uv_view)
    if value.kind == 'surface_isocurves':
        from .surface_modules_native import isocurve_edge
        key = value.kind, value.sources[0], value.face_index
        if topology_cache is not None:
            edge = topology_cache.get(key, {}).get(value.iso)
            if edge is not None:
                topology_cache.move_to_end(key)
                return edge
        return isocurve_edge(resolve(value.sources[0]), value.face_index, value.iso)
    if value.kind == 'box_morph':
        from .box_morph_native import box_morph_shape
        source, box, target = value.sources
        frame = box.axis if box.kind == 'bounding_box' else box.frame
        return box_morph_shape(resolve(source), resolve(box), frame, target.box_corners)
    shapes=[resolve(source) for source in value.sources]
    if value.kind == 'scale_non_uniform':
        from .surface_modules_native import nonuniform_scale
        return nonuniform_scale(shapes[0], value.axis, value.vector)
    if value.kind == 'cap_holes':
        from serpentine3d.core import geometry as g
        return checked(g.cap_holes(g.copy_shape(g.unwrap_compound(shapes[0]))))
    if value.kind == 'project':
        return project_shape(shapes[0], value.axis, value.vector)
    if value.kind == 'bounding_box':
        from .morph_native import box_shape
        return box_shape(shapes, value.axis)
    if value.kind == 'surface_morph':
        from .morph_native import morph_shape
        box = value.sources[1]
        frame = box.axis if box.kind == 'bounding_box' else box.frame
        return morph_shape(*shapes, frame, value.morph_domains)
    if value.kind == 'surface_box':
        from .box_morph_native import cage_shape
        return cage_shape(value.box_corners)
    from .placement import PLACEMENT_SPECS
    if value.kind in PLACEMENT_SPECS:
        from .placement_native import materialize as place
        return place(value, shapes[0])
    if value.kind == 'map_surface':
        from .map_surface_native import map_shape
        return map_shape(*shapes)
    if value.kind == 'fillet_parametric':
        from .fillet_curves import fillet_shape
        return fillet_shape(*shapes, value.radius, value.fillet_corner)
    if value.kind == 'fillet_edge':
        from .fillet_native import fillet_shape
        return fillet_shape(shapes[0], value.radius, value.fillet_points, value.fillet_selection)
    if value.kind == 'offset':
        from .offset_native import offset_geometry_shape
        return offset_geometry_shape(shapes[0], value.distance, fill=value.fill, solid=value.solid,
                                     normal=value.offset_normal)
    if value.kind in PARAMETRIC_BOOLEANS:
        from .boolean_native import boolean_shape
        return boolean_shape(PARAMETRIC_BOOLEANS[value.kind][0], shapes)
    if value.kind in ('sweep1','sweep2','birail_sweep'):
        from .sweep_native import sweep1_shape,sweep2_shape,birail_shape
        if value.kind=='sweep1':
            return sweep1_shape(shapes[1],shapes[0])
        rail1,rail2,profile=shapes
        return sweep2_shape(profile,rail1,rail2) if value.kind=='sweep2' else birail_shape(
            profile,rail1,rail2,value.rail_samples,value.profile_samples)
    if value.kind=='planar_surface':
        return planar_surface_shape(shapes)
    if value.kind=='edge_surface':
        return edge_surface_shape(shapes)
    if value.kind=='patch':
        return patch_shape(shapes)
    if value.kind == 'pipe':
        from serpentine3d.core.geometry import pipe
        return checked(pipe(shapes[0], value.radius, cap=value.cap))
    if value.kind=='extrude':
        return extrude_shape(shapes[0],value.vector,value.cap)
    if value.kind=='revolve':
        return revolve_shape(shapes[0],value.axis.origin,value.axis.normal,value.angle)
    return loft_shape(shapes,value.closed,value.ruled,value.adjust)


def native_job(ctx,c,sources,build,label,*,single_on_source_layer=False,mesh_result=False):
    """Native CLI uses the common OCC pool, with one native checkpoint/commit.

    These commands create ordinary independent CAD objects, without graph binding.
    The editor's nodes always use ParametricSceneAdapter and ParametricObject.
    """
    bridge=getattr(ctx.window,'_noodles_bridge',None)
    if bridge is None:
        c.echo('Load NoodleSBridge first.')
        return
    from PySide6.QtCore import QTimer
    scene=ctx.scene
    snapshots=tuple((obj.id,obj._shape) for obj in sources)
    def prepare():
        from .native_display import tessellate,geometry_bounds
        from serpentine3d.core import geometry as g
        parts=build([s for _,s in snapshots])
        if mesh_result:
            from .mesh_native import prepare_mesh
            return prepare_mesh(parts)
        shape=parts[0] if single_on_source_layer else g.make_compound(parts)
        bounds=geometry_bounds(parts)
        return shape,tessellate(shape,parts=parts,bounds=bounds),bounds
    future=bridge.geometry.pool.submit(prepare)
    timer=QTimer(ctx.window)
    timer.setInterval(20)
    def ready():
        if not future.done():
            return
        if getattr(getattr(ctx.window,'processor',None),'busy',False):
            return
        timer.stop()
        timer.deleteLater()
        try:
            shape,mesh,bounds=future.result()
            if ctx.scene is not scene or any(scene.get(id) is None or scene.get(id)._shape is not source for id,source in snapshots):
                raise ValueError('Source geometry/document changed during preparation; retry the command.')
            snapshot=scene.snapshot()
            ctx.window.history.checkpoint(label)
            try:
                with scene.batched():
                    layer = {'layer_id': scene.get(snapshots[0][0]).layer_id} if single_on_source_layer else {}
                    obj=scene.add(shape,name=label,**layer)
                    obj._mesh=mesh
                    obj._bounds=(shape,bounds)
            except Exception:
                scene.restore(snapshot)
                ctx.window.history.discard_checkpoint()
                raise
            c.echo('Created '+obj.name+'.')
        except Exception as exc:
            c.echo(label+': '+str(exc))
    timer.timeout.connect(ready)
    timer.start()
    c.echo('Preparing '+label+'…')


def register_commands(ctx):
    from .box_morph_native import register_commands as register_box_morph
    from .isotrim_native import register_commands as register_trim
    from .topology_native import register_commands as register_topology
    from .surface_modules_native import register_commands as register_modules
    from .morph_native import register_commands as register_morph
    from .surface_native import register_commands as register_surfaces
    register_surfaces(ctx)
    from .sweep_native import register_commands as register_sweeps
    register_sweeps(ctx)
    register_morph(ctx)
    register_box_morph(ctx)
    register_trim(ctx)
    register_topology(ctx)
    register_modules(ctx)
    req=ctx.requests()
    @ctx.command('projectplane', mutates=False, label='Project to Plane')
    def project(c):
        from .curves import PlaneValue

        sources = yield req.SelectReq('Select points or curves', kinds=('point', 'curve'))
        frame = PlaneValue(tuple(map(float, c.cplane.origin)), tuple(map(float, c.cplane.xdir)),
                           tuple(map(float, c.cplane.normal)))
        mode = yield req.OptionReq('Projection direction', options=['Normal', 'Along Vector'], default='Normal')
        direction = None
        if mode == 'Along Vector':
            start = yield req.PointReq('Vector start')
            end = yield req.PointReq('Vector end')
            direction = tuple(float(b-a) for a, b in zip(start, end))
        native_job(ctx, c, sources, lambda shapes: [project_shape(s, frame, direction) for s in shapes], 'Project')

    @ctx.command('extrudevector',aliases=('extrudev',),mutates=False,label='Extrude by Vector')
    def extrude(c):
        source=yield req.SelectReq('Select curves or surfaces',kinds=('curve','surface'))
        start=yield req.PointReq('Vector start',default=(0.,0.,0.))
        end=yield req.PointReq('Vector end',default=(start[0],start[1],start[2]+10.))
        cap=yield req.OptionReq('Cap closed planar profiles',options=['Yes','No'],default='Yes')
        vector=tuple(float(b-a) for a,b in zip(start,end))
        native_job(ctx,c,source,lambda shapes:[extrude_shape(s,vector,cap=='Yes') for s in shapes],'Extrude')
    @ctx.command('revolveparam',mutates=False,label='Revolve by Axis')
    def revolve(c):
        source=yield req.SelectReq('Select profile curves',kinds=('curve',))
        start=yield req.PointReq('Axis start',default=(0.,0.,0.))
        end=yield req.PointReq('Axis end',default=(start[0],start[1],start[2]+10.))
        angle=yield req.NumberReq('Angle (degrees)',default=360.)
        direction=tuple(float(b-a) for a,b in zip(start,end))
        native_job(ctx,c,source,lambda shapes:[revolve_shape(s,start,direction,angle) for s in shapes],'Revolve')
    @ctx.command('loftparam',mutates=False,label='Loft with Options')
    def loft(c):
        source=yield req.SelectReq('Select sections in order',kinds=('curve',),min_count=2)
        style=yield req.OptionReq('Loft type',options=['Smooth','Ruled'],default='Smooth')
        closed=yield req.OptionReq('Closed section cycle',options=['No','Yes'],default='No')
        adjust=yield req.OptionReq('Adjust compatibility',options=['Yes','No'],default='Yes')
        native_job(ctx,c,source,lambda shapes:[loft_shape(shapes,closed=='Yes',style=='Ruled',adjust=='Yes')],'Loft')
