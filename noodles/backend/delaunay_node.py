"""Shared Delaunay/Voronoi DataTree contract and deferred contours."""
import hashlib
from collections import Counter

from .curves import CurveInput, input_tree, normalize_curve_state, polyline, xyz
from .datatree import Branch, DataTree, aligned
from .honeycomb import DEFAULT_CELL_SIZE
from .moves import geometry_wire
from .parametric import ParametricObject
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry
from .tessellation import MAX_CELLS, TESSELLATION, contours


DELAUNAY = 'delaunay'
VORONOI = 'voronoi'
HEXAGON_TILING = 'hexagon_tiling'
SITE_LIMITS = {DELAUNAY: 1700, VORONOI: 1800}
DELAUNAY_SPEC = {'class': 'DelaunayNode', 'name': 'Delaunay', 'category': 'Operations',
                'primary': 'C', 'reference': False, 'inputs': (
    CurveInput('P', 'Points', 'points'),
    CurveInput('Pl', 'Plane', 'plane', optional=True),
    CurveInput('B', 'Boundary Curve or Planar Surface', 'geometry', optional=True)),
    'outputs': ('C', 'Count')}
TESSELLATION_SPECS = {DELAUNAY: DELAUNAY_SPEC,
                      VORONOI: {**DELAUNAY_SPEC, 'class': 'VoronoiNode', 'name': 'Voronoi'},
                      HEXAGON_TILING: {**DELAUNAY_SPEC, 'class': 'HexagonTilingNode', 'name': 'Hexagon Tiling',
                          'inputs': (CurveInput('B', 'Boundary Curve or Planar Surface', 'geometry'),
                                     CurveInput('S', 'Cell Size Across Flats', 'number', DEFAULT_CELL_SIZE),
                                     CurveInput('Pl', 'Plane', 'plane', optional=True)),
                          'outputs': ('C', 'H', 'P', 'Count')}}


def normalize_state(data, operation=DELAUNAY):
    spec = TESSELLATION_SPECS[operation]
    state = normalize_curve_state(operation, data, spec=spec)
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        if operation == HEXAGON_TILING:
            raise ValueError('Hexagon Tiling uses connected Boundary geometry.')
        raise ValueError(f'{spec["name"]} uses connected point data.')
    periodic = data.get('parameters', {}).get('periodic_u', False)
    if type(periodic) is not bool:
        raise ValueError('Periodic U must be Boolean.')
    state['parameters']['periodic_u'] = periodic
    return state


def match_branches(tree, paths, label):
    if tree is None:
        return dict.fromkeys(paths)
    if tree.count == 1:
        return dict.fromkeys(paths, tree.values()[0])
    if set(paths) != {b.path for b in tree.branches} or any(len(b.items) != 1 for b in tree.branches):
        raise ValueError(f'{label} needs one shared value or one value per point branch.')
    return {b.path: b.items[0] for b in tree.branches}


def _site_slots(keys):
    occurrences = Counter()
    slots = []
    for key in keys:
        slots.append((key, occurrences[key]))
        occurrences[key] += 1
    return slots


