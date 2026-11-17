"""Population nodes produce typed points without adding scene objects."""
import hashlib

from .curves import CurveInput, input_tree, matched_inputs, normalize_curve_state, xyz
from .datatree import Branch, DataTree, MAX_ITEMS, aligned
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry


POPULATION_LIMITS = {'populate_2d': (2000, MAX_ITEMS), 'populate_geometry': (128, 10000)}
POPULATION_SPECS = {}
for operation, name, class_name, port in (
    ('populate_2d', 'Populate 2D', 'Populate2DNode', CurveInput('R', 'Rectangular Curve or Surface', 'geometry')),
    ('populate_geometry', 'Populate Geometry', 'PopulateGeometryNode', CurveInput('G', 'Geometry', 'move_geometry')),
):
    count_kind = 'population_2d_count' if operation == 'populate_2d' else 'population_count'
    POPULATION_SPECS[operation] = {'name': name, 'class': class_name, 'reference': False,
        'category': 'Operations', 'inputs': (port, CurveInput('N', 'New Point Count', count_kind, 100),
        CurveInput('S', 'Random Seed', 'population_seed', 0),
        CurveInput('P', 'Existing Points', 'points', optional=True)), 'outputs': ('P',)}


def normalize_state(operation, parameters):
    state = normalize_curve_state(operation, parameters, spec=POPULATION_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Populate uses connected geometry.')
    return state


def seed_for(operation, seed, path):
    separator, size = (';', 16) if operation == 'populate_2d' else (',', 8)
    text = f'{seed}|' + separator.join(map(str, path))
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=size).digest(), 'big')


def evaluate(operation, parameters, inputs):
    from .moves import geometry_wire

    state = normalize_state(operation, parameters)
    *required, existing = POPULATION_SPECS[operation]['inputs']
    def tree(d):
        return input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                          state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
    tasks = []
    for path, rows in aligned(*matched_inputs([tree(d) for d in required])):
        if not rows:
            tasks.append((path, None, 0, 0))
        for i, ((source, count, seed), _) in enumerate(rows):
            output_path = (*path, i) if len(rows) > 1 else path
            tasks.append((output_path, source, count, seed_for(operation, seed, output_path)))
    region_limit, point_limit = POPULATION_LIMITS[operation]
    if len(tasks) > region_limit or sum(t[2] for t in tasks) > point_limit:
        raise ValueError(f'Population exceeds the {region_limit} region or {point_limit} point limit.')
    paths = {path for path, *_ in tasks}
    prior = {}
    if 'P' in inputs:
        points = tree(existing)
        if len(tasks) == len(points.branches) == 1:
            prior[tasks[0][0]] = points.branches[0].items
        elif paths != {b.path for b in points.branches}:
            raise ValueError('Existing Points must match the population branch paths.')
        else:
            prior = {b.path: b.items for b in points.branches}
        if points.count + sum(t[2] for t in tasks) > point_limit:
            raise ValueError(f'Population exceeds the {point_limit} point limit including Existing Points.')
    sources, indices, rows = [], {}, []
    for path, source, count, seed in tasks:
        index = None
        if source is not None:
            if source not in indices:
                indices[source] = len(sources)
                sources.append(geometry_wire(source))
            index = indices[source]
        rows.append({'source': index, 'count': count, 'seed': str(seed),
                     'prior': [list(p.xyz) for p in prior.get(path, ())]})
    plan = {'operation': operation, 'sources': sources, 'rows': rows}
    signature = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if any(source is not None for _, source, _, _ in tasks) and detail.get('signature') != signature:
        pending = PendingGeometry('Waiting for native population')
        return {'P': DataTree(tuple(Branch(path, (pending,) if source is not None else ())
                                    for path, source, _, _ in tasks)),
                '_sampling': {**{key: state[key] for key in ('project_uuid', 'node_uuid')},
                              'signature': signature, 'plan': plan}}
    if detail.get('signature') == signature and detail.get('error'):
        raise ValueError(detail['error'])
    samples = detail.get('values', []) if detail.get('signature') == signature else [[] for _ in rows]
    if len(samples) != len(rows) or any(len(sample) != row['count'] for sample, row in zip(samples, rows)):
        raise ValueError('Native population returned incomplete results.')
    branches = []
    for (path, _, _, _), sample in zip(tasks, samples):
        prefix = hashlib.sha256(repr((state['node_uuid'], path)).encode()).hexdigest()[:24]
        result = prior.get(path, ()) + tuple(PointValue(f'{prefix}:sample:{i}', xyz(v)) for i, v in enumerate(sample))
        branches.append(Branch(path, result, tuple(p.key for p in result)))
    return {'P': DataTree(tuple(branches))}
