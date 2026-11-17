"""Materialize indexed meshes on the shared native worker."""
import math

from .curves import PlaneValue
from .delaunay_node import DELAUNAY, SITE_LIMITS
from .mesh_nodes import (MESH, MAX_MESH_ELEMENTS, MeshValue, brep_mesh_settings,
                         construct_mesh, delaunay_mesh, mesh_from_wire)
from .mesh_topology import join_meshes, weld_mesh, weld_settings


def materialize(mesh):
    from serpentine3d.core.mesh import MeshShape

    return MeshShape(mesh.vertices, mesh.triangles, mesh.normals or None)


def prepare_mesh(parts):
    from serpentine3d.core.mesh import merge, mesh_to_display

    parts = tuple(parts)
    shape = parts[0] if len(parts) == 1 else merge(parts)
    display = mesh_to_display(shape)
    display.segment_index()
    return shape, display, shape.bbox()


def brep_to_mesh(shape, settings, wanted=lambda: True):
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    from serpentine3d.core import geometry as g

    deflection, angle, relative = brep_mesh_settings(*settings)
    if g.shape_kind(shape) not in ('surface', 'solid', 'compound') or not g.faces_of(shape):
        raise ValueError('Brep to Mesh requires a BREP with faces.')
    span = math.dist(*g.bbox(shape))
    if relative:
        deflection *= span
    if deflection < max(g.tol(), span*1e-8):
        raise ValueError('Linear Deflection is below the safe minimum for this BREP.')
    # A private copy gives deterministic density independent of the viewport
    # and prevents overwriting triangulations on the original object.
    copy = g.copy_shape(shape)
    BRepTools.Clean_s(copy)
    mesher = BRepMesh_IncrementalMesh(copy, deflection, False, math.radians(angle), True)
    if not mesher.IsDone():
        raise ValueError('OpenCascade could not mesh the BREP.')
    vertices, triangles, index = [], [], {}
    for face in g.faces_of(copy):
        if not wanted():
            return None
        location = TopLoc_Location()
        data = BRep_Tool.Triangulation_s(face, location)
        if data is None or not data.NbTriangles():
            raise ValueError('OpenCascade did not triangulate every BREP face.')
        if len(triangles) + data.NbTriangles() > MAX_MESH_ELEMENTS:
            raise ValueError('Brep to Mesh exceeds 10,000 triangles. Increase deflection.')
        transform = location.Transformation()
        remap = {}
        for row in range(1, data.NbTriangles()+1):
            triangle = []
            for node in data.Triangle(row).Get():
                if node not in remap:
                    point = data.Node(node).Transformed(transform).Coord()
                    if point not in index:
                        if len(vertices) >= MAX_MESH_ELEMENTS:
                            raise ValueError('Brep to Mesh exceeds 10,000 vertices. Increase deflection.')
                        index[point] = len(vertices)
                        vertices.append(point)
                    remap[node] = index[point]
                triangle.append(remap[node])
            a, b, c = triangle
            if len({a, b, c}) == 3:
                triangles.append((a, c, b) if face.Orientation() == TopAbs_REVERSED else (a, b, c))
    if not triangles:
        raise ValueError('OpenCascade returned no usable mesh triangles.')
    return MeshValue('mesh', tuple(vertices), tuple(triangles))


def measure_brep_mesh(plan, wanted, topology_cache):
    from .booleans import is_boolean_operand
    from .moves import geometry_from_wire
    from .scene_curves import materialize as materialize_brep

    sources, rows = plan.get('sources'), plan.get('rows')
    if not isinstance(rows, list) or not isinstance(sources, list) or not 1 <= len(sources) <= len(rows) <= 240:
        raise ValueError('Invalid Brep to Mesh request.')
    budget = [MAX_MESH_ELEMENTS]
    sources = tuple(geometry_from_wire(data, budget=budget) for data in sources)
    if not all(is_boolean_operand(source, solid_only=False) for source in sources):
        raise ValueError('Brep to Mesh requires native BREP sources.')
    shapes, converted, results = {}, {}, []
    vertices = triangles = 0

    def resolve(value):
        if value not in shapes:
            shapes[value] = materialize_brep(value, resolve=resolve, topology_cache=topology_cache)
        return shapes[value]

    for row in rows:
        if not wanted():
            return []
        if not isinstance(row, list) or len(row) != 4 or type(row[0]) is not int or not 0 <= row[0] < len(sources):
            raise ValueError('Invalid Brep to Mesh source index.')
        index, *settings = row
        settings = brep_mesh_settings(*settings)
        key = index, settings
        if key not in converted:
            result = brep_to_mesh(resolve(sources[index]), settings, wanted)
            if result is None:
                return []
            converted[key] = result, result.to_wire()
        mesh, wire = converted[key]
        vertices += len(mesh.vertices)
        triangles += len(mesh.triangles)
        if max(vertices, triangles) > MAX_MESH_ELEMENTS:
            raise ValueError('Brep to Mesh exceeds 10,000 vertices or triangles. Increase deflection.')
        results.append(wire)
    return results


