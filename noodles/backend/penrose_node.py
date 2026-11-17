"""DataTree contract for the native Penrose P2 pattern."""
import hashlib
from collections import Counter

from .curves import CurveInput, arc, input_tree, normalize_curve_state, polyline
from .datatree import Branch, DataTree, aligned
from .moves import geometry_wire
from .parametric import ParametricObject
from .penrose import KITE
from .pull import request_signature
from .splines import PendingGeometry
from .tessellation import cell_points


PENROSE = 'penrose_p2'
DEFAULT_GENERATIONS = 4
DEFAULT_DIAMETER = 100.
SPEC = {'class': 'PenroseP2Node', 'name': 'Penrose P2', 'category': 'Operations',
        'primary': 'C', 'reference': False, 'inputs': (
            CurveInput('B', 'Convex Boundary', 'geometry', optional=True),
            CurveInput('Pl', 'Plane', 'plane', optional=True),
            CurveInput('S', 'Sun Diameter (without Boundary)', 'number', DEFAULT_DIAMETER),
            CurveInput('N', 'Generations', 'penrose_generations', DEFAULT_GENERATIONS)),
        'outputs': ('C', 'K', 'D', 'A', 'Count')}


def normalize_state(data):
    state = normalize_curve_state(PENROSE, data, spec=SPEC)
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Penrose P2 generates a planar pattern.')
    matching = data.get('parameters', {}).get('matching_arcs', True)
    if type(matching) is not bool:
        raise ValueError('Matching Arcs must be Boolean.')
    state['parameters']['matching_arcs'] = matching
    return state


def evaluate(parameters, inputs):
    state = normalize_state(parameters)
    options = state['parameters']
    trees = [input_tree(inputs.get(d.port, options.get(d.port)), d, state['tree_modes'].get(d.port, 'none'),
                        d.port not in inputs)
             if d.port in inputs or d.default is not None else None for d in SPEC['inputs']]
    rows, branches = [], []
    for path, items in aligned(*trees):
        start = len(rows)
        slots = []
        occurrences = Counter()
        for (boundary, plane, diameter, generations), keys in items:
            slots.append((keys, occurrences[keys]))
            occurrences[keys] += 1
            rows.append({'boundary': geometry_wire(boundary) if boundary is not None else None,
                         'plane': plane.to_wire() if plane is not None else None,
                         'diameter': diameter, 'generations': generations})
        branches.append((path, start, slots))
    plan = {'algorithm': PENROSE, 'matching_arcs': options['matching_arcs'], 'rows': rows}
    signature = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if rows and detail.get('signature') != signature:
        pending = PendingGeometry('Waiting for Penrose P2')
        return {**dict.fromkeys(SPEC['outputs'], pending), '_sampling': {
            'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
            'signature': signature, 'plan': plan}}
    if rows and detail.get('error'):
        raise ValueError(detail['error'])
    values = detail.get('values', []) if rows else []
    if len(values) != len(rows):
        raise ValueError('Penrose P2 returned an incomplete pattern.')
    outputs = {port: [] for port in ('C', 'K', 'D', 'A')}
    for path, start, slots in branches:
        parts = {port: [] for port in outputs}
        for index, slot in enumerate(slots, start):
            vertices, records = values[index]
            for tile, kind, piece, indices in records:
                key = hashlib.sha256(repr((path, slot, tile, kind, piece)).encode()).hexdigest()[:24]
                points = cell_points(vertices, indices)
                if kind == 'arc':
                    parts['A'].append(arc(key, *points))
                else:
                    curve = polyline(key, points, True)
                    parts['C'].append(curve)
                    parts['K' if kind == KITE else 'D'].append(curve)
        for port, items in parts.items():
            outputs[port].append(Branch(path, tuple(items), tuple(v.key for v in items)))
    outputs = {port: DataTree(tuple(items)) for port, items in outputs.items()}
    return {**outputs, 'Count': outputs['C'].count}


def object_from_outputs(parameters, outputs):
    parts = DataTree(tuple(Branch(c.path, c.items + a.items, c.keys + a.keys)
                           for c, a in zip(outputs['C'].branches, outputs['A'].branches)))
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], parts, kind=PENROSE)
