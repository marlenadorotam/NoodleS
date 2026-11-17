"""Indexed native mesh references and topology, independent of Qt and OCC."""
from collections import Counter
from dataclasses import dataclass
import hashlib
import math

from .arithmetic import VectorValue, finite_number
from .curves import CurveInput, CurveValue, PlaneValue, add, cross, dot, input_tree, line, normalize_curve_state, polyline, scale, sub, xyz
from .datatree import Branch, DataTree, MAX_ITEMS, aligned, topology
from .delaunay import periodic_mesh_u, site_frame, triangulate
from .delaunay_node import DELAUNAY, SITE_LIMITS, match_branches
from .parametric import ParametricObject
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry
from .surface_uv import _match
from .mesh_topology import face_neighbours, join_meshes, weld_mesh


MESH = 'mesh'
MESH_EDGES = 'mesh_edges'
DECONSTRUCT_MESH = 'deconstruct_mesh'
FACE_BOUNDARIES = 'face_boundaries'
DECONSTRUCT_FACE = 'deconstruct_face'
TRIANGLE_FACE = 'triangle_face'
FACE_NORMALS = 'face_normals'
DELAUNAY_MESH = 'delaunay_mesh'
CONSTRUCT_MESH = 'construct_mesh'
BREP_TO_MESH = 'brep_to_mesh'
MESH_JOIN = 'mesh_join'
WELD_MESH = 'weld_mesh'
FACE_NEIGHBOURS = 'face_neighbours'
MESH_PUBLISHERS = (CONSTRUCT_MESH, BREP_TO_MESH, MESH_JOIN, WELD_MESH)
MESH_MODEL = 'meshes'
MAX_MESH_ELEMENTS = MAX_ITEMS
MESH_SPECS = {
    MESH: {'class': 'MeshNode', 'name': 'Mesh', 'reference': True, 'reference_only': True,
           'inputs': (), 'outputs': ('M',), 'primary': 'M'},
    MESH_EDGES: {'class': 'MeshEdgesNode', 'name': 'Mesh Edges', 'reference': False, 'category': 'Operations',
                 'inputs': (CurveInput('M', 'Mesh', 'items'),), 'outputs': ('E1', 'E2', 'E3')},
    DECONSTRUCT_MESH: {'class': 'DeconstructMeshNode', 'name': 'Deconstruct Mesh', 'reference': False,
                       'category': 'Operations', 'inputs': (CurveInput('M', 'Mesh', 'items'),),
                       'outputs': ('V', 'F', 'C', 'N')},
    FACE_BOUNDARIES: {'class': 'FaceBoundariesNode', 'name': 'Face Boundaries', 'reference': False,
                      'category': 'Operations', 'inputs': (CurveInput('M', 'Mesh', 'items'),), 'outputs': ('B',)},
    DECONSTRUCT_FACE: {'class': 'DeconstructFaceNode', 'name': 'Deconstruct Face', 'reference': False,
                       'category': 'Operations', 'inputs': (CurveInput('F', 'Mesh Faces', 'items'),),
                       'outputs': ('A', 'B', 'C', 'D')},
    TRIANGLE_FACE: {'class': 'TriangleFaceNode', 'name': 'Triangle Face', 'reference': False,
                    'category': 'Operations',
                    'inputs': tuple(CurveInput(port, f'Vertex Index {port}', 'list_index', index)
                                    for index, port in enumerate('ABC')), 'outputs': ('F',)},
    FACE_NORMALS: {'class': 'FaceNormalsNode', 'name': 'Face Normals', 'reference': False,
                   'category': 'Operations', 'inputs': (CurveInput('M', 'Mesh', 'items'),),
                   'outputs': ('C', 'N')},
    DELAUNAY_MESH: {'class': 'DelaunayMeshNode', 'name': 'Delaunay Mesh', 'reference': False,
                    'category': 'Operations', 'inputs': (CurveInput('P', 'Points', 'points'),
                                                        CurveInput('Pl', 'Plane', 'plane', optional=True),
                                                        CurveInput('B', 'UV Rectangle Boundary', 'geometry', optional=True)),
                    'outputs': ('M', 'U', 'V')},
    CONSTRUCT_MESH: {'class': 'ConstructMeshNode', 'name': 'Construct Mesh', 'reference': False,
                     'category': 'Operations', 'primary': 'M',
                     'inputs': (CurveInput('V', 'Vertices', 'points'), CurveInput('F', 'Faces', 'items'),
                                CurveInput('C', 'Vertex Colors', 'items', optional=True)), 'outputs': ('M',)},
    BREP_TO_MESH: {'class': 'BrepToMeshNode', 'name': 'Brep to Mesh', 'reference': False,
                   'category': 'Operations', 'primary': 'M', 'inputs': (
                       CurveInput('B', 'Surfaces or Solids', 'native_boolean_operand'),
                       CurveInput('D', 'Linear Deflection', 'number', .005),
                       CurveInput('A', 'Angular Deflection (Degrees)', 'number', 20.),
                       CurveInput('R', 'Relative to Object Size', 'boolean', True)), 'outputs': ('M',)},
    MESH_JOIN: {'class': 'MeshJoinNode', 'name': 'Mesh Join', 'reference': False,
                'category': 'Operations', 'primary': 'M', 'inputs': (
                    CurveInput('M', 'Meshes', 'items'),), 'outputs': ('M',)},
    WELD_MESH: {'class': 'WeldMeshNode', 'name': 'Weld Mesh', 'reference': False,
                'category': 'Operations', 'primary': 'M', 'inputs': (
                    CurveInput('M', 'Mesh', 'items'), CurveInput('T', 'Weld Tolerance', 'number', .001),
                    CurveInput('A', 'Maximum Normal Angle (Degrees)', 'number', 30.)), 'outputs': ('M',)},
    FACE_NEIGHBOURS: {'class': 'FaceNeighboursNode', 'name': 'Face Neighbours', 'reference': False,
                      'category': 'Operations', 'primary': 'N', 'inputs': (
                          CurveInput('M', 'Mesh', 'items'),), 'outputs': ('N', 'B', 'X')},
}


