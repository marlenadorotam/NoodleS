"""Shared OCC topology operations."""
from .booleans import BOOLEAN_SPLIT_PARAMETRIC
from .profile_operations import PROFILE_SPECS, SHATTER, profile_options
from .surface_modules import SURFACE_ISOCURVES


def section_shapes(shape, plane):
    from OCP.TopAbs import TopAbs_COMPOUND
    from serpentine3d.core import geometry as g

    if shape.ShapeType() == TopAbs_COMPOUND:
        return tuple(part for child in g.joined_pieces(shape) for part in section_shapes(child, plane))
    kind = g.shape_kind(shape)
    if kind not in ('surface', 'solid'):
        raise ValueError('Section needs a surface or solid BREP.')
    private = g.copy_shape(shape)
    regions = g.section_regions(private, plane.origin, plane.normal) if kind == 'solid' else []
    if regions:
        return (*region_outlines(regions), *regions)
    try:
        return tuple(g.section_curves(private, plane.origin, plane.normal))
    except g.GeometryError as exc:
        if str(exc) == 'The objects do not intersect':
            return ()
        raise


def region_outlines(faces):
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    for face in faces:
        wires = TopExp_Explorer(face, TopAbs_WIRE)
        while wires.More():
            yield TopoDS.Wire_s(wires.Current())
            wires.Next()


