"""Exact OCC intersection of a face's trims with an isoparametric rectangle."""


def isotrim_shape(shape, intervals, face_index=0, view=()):
    from serpentine3d.core import geometry as g
    from .surface_uv_native import _parameter, select_face, uv_bounds

    face = select_face(g.faces_of(shape), face_index)
    bounds = uv_bounds(face)
    exposed = view or bounds
    trim = tuple(_parameter(value, bounds[i:i+2], exposed[i:i+2], axis)[0]
                 for i, axis in ((0, 'U'), (2, 'V')) for value in intervals[i:i+2])
    return isotrim_face(face, trim, bounds)


def isotrim_face(face, trim, bounds, *, allow_empty=False):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    if trim == bounds:
        return g.copy_shape(face)
    if not (trim[0] < trim[1] and trim[2] < trim[3]):
        raise ValueError('Isotrim needs a nonzero region in the native UV domain.')
    region = BRepBuilderAPI_MakeFace(BRep_Tool.Surface_s(face), *trim, 1e-7)
    if not region.IsDone():
        raise ValueError('OpenCascade could not construct the Isotrim UV rectangle.')
    common = BRepAlgoAPI_Common()
    from OCP.TopTools import TopTools_ListOfShape
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(face)
    tools.Append(region.Face())
    common.SetArguments(arguments)
    common.SetTools(tools)
    common.SetNonDestructive(True)
    common.Build()
    if not common.IsDone():
        raise ValueError('OpenCascade could not intersect the source face with the UV rectangle.')
    shape = common.Shape()
    if shape.IsNull() and not allow_empty:
        raise ValueError('OpenCascade could not intersect the source face with the UV rectangle.')
    faces = () if shape.IsNull() else tuple(TopoDS.Face_s(part.Oriented(face.Orientation())) for part in g.faces_of(shape))
    if not faces:
        if allow_empty:
            return None
        raise ValueError('The Isotrim rectangle does not contain any part of the source face.')
    result = faces[0] if len(faces) == 1 else g.make_compound(faces)
    if not BRepCheck_Analyzer(result).IsValid() or g.surface_area(result) <= 1e-12:
        raise ValueError('OpenCascade returned an invalid Isotrim surface.')
    return result


def build_uv_panels(shape, face_index, u, v, wanted=lambda: True):
    from serpentine3d.core import geometry as g
    from .domain import DomainValue
    from .surface_uv import Domain2Value, uv_cells
    from .surface_uv_native import select_face, uv_bounds

    face = select_face(g.faces_of(shape), face_index)
    bounds = uv_bounds(face)
    domain = Domain2Value(DomainValue(*bounds[:2]), DomainValue(*bounds[2:]))
    for i, j, cell in uv_cells(domain, u, v):
        if not wanted():
            return
        intervals = cell.u.start, cell.u.end, cell.v.start, cell.v.end
        part = isotrim_face(face, intervals, bounds, allow_empty=True)
        if part is not None:
            yield i, j, intervals, part


def register_commands(ctx):
    from .isotrim import checked_intervals
    from .operation_native import native_job
    from .splines import integer
    from .topology_native import brep_join_shapes

    req = ctx.requests()

    @ctx.command('brepjoinparam', mutates=False, label='Brep Join')
    def brep_join(command):
        sources = yield req.SelectReq('Select Breps to join', kinds=('surface', 'solid', 'compound'),
                                      min_count=1, max_count=240)
        native_job(ctx, command, sources, brep_join_shapes, 'Brep Join')

    @ctx.command('isotrimparam', mutates=False, label='Isotrim')
    def isotrim(command):
        source = yield req.SelectReq('Select geometry containing the target face',
                                     kinds=('surface', 'solid', 'compound'), min_count=1, max_count=1)
        face = integer((yield req.NumberReq('Face index (0 = Auto)', default=0.)), 'Face Index', 0, 10000)
        bounds = []
        for axis in 'UV':
            bounds.append((yield req.NumberReq(f'Native {axis} start', default=0.)))
            bounds.append((yield req.NumberReq(f'Native {axis} end', default=1.)))
        intervals = checked_intervals(bounds)
        native_job(ctx, command, source, lambda shapes: [isotrim_shape(shapes[0], intervals, face)], 'Isotrim')

    @ctx.command('uvpanels', mutates=False, label='UV Panels')
    def uv_panels(command):
        from .surface_structure import MAX_PANELS, panel_count

        source = yield req.SelectReq('Select geometry containing the target face',
                                     kinds=('surface', 'solid', 'compound'), min_count=1, max_count=1)
        face = integer((yield req.NumberReq('Face index (0 = Auto)', default=0.)), 'Face Index', 0, 10000)
        u = integer((yield req.NumberReq('U Count', default=10., minimum=1)), 'U Count', 1, MAX_PANELS)
        v = integer((yield req.NumberReq('V Count', default=10., minimum=1)), 'V Count', 1, MAX_PANELS)
        panel_count(u, v)
        native_job(ctx, command, source, lambda shapes: [part for _, _, _, part in build_uv_panels(shapes[0], face, u, v)],
                   'UV Panels')