@dataclass(frozen=True)
class MeshValue:
    key: str
    vertices: tuple
    triangles: tuple
    normals: tuple = ()
    kind = MESH

    def __str__(self):
        return f'Mesh · {len(self.vertices):,} vertices · {len(self.triangles):,} triangles'

    def to_wire(self):
        data = {'key': self.key, 'kind': self.kind, 'vertices': [list(p) for p in self.vertices],
                'triangles': [list(t) for t in self.triangles]}
        if self.normals:
            data['normals'] = [list(normal) for normal in self.normals]
        return data


def mesh_from_wire(data):
    key, vertices, triangles = (data.get(field) for field in ('key', 'vertices', 'triangles'))
    if (data.get('kind') != MESH or not isinstance(key, str) or not 0 < len(key) <= 256
            or not isinstance(vertices, (list, tuple)) or not isinstance(triangles, (list, tuple))
            or not 0 < len(vertices) <= MAX_MESH_ELEMENTS or not 0 < len(triangles) <= MAX_MESH_ELEMENTS):
        raise ValueError('Invalid mesh or mesh exceeds the vertex or triangle limit.')
    points = tuple(xyz(p) for p in vertices)
    faces = []
    for face in triangles:
        if (not isinstance(face, (list, tuple)) or len(face) != 3
                or any(type(i) is not int or not 0 <= i < len(points) for i in face)):
            raise ValueError('Invalid mesh triangle indices.')
        faces.append(tuple(face))
    normals = data.get('normals', ())
    if not isinstance(normals, (list, tuple)) or len(normals) not in (0, len(points)):
        raise ValueError('Expected one mesh normal per vertex.')
    return MeshValue(key, points, tuple(faces), tuple(xyz(normal) for normal in normals))