def evaluate(parameters, inputs, operation=DELAUNAY):
    state = normalize_state(parameters, operation)
    if operation == HEXAGON_TILING:
        return _evaluate_hexagons(parameters, state, inputs)
    name = TESSELLATION_SPECS[operation]['name']
    modifiers = state['tree_modes']
    trees = {d.port: input_tree(inputs[d.port], d, modifiers.get(d.port, 'none'))
             for d in TESSELLATION_SPECS[operation]['inputs'] if d.port in inputs}
    points = trees['P']
    periodic = state['parameters']['periodic_u']
    limit = SITE_LIMITS[operation]
    if points.count > limit:
        raise ValueError(f'{name} supports up to {limit} points in total.')
    if operation == DELAUNAY and any(0 < len(b.items) < 3 for b in points.branches):
        raise ValueError('Delaunay needs at least three points per nonempty branch.')
    if periodic and 'B' not in trees:
        raise ValueError('Periodic U needs a rectangle at Boundary.')
    paths = [b.path for b in points.branches if b.items]
    planes, boundaries = (match_branches(trees.get(port), paths, label) for port, label in (
        ('Pl', 'Plane'), ('B', 'Boundary'))) if paths else ({}, {})
    rows = [{'sites': [list(p.xyz) for p in b.items],
             'plane': planes[b.path].to_wire() if planes[b.path] is not None else None,
             'boundary': geometry_wire(boundaries[b.path]) if boundaries[b.path] is not None else None}
            for b in points.branches if b.items]
    plan = {'periodic_u': periodic, 'rows': rows}
    if operation == VORONOI:
        plan['algorithm'] = VORONOI
    stamp = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if rows and detail.get('signature') != stamp:
        pending = PendingGeometry(f'Waiting for {name}')
        return {'C': DataTree(tuple(Branch(b.path, (pending,) if b.items else ()) for b in points.branches)),
                'Count': pending, '_sampling': {'project_uuid': state['project_uuid'],
                'node_uuid': state['node_uuid'], 'signature': stamp, 'plan': plan}}
    if rows and detail.get('error'):
        raise ValueError(detail['error'])
    values = detail.get('values', []) if rows else []
    if len(values) != len(rows):
        raise ValueError(f'{name} returned an incomplete tessellation.')
    measured = iter(values)
    branches, count = [], 0
    for branch in points.branches:
        result = []
        if branch.items:
            vertices, indices, *owners = next(measured)
            if owners:
                slots = _site_slots(branch.keys)
                provenance = [(slots[site], piece) for site, piece in owners[0]]
            else:
                provenance = [sorted(ids) for ids in indices]
            if len(provenance) != len(indices):
                raise ValueError(f'{name} returned an incomplete contour list.')
            for slot, polygon in zip(provenance, contours(vertices, indices)):
                key = hashlib.sha256(repr((branch.path, slot)).encode()).hexdigest()[:24]
                result.append(polyline(key, polygon, True))
        count += len(result)
        if count > MAX_CELLS:
            raise ValueError(f'{name} exceeds the contour limit.')
        branches.append(Branch(branch.path, tuple(result), tuple(v.key for v in result)))
    return {'C': DataTree(tuple(branches)), 'Count': count}


def _evaluate_hexagons(parameters, state, inputs):
    spec = TESSELLATION_SPECS[HEXAGON_TILING]
    if 'B' not in inputs:
        raise ValueError('Connect input B.')
    trees = [input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                        state['tree_modes'].get(d.port, 'none'))
             if d.port in inputs or d.default is not None else None for d in spec['inputs']]
    rows, branches = [], []
    for path, records in aligned(*trees):
        slots = []
        occurrences = Counter()
        for (boundary, size, plane), keys in records:
            if size <= 0.:
                raise ValueError('Cell Size must be positive.')
            slots.append((len(rows), keys, occurrences[keys]))
            occurrences[keys] += 1
            rows.append({'boundary': geometry_wire(boundary), 'size': size,
                         'plane': plane.to_wire() if plane is not None else None})
        branches.append((path, slots))
    plan = {'algorithm': HEXAGON_TILING, 'periodic_u': state['parameters']['periodic_u'], 'rows': rows}
    stamp = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if rows and detail.get('signature') != stamp:
        pending = PendingGeometry('Waiting for Hexagon Tiling')
        return {**dict.fromkeys(spec['outputs'], pending), '_sampling': {
            'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'], 'signature': stamp, 'plan': plan}}
    if rows and detail.get('error'):
        raise ValueError(detail['error'])
    values = detail.get('values', []) if rows else []
    if len(values) != len(rows):
        raise ValueError('Hexagon Tiling returned an incomplete pattern.')
    outputs = {port: [] for port in ('C', 'H', 'P')}
    for path, slots in branches:
        cells, complete, centers = [], [], []
        for i, keys, occurrence in slots:
            vertices, indices, owners = values[i]
            if len(owners) != len(indices):
                raise ValueError('Hexagon Tiling returned an incomplete contour list.')
            for (row, column, wrap, piece, center), polygon in zip(owners, contours(vertices, indices)):
                key = hashlib.sha256(repr((path, keys, occurrence, row, column, wrap, piece)).encode()).hexdigest()[:24]
                cell = polyline(key, polygon, True)
                cells.append(cell)
                if center is not None:
                    complete.append(cell)
                    centers.append(PointValue(key, xyz(center)))
        for port, items in zip(outputs, (cells, complete, centers)):
            outputs[port].append(Branch(path, tuple(items), tuple(item.key for item in items)))
    trees = {port: DataTree(tuple(items)) for port, items in outputs.items()}
    return {**trees, 'Count': trees['C'].count}


def object_from_outputs(parameters, outputs):
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['C'], kind=TESSELLATION)
