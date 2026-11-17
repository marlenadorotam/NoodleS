"""Read-only closest-point plans with one result per source point."""
import hashlib
import json
import math

from .curves import CurveInput, input_tree, is_curve_recipe, normalize_curve_state, xyz
from .datatree import Branch, DataTree, MAX_ITEMS
from .point import PointValue
from .splines import PendingGeometry

PULL_SPEC = {'class': 'PullPointNode', 'name': 'Pull Point', 'reference': False,
             'category': 'Operations', 'inputs': (CurveInput('P', 'Points', 'points'),
             CurveInput('G', 'Attractor Points / Curves', 'pull_attractor')), 'outputs': ('P', 'D')}
MAX_COMPARISONS = 2_000_000


def normalize_pull_state(data):
    state = normalize_curve_state('pull_point', data, spec=PULL_SPEC)
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Pull Point uses connected geometry.')
    return state


def is_attractor(value):
    from .moves import TranslatedValue
    while isinstance(value, TranslatedValue):
        value = value.source
    return isinstance(value, PointValue) or is_curve_recipe(value)


def branch_pairs(points, attractors):
    if not points.branches:
        return
    if not attractors.branches:
        if points.count:
            raise ValueError('Pull Point needs at least one attractor.')
        yield from ((b.path, b, ()) for b in points.branches)
        return
    primary = (points if len(points.branches) > 1 else attractors if len(attractors.branches) > 1 else
               max((points, attractors), key=lambda t: (len(t.branches[0].path), t.branches[0].path != (0,))))
    left, right = ({b.path: b for b in tree.branches} for tree in (points, attractors))
    paths = {b.path for b in primary.branches}
    if any(len(index) > 1 and index.keys() != paths for index in (left, right)):
        raise ValueError('Pull Point needs matching branch paths or a single shared branch.')
    for branch in primary.branches:
        path = branch.path
        yield path, left.get(path, points.branches[0]), right.get(path, attractors.branches[0]).items


def request_signature(plan):
    return hashlib.sha256(json.dumps(plan, separators=(',', ':'), sort_keys=True).encode()).hexdigest()


def evaluate_pull(parameters, inputs):
    state = normalize_pull_state(parameters)
    points, attractors = (input_tree(inputs[d.port], d, state['tree_modes'].get(d.port, 'none'))
                         for d in PULL_SPEC['inputs'])
    pairs = tuple(branch_pairs(points, attractors))
    count = sum(len(branch.items) for _, branch, _ in pairs)
    if count > MAX_ITEMS or sum(len(branch.items)*len(items) for _, branch, items in pairs) > MAX_COMPARISONS:
        raise ValueError('Pull Point exceeds the output or 2,000,000-comparison limit.')
    if any(branch.items and not items for _, branch, items in pairs):
        raise ValueError('Pull Point needs at least one attractor per nonempty point branch.')

    def build(results):
        closest, distances = [], []
        for (path, branch, _), values in zip(pairs, results):
            p, d = zip(*values) if values else ((), ())
            closest.append(Branch(path, tuple(p), branch.keys))
            distances.append(Branch(path, tuple(d), branch.keys))
        return {'P': DataTree(tuple(closest)), 'D': DataTree(tuple(distances))}

    if not any(branch.items and any(not isinstance(item, PointValue) for item in items)
               for _, branch, items in pairs):
        result = []
        for _, branch, items in pairs:
            candidates = [p.xyz for p in items]
            rows = []
            for key, point in zip(branch.keys, branch.items):
                distance, match = min(((math.dist(point.xyz, c), c) for c in candidates), key=lambda v: v[0])
                rows.append((PointValue(key, match), distance))
            result.append(rows)
        return build(result)

    # Store each attractor branch once, including when broadcast to many paths.
    groups, index, rows = [], {}, []
    for _, branch, items in pairs:
        group = id(items)
        if group not in index:
            index[group] = len(groups)
            wires = []
            for item in items:
                wire = item.to_wire()
                if 'knots' in wire:
                    wire.pop('length', None)
                wires.append(wire)
            groups.append(wires)
        rows.append({'points': [list(point.xyz) for point in branch.items], 'group': index[group]})
    plan = {'groups': groups, 'rows': rows}
    signature = request_signature(plan)
    record = parameters.get('pull_details') or {}
    if record.get('signature') == signature:
        if record.get('error'):
            raise ValueError(record['error'])
        values = record['values']
        if len(values) != len(pairs) or any(len(v) != len(b.items) for v, (_, b, _) in zip(values, pairs)):
            raise ValueError('Pull Point returned incomplete measurements.')
        return build([[(PointValue(key, xyz(match)), math.dist(point.xyz, match))
                       for key, point, match in zip(branch.keys, branch.items, row)]
                      for (_, branch, _), row in zip(pairs, values)])
    pending = PendingGeometry('Waiting for native Pull Point measurement')
    output = build([[(pending, pending)]*len(branch.items) for _, branch, _ in pairs])
    output['_pull'] = {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                       'signature': signature, 'plan': plan}
    return output