def normalize_state(operation, data):
    if operation == MESH:
        data = {**data, 'mode': 'reference'}
        return normalize_curve_state(operation, data, spec=MESH_SPECS[operation], decoder=mesh_from_wire)
    state = normalize_curve_state(operation, data, spec=MESH_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Mesh operations use connected data.')
    if operation == DELAUNAY_MESH:
        periodic = data.get('parameters', {}).get('periodic_u', False)
        if type(periodic) is not bool:
            raise ValueError('Periodic U must be Boolean.')
        state['parameters']['periodic_u'] = periodic
    return state


def construct_mesh(key, vertices, faces):
    triangles = []
    for face in faces:
        if (not isinstance(face, (tuple, list)) or len(face) not in (3, 4)
                or any(type(i) is not int or not 0 <= i < len(vertices) for i in face)
                or len(set(face)) != len(face)):
            raise ValueError('Faces need three or four distinct zero-based vertex indices.')
        a, b, c, *d = face
        triangles.append((a, b, c))
        if d:
            triangles.append((a, c, d[0]))
    if not triangles or len(triangles) > MAX_MESH_ELEMENTS:
        raise ValueError(f'Construct Mesh needs 1–{MAX_MESH_ELEMENTS:,} triangles per mesh.')
    return MeshValue(key, tuple(vertices), tuple(triangles))


def delaunay_mesh(key, vertices, frame=None):
    if not 3 <= len(vertices) <= SITE_LIMITS[DELAUNAY]:
        raise ValueError(f'Delaunay Mesh needs 3–{SITE_LIMITS[DELAUNAY]:,} points.')
    if frame is None:
        frame = site_frame(vertices)
        if max(frame.normal, key=abs) < 0:
            frame = PlaneValue(frame.origin, frame.axis_x, scale(frame.normal, -1))
    xaxis, yaxis = frame.axis_x, frame.axis_y
    offsets = (sub(point, frame.origin) for point in vertices)
    uv = [(dot(delta, xaxis), dot(delta, yaxis)) for delta in offsets]
    u0, v0 = map(min, zip(*uv))
    span = max(max(u for u, _ in uv) - u0, max(v for _, v in uv) - v0)
    if span <= 1e-9:
        raise ValueError('Delaunay Mesh has no usable projected extent.')
    projected = [((u - u0) / span, (v - v0) / span) for u, v in uv]
    if len({(round(u, 11), round(v, 11)) for u, v in projected}) != len(vertices):
        raise ValueError('Delaunay Mesh has duplicate or coincident projected points.')
    return MeshValue(key, tuple(vertices), tuple(triangulate(projected, lambda: None)))


def _periodic_mesh(key, points, boundary):
    if not isinstance(boundary, CurveValue) or boundary.kind != 'rectangle':
        raise ValueError('Periodic U needs a Rectangle at B.')
    if len(points) < 3:
        raise ValueError('Delaunay Mesh needs at least three points per nonempty branch.')
    width, height = boundary.dimensions
    span = max(width, height)
    frame, origin = boundary.frame, boundary.points[0]
    offsets = tuple(sub(point, origin) for point in points)
    if any(abs(dot(delta, frame.normal)) > max(1e-7, span*1e-8) for delta in offsets):
        raise ValueError('Periodic U points must lie in the plane of the Rectangle.')
    sites = [(dot(delta, frame.axis_x)/span, dot(delta, frame.axis_y)/span) for delta in offsets]
    width_uv, height_uv = width/span, height/span
    vertices, faces = periodic_mesh_u(sites, width_uv, height_uv, lambda: None)
    world = tuple(add(origin, add(scale(frame.axis_x, u*span), scale(frame.axis_y, v*span)))
                  for u, v in vertices)
    return MeshValue(key, world, tuple(faces)), tuple((u/width_uv, v/height_uv) for u, v in vertices)


def _build_meshes(operation, state, inputs):
    delaunay = operation == DELAUNAY_MESH
    periodic = delaunay and state['parameters']['periodic_u']
    specs = MESH_SPECS[operation]['inputs']
    unused = 'Pl' if periodic else 'B'
    trees = {d.port: input_tree(inputs[d.port], d, state['tree_modes'].get(d.port, 'none'))
             for d in specs if d.port in inputs and d.port != unused}
    if delaunay:
        vertices = trees['P']
        if vertices.count > SITE_LIMITS[DELAUNAY]:
            raise ValueError(f'Delaunay Mesh supports up to {SITE_LIMITS[DELAUNAY]:,} points in total.')
        paths = [b.path for b in vertices.branches if b.items]
        port, label = ('B', 'Boundary') if periodic else ('Pl', 'Plane')
        frames = match_branches(trees.get(port), paths, label) if paths else {}
    else:
        if 'C' in trees and trees['C'].count:
            raise ValueError('Serpentine meshes do not support vertex colors.')
        vertices, faces = trees['V'], trees['F']
        face_items = {b.path: b.items for b in faces.branches if b.items}
        if {b.path for b in vertices.branches if b.items} != set(face_items):
            raise ValueError('Vertices and Faces need matching nonempty branch paths.')
    outputs = {port: [] for port in MESH_SPECS[operation]['outputs']}
    total_faces = 0
    for branch in vertices.branches:
        values = ()
        uv = ()
        if branch.items:
            key = hashlib.sha256(repr(branch.path).encode()).hexdigest()[:24]
            points = tuple(point.xyz for point in branch.items)
            if periodic:
                mesh, uv = _periodic_mesh(key, points, frames[branch.path])
            elif delaunay:
                mesh = delaunay_mesh(key, points, frames[branch.path])
            else:
                mesh = construct_mesh(key, points, face_items[branch.path])
            total_faces += len(mesh.triangles)
            if total_faces > MAX_MESH_ELEMENTS:
                raise ValueError(f'Mesh output supports up to {MAX_MESH_ELEMENTS:,} triangles in total.')
            values = (mesh,)
        outputs['M'].append(Branch(branch.path, values, tuple(v.key for v in values)))
        if delaunay:
            for index, port in enumerate('UV'):
                outputs[port].append(Branch(branch.path, tuple(pair[index] for pair in uv)))
    return {port: DataTree(tuple(branches)) for port, branches in outputs.items()}


def object_from_outputs(parameters, outputs):
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['M'], kind=MESH_MODEL)