def native_mesh_value(shape, key):
    from serpentine3d.core.mesh import MeshShape

    if not isinstance(shape, MeshShape):
        raise ValueError('Select native Mesh objects.')
    if max(len(shape.vertices), len(shape.triangles)) > MAX_MESH_ELEMENTS:
        raise ValueError('The mesh exceeds the 10,000-vertex or triangle limit.')
    normals = () if shape.normals is None else shape.normals.tolist()
    return mesh_from_wire({'kind': MESH, 'key': key, 'vertices': shape.vertices.tolist(),
                           'triangles': shape.triangles.tolist(), 'normals': normals})


def register_commands(ctx):
    from .operation_native import native_job

    req = ctx.requests()

    def points(shapes):
        from serpentine3d.core.geometry import point_coords
        return tuple(tuple(map(float, point_coords(shape))) for shape in shapes)

    @ctx.command('delaunaymesh', mutates=False, label='Delaunay Mesh')
    def triangulate(c):
        source = yield req.SelectReq('Select points to triangulate on the construction plane', kinds=('point',),
                                     min_count=3, max_count=SITE_LIMITS[DELAUNAY])
        frame = PlaneValue(tuple(map(float, c.cplane.origin)), tuple(map(float, c.cplane.xdir)),
                           tuple(map(float, c.cplane.normal)))
        native_job(ctx, c, source, lambda shapes: [materialize(delaunay_mesh('mesh', points(shapes), frame))],
                   'Delaunay Mesh', mesh_result=True)

    @ctx.command('constructmesh', mutates=False, label='Construct Mesh')
    def construct(c):
        source = yield req.SelectReq('Select vertices in index order', kinds=('point',),
                                     min_count=3, max_count=MAX_MESH_ELEMENTS)
        raw = yield req.TextReq('Faces as zero-based indices, separated by semicolons', default='0 1 2')

        def build(shapes):
            faces = [tuple(map(int, face.replace(',', ' ').split())) for face in raw.split(';')]
            return [materialize(construct_mesh('mesh', points(shapes), faces))]

        native_job(ctx, c, source, build, 'Construct Mesh', mesh_result=True)

    @ctx.command('breptomeshquality', mutates=False, label='Brep to Mesh')
    def convert(c):
        sources = yield req.SelectReq('Select surfaces or solids', kinds=('surface', 'solid', 'compound'),
                                      min_count=1, max_count=240)
        mode = yield req.OptionReq('Linear deflection mode', options=['Relative', 'Absolute'], default='Relative')
        deflection = yield req.NumberReq('Linear deflection', default=.005 if mode == 'Relative' else .1)
        angle = yield req.NumberReq('Angular deflection (degrees)', default=20.)
        settings = deflection, angle, mode == 'Relative'

        def build(shapes):
            meshes = tuple(brep_to_mesh(shape, settings) for shape in shapes)
            return (materialize(join_meshes('converted', meshes)),)

        native_job(ctx, c, sources, build, 'Brep to Mesh', mesh_result=True)

    @ctx.command('meshjoin', mutates=False, label='Mesh Join')
    def join(c):
        sources = yield req.SelectReq('Select meshes to join', kinds=('mesh',), min_count=2, max_count=240)

        def build(shapes):
            meshes = tuple(native_mesh_value(shape, str(i)) for i, shape in enumerate(shapes))
            return (materialize(join_meshes('joined', meshes)),)

        native_job(ctx, c, sources, build, 'Mesh Join', mesh_result=True)

    @ctx.command('weldmesh', mutates=False, label='Weld Mesh')
    def weld(c):
        sources = yield req.SelectReq('Select meshes to weld', kinds=('mesh',), min_count=1, max_count=240)
        tolerance = yield req.NumberReq('Weld tolerance', default=.001)
        angle = yield req.NumberReq('Maximum normal angle (degrees)', default=30.)

        def build(shapes):
            settings = weld_settings(tolerance, angle)
            return tuple(materialize(weld_mesh(str(i), native_mesh_value(shape, str(i)), *settings))
                         for i, shape in enumerate(shapes))

        native_job(ctx, c, sources, build, 'Weld Mesh', mesh_result=True)