def curve_intersection_shapes(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX, TopAbs_WIRE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    if any(shape.ShapeType() not in (TopAbs_EDGE, TopAbs_WIRE) for shape in (a, b)):
        raise ValueError('Curve–Curve needs two OpenCascade edges or wires.')
    builder = BRepAlgoAPI_Section(a, b, False)
    builder.SetNonDestructive(True)
    builder.Build()
    if not builder.IsDone():
        raise ValueError('OpenCascade could not intersect the two curves.')
    result = builder.Shape()
    if result.IsNull():
        return ()
    edges = tuple(g.edges_of(result))
    vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(result, TopAbs_VERTEX, vertices)
    return (*edges, *(TopoDS.Vertex_s(vertices.FindKey(i)) for i in range(1, vertices.Extent()+1)))


def intersection_events(a, b, vertices, wanted):
    from OCP.BRep import BRep_Tool
    from .curve_sampling_native import closest_on_curve, curve_adaptor, projection_segments

    curves = []
    for shape in (a, b):
        adaptor, wire, _ = curve_adaptor(shape)
        curves.append((adaptor, projection_segments(adaptor, wire)))
    events = set()
    for vertex in vertices:
        xyz = BRep_Tool.Pnt_s(vertex).Coord()
        params = [closest_on_curve(adaptor, segments, xyz, False, wanted) for adaptor, segments in curves]
        if any(result is None for result in params):
            return []
        events.add((*xyz, params[0][3], params[1][3]))
    return sorted(events, key=lambda event: (event[3], event[4], event[:3]))


def region_boolean_shapes(shapes, mode, a_count):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    def operand_faces(shape):
        if g.shape_kind(shape) == 'curve':
            try:
                return [g.planar_face(g.copy_shape(shape))]
            except g.GeometryError as exc:
                raise ValueError('Region Boolean needs closed planar curves or planar faces.') from exc
        if g.shape_kind(shape) == 'surface':
            return g.faces_of(g.copy_shape(shape))
        raise ValueError('Region Boolean needs closed planar curves or planar faces.')

    operands = [operand_faces(shape) for shape in shapes]
    reference = None
    for faces in operands:
        if not faces:
            raise ValueError('Region Boolean needs closed planar curves or planar faces.')
        for face in faces:
            adaptor = BRepAdaptor_Surface(TopoDS.Face_s(face))
            if adaptor.GetType() != GeomAbs_Plane:
                raise ValueError('Region Boolean needs planar faces.')
            plane = adaptor.Plane()
            if reference is None:
                reference = plane
            if (not reference.Axis().Direction().IsParallel(plane.Axis().Direction(), 1e-9)
                    or reference.Distance(plane.Location()) > g.tol()):
                raise ValueError('Region Boolean operands must lie on the same plane.')

    def union(groups):
        faces = iter(face for group in groups for face in group)
        result = next(faces)
        for face in faces:
            result = g.boolean_union(result, face)
        return result

    if mode == 'Union':
        result = union(operands)
    elif mode == 'Difference' and a_count == len(operands):
        result = union(operands[:a_count])
    else:
        operation = g.boolean_difference if mode == 'Difference' else g.boolean_intersection
        result = operation(union(operands[:a_count]), union(operands[a_count:]))
    if not g.faces_of(result):
        return ()
    merge = ShapeUpgrade_UnifySameDomain(result, True, True, False)
    merge.SetSafeInputMode(True)
    merge.Build()
    merged = tuple(g.faces_of(merge.Shape()))
    if not merged or any(not BRepCheck_Analyzer(face).IsValid() for face in merged):
        raise ValueError('OpenCascade returned invalid Region Boolean geometry.')
    return merged


def join_shapes(shapes):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from serpentine3d.core import geometry as g

    kinds = {g.shape_kind(shape) for shape in shapes}
    # Join can change edge tolerances or sew shared faces. Work on private
    # shape copies because the graph resolver caches its source handles.
    sources = [g.copy_shape(shape) for shape in shapes]
    if kinds == {'curve'}:
        result = (g.join_curves([edge for source in sources for edge in g.edges_of(source)]),)
    elif kinds == {'surface'}:
        result = tuple(g.joined_pieces(g.join_surfaces(sources)))
        if len(result) >= len(sources):
            raise ValueError('Join found no shared edges between these surfaces.')
    else:
        raise ValueError('Join needs all curves or all surfaces in each branch.')
    if not result or any(piece.IsNull() or not BRepCheck_Analyzer(piece).IsValid() for piece in result):
        raise ValueError('OpenCascade returned invalid Join geometry.')
    return result


def explode_shape(shape):
    from serpentine3d.core import geometry as g
    return tuple(g.explode(shape))


def brep_join_shapes(shapes):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_Shell, BRepCheck_Status
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    opened, closed = [], []
    def collect(shape):
        if shape.ShapeType() == TopAbs_COMPOUND:
            for child in g.joined_pieces(shape):
                collect(child)
        elif g.shape_kind(shape) == 'solid':
            closed.append(shape)
        elif g.shape_kind(shape) == 'surface':
            opened.append(g.copy_shape(shape))
        else:
            raise ValueError('Brep Join accepts surfaces, shells and solids.')
    for shape in shapes:
        collect(shape)
    joined = []
    if opened:
        for piece in g.joined_pieces(g.join_surfaces(opened)):
            if piece.ShapeType() == TopAbs_SHELL:
                shell = TopoDS.Shell_s(piece)
                if BRepCheck_Shell(shell).Closed() == BRepCheck_Status.BRepCheck_NoError:
                    piece = BRepBuilderAPI_MakeSolid(shell).Solid()
            if g.shape_kind(piece) == 'solid':
                solid = TopoDS.Solid_s(piece)
                if not BRepLib.OrientClosedSolid_s(solid) or g.volume(solid) <= 1e-12:
                    raise ValueError('Brep Join could not orient a closed result.')
                piece = solid
            joined.append(piece)
    result = (*joined, *closed)
    if not result or any(not BRepCheck_Analyzer(piece).IsValid() for piece in result):
        raise ValueError('Brep Join returned invalid geometry.')
    return result


def split_shapes(shapes):
    from serpentine3d.core import geometry as g
    # Native Split can rebuild tolerances on its input shapes.
    copies = [g.copy_shape(shape) for shape in shapes]
    return tuple(g.split_shape(copies[0], copies[1:]))


def trim_pieces(pieces, remove_at):
    """Remove the exact OCC piece closest to the supplied point."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from serpentine3d.core import geometry as g
    from .curves import xyz

    point = g.make_point(xyz(remove_at))
    distances = []
    for index, piece in enumerate(pieces):
        nearest = BRepExtrema_DistShapeShape(point, piece)
        if not nearest.IsDone() or not nearest.NbSolution():
            raise ValueError('OpenCascade could not locate the Trim point.')
        distances.append((nearest.Value(), index))
    distances.sort()
    (best, remove), (next_best, _) = distances[:2]
    if next_best - best <= 1e-9:
        raise ValueError('Trim point is equally close to multiple pieces. Move it closer to the piece to remove.')
    return tuple(piece for index, piece in enumerate(pieces) if index != remove)


def pieces(operation, sources, resolve, cache=None, *, remove_at=None, plane=None, region=None, profile=None):
    key = (operation, sources, remove_at, plane, region, profile)
    if cache is not None and key in cache:
        cache.move_to_end(key)
        return cache[key]
    if operation == 'trim':
        result = trim_pieces(pieces('split', sources, resolve, cache), remove_at)
    else:
        shapes = tuple(resolve(source) for source in sources)
        if operation == 'join':
            result = join_shapes(shapes)
        elif operation == 'brep_join':
            result = brep_join_shapes(shapes)
        elif operation == 'split':
            result = split_shapes(shapes)
        elif operation == BOOLEAN_SPLIT_PARAMETRIC:
            from .boolean_native import split_solids
            result = split_solids(shapes, plane.normal)
        elif operation == 'section':
            result = section_shapes(shapes[0], plane)
        elif operation == 'curve_curve':
            result = curve_intersection_shapes(*shapes)
        elif operation == 'region_boolean':
            faces = region_boolean_shapes(shapes, *region)
            result = (*faces, *region_outlines(faces))
        elif operation in PROFILE_SPECS:
            from .profile_native import profile_geometry
            result = profile_geometry(operation, shapes, profile)
        elif operation == 'deconstruct_brep':
            from .surface_structure_native import brep_parts
            result, _ = brep_parts(shapes[0])
        else:
            result = explode_shape(shapes[0])
    if len(result) > 10000:
        raise ValueError('Topology operation exceeds the 10000-piece limit.')
    if cache is not None:
        cache[key] = result
        while len(cache) > 128 or sum(map(len, cache.values())) > 10000:
            cache.popitem(last=False)
    return result


def materialize_piece(value, resolve, cache):
    from serpentine3d.core import geometry as g
    if value.kind == SHATTER:
        from .profile_native import shatter_fragment
        return shatter_fragment(resolve(value.sources[0]), value.profile[1])
    parts = pieces(value.kind, value.sources, resolve, cache, remove_at=value.remove_at,
                   plane=value.axis if value.kind in ('section', BOOLEAN_SPLIT_PARAMETRIC) else None,
                   region=value.region, profile=value.profile)
    if value.piece_index >= len(parts) or g.shape_kind(parts[value.piece_index]) != value.result_kind:
        raise ValueError('Native topology changed. Recompute the graph.')
    return parts[value.piece_index]


def measure(plan, wanted, cache):
    from serpentine3d.core import geometry as g
    from .curves import PlaneValue, xyz
    from .datatree import MAX_ITEMS
    from .moves import geometry_from_wire
    from .scene_curves import materialize
    from .topology_operations import (CURVE_CURVE, PIECE_KINDS, REGION_BOOLEAN, SECTION,
                                      TOPOLOGY_OPERATIONS, TOPOLOGY_SOURCE_LIMITS, region_parameters)

    operation, rows = plan.get('operation'), plan.get('rows')
    from .mesh_nodes import BREP_TO_MESH
    if operation == BREP_TO_MESH:
        from .mesh_native import measure_brep_mesh
        return measure_brep_mesh(plan, wanted, cache)
    if operation == SURFACE_ISOCURVES:
        from .surface_modules_native import measure_isocurves
        return measure_isocurves(plan, wanted, cache)
    if (operation not in TOPOLOGY_OPERATIONS or operation not in TOPOLOGY_SOURCE_LIMITS
            or not isinstance(rows, list) or len(rows) > MAX_ITEMS):
        raise ValueError('Invalid topology operation request.')
    minimum, maximum = TOPOLOGY_SOURCE_LIMITS[operation]
    shapes, results, budget = {}, [], [MAX_ITEMS]

    def resolve(value):
        if value not in shapes:
            shapes[value] = materialize(value, resolve=resolve, topology_cache=cache)
        return shapes[value]

    total = 0
    shared = ()
    if operation in (SECTION, CURVE_CURVE, REGION_BOOLEAN, *PROFILE_SPECS):
        sources = plan.get('sources')
        if not isinstance(sources, list) or len(sources) > MAX_ITEMS:
            raise ValueError('Invalid topology source list.')
        shared = tuple(geometry_from_wire(source, budget=budget) for source in sources)
    for row in rows:
        if not wanted():
            return []
        remove_at = None
        plane = None
        region = None
        profile = None
        if operation == SECTION:
            if (not isinstance(row, list) or len(row) != 2 or type(row[0]) is not int
                    or not 0 <= row[0] < len(shared) or not isinstance(row[1], dict)):
                raise ValueError('Invalid Section source or plane.')
            sources, plane = (shared[row[0]],), PlaneValue(**row[1])
        elif operation in (CURVE_CURVE, REGION_BOOLEAN, *PROFILE_SPECS):
            indices = row.get('indices') if isinstance(row, dict) else row
            if (not isinstance(indices, list) or not minimum <= len(indices) <= maximum
                    or any(type(i) is not int or not 0 <= i < len(shared) for i in indices)):
                raise ValueError('Invalid intersection source list.')
            sources = tuple(shared[i] for i in indices)
            if operation == REGION_BOOLEAN:
                options = row.get('region') if isinstance(row, dict) else None
                if not isinstance(options, (list, tuple)) or len(options) != 2:
                    raise ValueError('Invalid Region Boolean options.')
                region = region_parameters(*options, len(sources))
            elif operation in PROFILE_SPECS:
                from .curves import is_curve_recipe
                if not isinstance(row, dict) or not all(map(is_curve_recipe, sources)):
                    raise ValueError('Invalid curve profile sources.')
                profile = profile_options(operation, row.get('profile'))
        else:
            if operation == 'trim':
                if not isinstance(row, dict):
                    raise ValueError('Trim needs sources and a Remove At point.')
                remove_at = xyz(row.get('remove_at'))
                row = row.get('sources')
            elif operation == BOOLEAN_SPLIT_PARAMETRIC:
                if not isinstance(row, dict) or not isinstance(row.get('plane'), dict):
                    raise ValueError('Boolean Split needs a cutting plane.')
                plane = PlaneValue(**row['plane'])
                row = row.get('sources')
            if not isinstance(row, list) or not minimum <= len(row) <= maximum:
                raise ValueError('Invalid topology operation source count.')
            sources = tuple(geometry_from_wire(data, budget=budget) for data in row)
        result = pieces(operation, sources, resolve, cache, remove_at=remove_at, plane=plane,
                        region=region, profile=profile)
        kinds = [g.shape_kind(part) for part in result]
        total += len(kinds)
        if operation == CURVE_CURVE:
            first_point = kinds.index('point') if 'point' in kinds else len(kinds)
            vertices = result[first_point:]
            events = intersection_events(*map(resolve, sources), vertices, wanted) if vertices else []
            results.append({'kinds': kinds[:first_point], 'events': events})
            kinds = kinds[:first_point]
        elif operation in PROFILE_SPECS:
            from .profile_native import profile_metadata
            results.append({'kinds': kinds, 'meta': profile_metadata(operation, tuple(map(resolve, sources)), profile)})
        else:
            results.append(kinds)
        if any(kind not in PIECE_KINDS for kind in kinds):
            raise ValueError('Topology operation returned an unsupported geometry kind.')
        if total > MAX_ITEMS:
            raise ValueError('Topology operation exceeds the 10000-piece limit.')
    return results


def register_commands(ctx):
    from .operation_native import native_job
    from .profile_native import profile_geometry
    from .profile_operations import MOVE_SEAM, SHATTER
    from .topology_operations import REGION_MODES

    req = ctx.requests()

    @ctx.command('shatterparam', mutates=False, label='Shatter')
    def shatter(command):
        source = yield req.SelectReq('Select a curve', kinds=('curve',), min_count=1, max_count=1)
        mode = yield req.OptionReq('Parameter space', options=['Normalized', 'Native'], default='Normalized')
        values = yield req.TextReq('Split parameters separated by spaces', default='0.5')
        try:
            options = profile_options(SHATTER, (mode == 'Normalized', tuple(map(float, values.split()))))
        except ValueError as exc:
            command.echo(str(exc))
            return
        native_job(ctx, command, source, lambda shapes: profile_geometry(SHATTER, shapes, options), 'Shatter')

    @ctx.command('moveseamparam', mutates=False, label='Move Seam')
    def move_seam(command):
        source = yield req.SelectReq('Select a closed curve', kinds=('curve',), min_count=1, max_count=1)
        mode = yield req.OptionReq('Parameter space', options=['Normalized', 'Native'], default='Normalized')
        parameter = yield req.NumberReq('New seam parameter', default=.5)
        options = profile_options(MOVE_SEAM, (mode == 'Normalized', (parameter,)))
        native_job(ctx, command, source, lambda shapes: profile_geometry(MOVE_SEAM, shapes, options), 'Move Seam')

    @ctx.command('curvecurve', mutates=False, label='Curve–Curve')
    def curve_curve(command):
        curves = []
        for label in ('A', 'B'):
            selection = yield req.SelectReq('Select curve ' + label, kinds=('curve',), min_count=1, max_count=1)
            curves.extend(selection)

        def build(shapes):
            parts = curve_intersection_shapes(*shapes)
            if not parts:
                raise ValueError('The curves do not intersect.')
            return parts

        native_job(ctx, command, curves, build, 'Curve–Curve')

    @ctx.command('regionboolean', mutates=False, label='Region Boolean')
    def region_boolean(command):
        mode = yield req.OptionReq('Region operation', options=list(REGION_MODES), default='Union')
        kinds = ('curve', 'surface')
        left = yield req.SelectReq('Select regions or closed curves A', kinds=kinds, min_count=1, max_count=240)
        right = ()
        if mode != 'Union':
            right = yield req.SelectReq('Select regions or closed curves B', kinds=kinds, min_count=1, max_count=239)
        if len(left)+len(right) > 240:
            raise ValueError('Region Boolean accepts at most 240 operands.')

        def build(shapes):
            faces = region_boolean_shapes(shapes, mode, len(left))
            if not faces:
                raise ValueError('The operation produced no regions.')
            return faces

        native_job(ctx, command, (*left, *right), build, 'Region Boolean')