def object_from_wire(data):
    from .curves import curve_object_from_wire

    def decode(raw):
        if not isinstance(raw, dict):
            raise ValueError('Invalid mesh record.')
        return mesh_from_wire(raw)

    model = curve_object_from_wire(data, decoder=decode, kind=MESH_MODEL)
    if any(sum(len(getattr(mesh, field)) for mesh in model.parts.values()) > MAX_MESH_ELEMENTS
           for field in ('vertices', 'triangles')):
        raise ValueError('Mesh ParametricObject exceeds the vertex or triangle budget.')
    return model


def _edge_counts(mesh):
    # Native imports may duplicate vertex indices at normals or material seams.
    indices = {}
    welded = tuple(indices.setdefault(point, i) for i, point in enumerate(mesh.vertices))
    edges = Counter()
    for triangle in mesh.triangles:
        a, b, c = (welded[i] for i in triangle)
        if len({a, b, c}) == 3:
            edges.update(tuple(sorted(pair)) for pair in ((a, b), (b, c), (c, a)))
    return edges


def _vertex_normals(mesh):
    if mesh.normals:
        return mesh.normals
    # The unnormalized cross product weights each contribution by triangle area.
    normals = [(0., 0., 0.)] * len(mesh.vertices)
    for triangle in mesh.triangles:
        a, b, c = (mesh.vertices[i] for i in triangle)
        normal = cross(sub(b, a), sub(c, a))
        for index in triangle:
            normals[index] = add(normals[index], normal)
    result = []
    for normal in normals:
        length = math.hypot(*normal)
        result.append(tuple(component / length for component in normal) if length else normal)
    return result


def _mesh_branches(tree, name):
    """Assign one branch per mesh, in the same order for every face operation."""
    split = any(len(branch.items) > 1 for branch in tree.branches)
    vertex_count = face_count = 0
    for branch in tree.branches:
        if not branch.items:
            yield branch.path + (0,) if split else branch.path, None, ''
        for slot, mesh in enumerate(branch.items):
            if not isinstance(mesh, MeshValue):
                raise ValueError(f'{name} requires Mesh data.')
            vertex_count += len(mesh.vertices)
            face_count += len(mesh.triangles)
            if max(vertex_count, face_count) > MAX_ITEMS:
                raise ValueError(f'{name} supports up to {MAX_ITEMS:,} vertices and faces in total.')
            path = branch.path + (slot,) if split else branch.path
            prefix = hashlib.sha256(repr((branch.path, branch.keys[slot], mesh.key, slot)).encode()).hexdigest()[:24]
            yield path, mesh, prefix


def _deconstruct(tree):
    outputs = {port: [] for port in MESH_SPECS[DECONSTRUCT_MESH]['outputs']}
    for path, mesh, prefix in _mesh_branches(tree, 'Deconstruct Mesh'):
        if mesh is None:
            for branches in outputs.values():
                branches.append(Branch(path, ()))
        else:
            vertices = tuple(PointValue(f'{prefix}:v:{index}', point) for index, point in enumerate(mesh.vertices))
            outputs['V'].append(Branch(path, vertices, tuple(point.key for point in vertices)))
            outputs['F'].append(Branch(path, mesh.triangles, tuple(f'{prefix}:f:{i}' for i in range(len(mesh.triangles)))))
            # Native MeshShape has no per-vertex colors.
            outputs['C'].append(Branch(path, ()))
            normals = tuple(VectorValue(normal) for normal in _vertex_normals(mesh))
            outputs['N'].append(Branch(path, normals, tuple(f'{prefix}:v:{i}' for i in range(len(normals)))))
    return {port: DataTree(tuple(branches)) for port, branches in outputs.items()}


def _face_normals(tree):
    centers, normals = [], []
    for path, mesh, prefix in _mesh_branches(tree, 'Face Normals'):
        points, vectors = [], []
        if mesh is not None:
            for index, triangle in enumerate(mesh.triangles):
                a, b, c = (mesh.vertices[i] for i in triangle)
                normal = cross(sub(b, a), sub(c, a))
                length = math.hypot(*normal)
                if not length:
                    raise ValueError(f'Face {index} on branch {path} has zero area.')
                key = f'{prefix}:f:{index}'
                points.append(PointValue(key, tuple((x + y + z) / 3 for x, y, z in zip(a, b, c))))
                vectors.append(VectorValue(tuple(component / length for component in normal)))
        keys = tuple(point.key for point in points)
        centers.append(Branch(path, points, keys))
        normals.append(Branch(path, vectors, keys))
    return {'C': DataTree(tuple(centers)), 'N': DataTree(tuple(normals))}


def _face_boundaries(tree):
    branches = []
    for path, mesh, prefix in _mesh_branches(tree, 'Face Boundaries'):
        boundaries = tuple(polyline(f'{prefix}:f:{i}', tuple(mesh.vertices[j] for j in face), True)
                           for i, face in enumerate(mesh.triangles)) if mesh is not None else ()
        branches.append(Branch(path, boundaries, tuple(value.key for value in boundaries)))
    return {'B': DataTree(tuple(branches))}


def _deconstruct_faces(tree):
    outputs = {port: [] for port in 'ABCD'}
    for branch in tree.branches:
        rows = []
        for face in branch.items:
            if (not isinstance(face, (tuple, list)) or len(face) not in (3, 4)
                    or any(type(index) is not int or index < 0 for index in face)):
                raise ValueError('Connect mesh faces with zero-based vertex indices.')
            rows.append((*face, face[2]) if len(face) == 3 else face)
        for index, port in enumerate(outputs):
            outputs[port].append(Branch(branch.path, tuple(face[index] for face in rows), branch.keys))
    return {port: DataTree(tuple(branches)) for port, branches in outputs.items()}


def _triangle_faces(state, inputs):
    trees = [input_tree(inputs.get(d.port, state['parameters'][d.port]), d,
                        state['tree_modes'].get(d.port, 'none'))
             for d in MESH_SPECS[TRIANGLE_FACE]['inputs']]
    widths = [{b.path: len(b.items) for b in tree.branches} for tree in trees]
    branches = []
    for path, rows in aligned(*trees):
        if rows and any(sizes.get(path, next(iter(sizes.values()))) not in (1, len(rows)) for sizes in widths):
            raise ValueError('Vertex indices need matching list lengths or a single shared index.')
        faces, keys = [], []
        for indices, provenance in rows:
            if any(not 0 <= index < MAX_ITEMS for index in indices):
                raise ValueError(f'Vertex indices must be between 0 and {MAX_ITEMS - 1:,}.')
            if len(set(indices)) != 3:
                raise ValueError('Triangle Face needs three distinct vertex indices.')
            faces.append(indices)
            keys.append('|'.join(provenance))
        branches.append(Branch(path, faces, keys))
    return {'F': DataTree(tuple(branches))}


def brep_mesh_settings(deflection, angle, relative):
    deflection, angle = map(finite_number, (deflection, angle))
    if type(relative) is not bool or deflection <= 0 or not 1 <= angle <= 90:
        raise ValueError('Use positive Linear Deflection and Angular Deflection from 1 to 90 degrees.')
    if relative and not .0001 <= deflection <= 1:
        raise ValueError('Relative Linear Deflection must be between 0.0001 and 1.')
    return deflection, angle, relative


def _mesh_key(path, slot=0):
    return hashlib.sha256(repr((path, slot)).encode()).hexdigest()[:24]


def _mesh_tree(branches):
    tree = DataTree(tuple(branches))
    if any(sum(len(getattr(mesh, field)) for mesh in tree.values()) > MAX_MESH_ELEMENTS
           for field in ('vertices', 'triangles')):
        raise ValueError('Mesh output exceeds the 10,000-vertex or triangle limit.')
    return {'M': tree}


def _mesh_inputs(operation, state, inputs):
    return tuple(input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                            state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
                 for d in MESH_SPECS[operation]['inputs'])


def _convert_breps(state, inputs, details):
    sources, rows, layout = {}, [], []
    for path, matched in _match(*_mesh_inputs(BREP_TO_MESH, state, inputs)):
        slots = []
        for slot, ((source, deflection, angle, relative), _) in enumerate(matched):
            settings = brep_mesh_settings(deflection, angle, relative)
            index = sources.setdefault(source, len(sources))
            slots.append(_mesh_key(path, slot))
            rows.append([index, *settings])
        layout.append((path, slots))
    if len(rows) > 240:
        raise ValueError('Brep to Mesh accepts up to 240 source items.')
    plan = {'operation': BREP_TO_MESH, 'sources': [source.to_wire() for source in sources], 'rows': rows}
    signature = request_signature(plan)
    if rows and details.get('signature') != signature:
        pending = PendingGeometry('Waiting for native Brep meshing')
        tree = DataTree(tuple(Branch(path, (pending,) if slots else ()) for path, slots in layout))
        return {'M': tree, '_sampling': {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                'signature': signature, 'plan': plan}}
    if rows and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native Brep to Mesh returned incomplete results.')
    values = iter(results)
    return _mesh_tree(Branch(path, tuple(mesh_from_wire({**next(values), 'key': key}) for key in slots), tuple(slots))
                      for path, slots in layout)


def _edit_meshes(operation, state, inputs):
    trees = _mesh_inputs(operation, state, inputs)
    branches = []
    if operation == MESH_JOIN:
        for branch in trees[0].branches:
            if any(not isinstance(mesh, MeshValue) for mesh in branch.items):
                raise ValueError('Mesh Join requires Mesh data.')
            values = (join_meshes(_mesh_key(branch.path), branch.items),) if branch.items else ()
            branches.append(Branch(branch.path, values, tuple(mesh.key for mesh in values)))
    else:
        for path, matched in _match(*trees):
            values = []
            for index, ((mesh, tolerance, angle), _) in enumerate(matched):
                if not isinstance(mesh, MeshValue):
                    raise ValueError('Weld Mesh requires Mesh data.')
                values.append(weld_mesh(_mesh_key(path, index), mesh, tolerance, angle))
            branches.append(Branch(path, values, tuple(mesh.key for mesh in values)))
    return _mesh_tree(branches)


def _face_neighbours(tree):
    neighbours, boundary, nonmanifold, remaining = [], [], [], MAX_ITEMS
    for path, mesh, prefix in _mesh_branches(tree, 'Face Neighbours'):
        if mesh is None:
            neighbours.append(Branch(path + (0,), ()))
            boundary.append(Branch(path, ()))
            nonmanifold.append(Branch(path, ()))
            continue
        rows, b, x, remaining = face_neighbours(mesh, remaining)
        keys = tuple(f'{prefix}:f:{index}' for index in range(len(rows)))
        neighbours.extend(Branch(path + (index,), row) for index, row in enumerate(rows))
        boundary.append(Branch(path, b, keys))
        nonmanifold.append(Branch(path, x, keys))
    return {'N': DataTree(tuple(neighbours)), 'B': DataTree(tuple(boundary)), 'X': DataTree(tuple(nonmanifold))}


def evaluate(operation, parameters, inputs):
    if operation == BREP_TO_MESH:
        return _convert_breps(normalize_state(operation, parameters), inputs, parameters.get('sampling_details') or {})
    if operation in (MESH_JOIN, WELD_MESH):
        return _edit_meshes(operation, normalize_state(operation, parameters), inputs)
    if operation in (DELAUNAY_MESH, CONSTRUCT_MESH):
        return _build_meshes(operation, normalize_state(operation, parameters), inputs)
    if operation == TRIANGLE_FACE:
        return _triangle_faces(normalize_state(operation, parameters), inputs)
    if operation == DECONSTRUCT_FACE:
        if 'F' not in inputs:
            raise ValueError('Connect Mesh Faces to F.')
        return _deconstruct_faces(topology(inputs['F'], parameters.get('tree_modes', {}).get('F', 'none')))
    if operation == MESH:
        if parameters.get('reference_error'):
            raise ValueError(parameters['reference_error'])
        values = tuple(mesh_from_wire(record['recipe']) for record in parameters.get('references', ()))
        if not values:
            raise ValueError('Select native meshes in Serpentine, then click Set reference.')
        tree = DataTree((Branch((0,), values, tuple(value.key for value in values)),))
        return {'M': topology(tree, parameters.get('tree_modes', {}).get('References', 'none'))}
    if 'M' not in inputs:
        raise ValueError('Connect Mesh to M.')
    tree = topology(inputs['M'], parameters.get('tree_modes', {}).get('M', 'none'))
    if operation == DECONSTRUCT_MESH:
        return _deconstruct(tree)
    if operation == FACE_NORMALS:
        return _face_normals(tree)
    if operation == FACE_BOUNDARIES:
        return _face_boundaries(tree)
    if operation == FACE_NEIGHBOURS:
        return _face_neighbours(tree)
    outputs = {port: [] for port in MESH_SPECS[MESH_EDGES]['outputs']}
    total = 0
    for branch in tree.branches:
        groups = {port: [] for port in outputs}
        for slot, mesh in enumerate(branch.items):
            if not isinstance(mesh, MeshValue):
                raise ValueError('Mesh Edges requires native Mesh data.')
            prefix = hashlib.sha256(repr((branch.path, branch.keys[slot], mesh.key, slot)).encode()).hexdigest()[:24]
            for (a, b), count in sorted(_edge_counts(mesh).items()):
                start, end = mesh.vertices[a], mesh.vertices[b]
                if math.dist(start, end) <= 1e-9:
                    continue
                total += 1
                if total > MAX_ITEMS:
                    raise ValueError(f'Mesh Edges exceeds the {MAX_ITEMS:,}-edge limit.')
                groups[f'E{min(3, count)}'].append(line(f'{prefix}:{a}:{b}', start, end))
        for port, values in groups.items():
            outputs[port].append(Branch(branch.path, values, tuple(value.key for value in values)))
    return {port: DataTree(tuple(branches)) for port, branches in outputs.items()}
