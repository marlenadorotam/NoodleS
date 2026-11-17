"""Read-only curve sampling plans and typed DataTree outputs."""
from .arithmetic import VectorValue
from .curves import CurveInput, PlaneValue, input_tree, is_curve_recipe, matched_inputs, normalize_curve_state, xyz
from .datatree import Branch, DataTree, aligned
from .domain import DomainValue
from .list_nodes import _list_branches
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry


MAX_DIVISIONS = 500
MAX_SAMPLES = 5000
MAX_FRAMES = 3500  # Frames carry three extra coordinates within the same JSON budget.
MAX_FRAME_PARAMETERS = 512
CURVES = CurveInput('C', 'Curves', 'sample_curve')
COUNT = CurveInput('N', 'Count', 'division_count', 10)
GUIDE = CurveInput('G', 'Guide Vector', 'vector', (0., 0., 1.))
PARAMETERS = CurveInput('t', 'Parameters', 'number', 0.)
FRAME_OUTPUTS = ('F', 'P', 'T', 't', 'Count')
FRAME_OPERATIONS = ('frame', 'perp_frames')
CURVATURE = 'curve_curvature'
POINT_IN_CURVE = 'point_in_curve'
CLOSEST_POINT = 'curve_closest_point'
SORT_ALONG_CURVE = 'sort_along_curve'
EVALUATE_CURVE = 'evaluate_curve'
CURVE_LENGTH = 'curve_length'
DIVIDE_BY_LENGTH = 'divide_by_length'
EXPLICIT_SAMPLING = ('frame', CURVATURE, EVALUATE_CURVE)
NORMALIZED = CurveInput('N', 'Normalized', 'boolean', True)
SAMPLING_SPECS = {
    'curve_domain': {'class': 'CurveDomainNode', 'name': 'Curve Domain', 'reference': False,
                     'category': 'Operations', 'inputs': (CURVES,), 'outputs': ('D', 'L')},
    CURVE_LENGTH: {'class': 'CurveLengthNode', 'name': 'Curve Length', 'reference': False,
                   'category': 'Operations', 'inputs': (CURVES,), 'outputs': ('L',), 'primary': 'L'},
    'divide_curve': {'class': 'DivideCurveNode', 'name': 'Divide Curve', 'reference': False,
                     'category': 'Operations', 'inputs': (CURVES, COUNT,
                     CurveInput('K', 'Kinks', 'boolean', False)), 'outputs': ('P', 'T', 't', 'Count'),
                     'primary': 'P'},
    DIVIDE_BY_LENGTH: {'class': 'DivideByLengthNode', 'name': 'Divide by Length', 'reference': False,
                       'category': 'Operations', 'inputs': (CURVES, CurveInput('L', 'Segment Length', 'number', 1.),
                       CurveInput('R', 'Include Remainder', 'boolean', True)), 'outputs': ('P', 'T', 't', 'Count'),
                       'primary': 'P'},
    'frame': {'class': 'FrameNode', 'name': 'Frame', 'reference': False, 'category': 'Operations',
              'inputs': (CURVES, PARAMETERS, GUIDE, NORMALIZED),
              'outputs': FRAME_OUTPUTS, 'primary': 'F'},
    'perp_frames': {'class': 'PerpFramesNode', 'name': 'Perp Frames', 'reference': False, 'category': 'Operations',
                    'inputs': (CURVES, COUNT, CurveInput('A', 'Align', 'boolean', True), GUIDE),
                    'outputs': FRAME_OUTPUTS, 'primary': 'F'},
    CURVATURE: {'class': 'CurveCurvatureNode', 'name': 'Curve Curvature', 'reference': False,
                'category': 'Operations', 'inputs': (CURVES, PARAMETERS, NORMALIZED),
                'outputs': ('P', 'K'), 'primary': 'P'},
    EVALUATE_CURVE: {'class': 'EvaluateCurveNode', 'name': 'Evaluate Curve', 'reference': False,
                     'category': 'Operations', 'inputs': (CURVES, PARAMETERS, NORMALIZED),
                     'outputs': ('P', 'T', 't', 'Count'), 'primary': 'P'},
    CLOSEST_POINT: {'class': 'CurveClosestPointNode', 'name': 'Curve Closest Point', 'reference': False,
                    'category': 'Operations', 'inputs': (CurveInput('P', 'Points', 'points'), CURVES, NORMALIZED),
                    'outputs': ('P', 't', 'D'), 'primary': 'P'},
    SORT_ALONG_CURVE: {'class': 'SortAlongCurveNode', 'name': 'Sort Along Curve', 'reference': False,
                       'category': 'Operations', 'inputs': (CurveInput('P', 'Points', 'points'),
                                                           CurveInput('C', 'Guide Curve', 'sample_curve')),
                       'outputs': ('P', 'I', 't'), 'primary': 'P'},
    POINT_IN_CURVE: {'class': 'PointInCurveNode', 'name': 'Point In Curve', 'reference': False,
                     'category': 'Operations', 'inputs': (CurveInput('P', 'Points', 'points'),
                         CurveInput('C', 'Closed Planar Curve', 'sample_curve')), 'outputs': ('R', 'I')},
}


def is_sample_curve(value):
    return is_curve_recipe(value)


def normalize_sampling_state(operation, data):
    state = normalize_curve_state(operation, data, spec=SAMPLING_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Curve sampling uses connected curves.')
    return state


def _layout(trees, domain, *, split_items=True):
    curves = trees[0]
    if domain or not curves.count:
        return [(b.path, tuple(zip(b.keys, b.items))) for b in curves.branches], False
    matched_trees = matched_inputs(trees)
    matched = list(aligned(*matched_trees))
    source = matched_trees[0]
    sizes = {b.path: len(b.items) for b in source.branches}
    if (sum(len(rows) for _, rows in matched) != curves.count
            or any(len(rows) != sizes.get(path, len(source.branches[0].items)) for path, rows in matched)):
        raise ValueError('Sampling options must match the supplied curves.')
    if not split_items:
        return [(path, tuple((keys[0], *items) for items, keys in rows)) for path, rows in matched], False
    # Extend every path when splitting so {a} and {a;0} cannot collide.
    split = any(len(rows) > 1 for _, rows in matched)
    layout = []
    for path, rows in matched:
        if not rows:
            layout.append((path + ((0,) if split else ()), ()))
        for i, (items, keys) in enumerate(rows):
            layout.append((path + ((i,) if split else ()), ((keys[0], *items),)))
    return layout, split


def _request_rows(operation, layout, parameters, split):
    by_path = {b.path: b.items for b in parameters.branches}
    shared = parameters.branches[0].items if len(parameters.branches) == 1 else None
    rows, total = [], 0
    limit = MAX_FRAMES if operation in FRAME_OPERATIONS else MAX_SAMPLES
    for path, entries in layout:
        for _, curve, *options in entries:
            row = {'curve': curve.to_wire()}
            if operation in EXPLICIT_SAMPLING:
                values = shared if shared is not None else by_path.get(path)
                if values is None and split:
                    values = by_path.get(path[:-1])
                if not values:
                    raise ValueError(f'{SAMPLING_SPECS[operation]["name"]} t needs a shared list or matching nonempty parameter branches.')
                if len(values) > MAX_FRAME_PARAMETERS:
                    raise ValueError(f'Use up to {MAX_FRAME_PARAMETERS} parameters per curve.')
                row.update(parameters=values, normalized=options[-1])
                if operation == 'frame':
                    row['guide'] = options[0].xyz
                total += len(values)
            elif operation in ('divide_curve', 'perp_frames'):
                count, option, *guide = options
                row['count'] = count
                if operation == 'perp_frames':
                    row.update(align=option, guide=guide[0].xyz)
                else:
                    row['kinks'] = option
                total += count
            elif operation == DIVIDE_BY_LENGTH:
                length, remainder = options
                if length <= 0:
                    raise ValueError('Segment Length must be positive.')
                row.update(length=length, remainder=remainder)
            if total > limit:
                raise ValueError(f'{SAMPLING_SPECS[operation]["name"]} exceeds the {limit:,}-sample limit.')
            rows.append(row)
    return rows


def evaluate_sampling(operation, parameters, inputs):
    state = normalize_sampling_state(operation, parameters)
    trees = {d.port: input_tree(inputs.get(d.port, state['parameters'].get(d.port, [])), d,
                               state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
             for d in SAMPLING_SPECS[operation]['inputs']}
    if operation == POINT_IN_CURVE:
        return evaluate_containment(state, trees, parameters.get('sampling_details') or {})
    if operation == CLOSEST_POINT:
        return evaluate_closest(state, trees, parameters.get('sampling_details') or {})
    if operation == SORT_ALONG_CURVE:
        return evaluate_sort_along_curve(state, trees, parameters.get('sampling_details') or {})
    parameter_tree = trees.pop('t', DataTree(()))
    layout, split = _layout(tuple(trees.values()), operation in ('curve_domain', CURVE_LENGTH))
    rows = _request_rows(operation, layout, parameter_tree, split)
    plan = {'operation': operation, 'rows': rows}
    signature = request_signature(plan)
    record = parameters.get('sampling_details') or {}
    pending = PendingGeometry('Waiting for native curve sampling')
    if not rows:
        values = []
    elif record.get('signature') == signature:
        if record.get('error'):
            raise ValueError(record['error'])
        values = record['values']
        if len(values) != len(rows):
            raise ValueError('Native curve sampling returned incomplete results.')
    else:
        values = None
    output = _outputs(operation, layout, iter(values) if values is not None else None, pending)
    if values is None:
        output['_sampling'] = {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                               'signature': signature, 'plan': plan}
    return output


def _outputs(operation, layout, values, pending):
    if operation == CURVE_LENGTH:
        return {'L': DataTree(tuple(Branch(path, tuple(next(values) if values is not None else pending
                                                     for _ in items), tuple(key for key, _ in items))
                                    for path, items in layout))}
    if operation == 'curve_domain':
        domains, spans = [], []
        for path, items in layout:
            keys = tuple(key for key, _ in items)
            intervals = tuple(DomainValue(*next(values)) if values is not None else pending for _ in items)
            domains.append(Branch(path, intervals, keys))
            spans.append(Branch(path, tuple(v.length if isinstance(v, DomainValue) else v for v in intervals), keys))
        return {'D': DataTree(tuple(domains)), 'L': DataTree(tuple(spans))}

    if operation == CURVATURE:
        points, vectors = [], []
        for path, items in layout:
            p = k = keys = ()
            if items and values is None:
                p = k = (pending,)
                keys = (items[0][0],)
            elif items:
                samples = next(values)
                keys = tuple(f'{items[0][0]}:sample:{i}' for i in range(len(samples)))
                p = tuple(PointValue(key, xyz(sample[:3])) for key, sample in zip(keys, samples))
                k = tuple(VectorValue(tuple(sample[3:6])) for sample in samples)
            points.append(Branch(path, p, keys))
            vectors.append(Branch(path, k, keys))
        return {'P': DataTree(tuple(points)), 'K': DataTree(tuple(vectors))}

    with_frames = operation in FRAME_OPERATIONS
    points, tangents, parameters, frames = [], [], [], []
    for path, items in layout:
        if not items:
            p = t = u = f = keys = ()
        elif values is None:
            p = t = u = f = (pending,)
            keys = (items[0][0],)
        else:
            samples = next(values)
            keys = tuple(f'{items[0][0]}:sample:{i}' for i in range(len(samples)))
            p = tuple(PointValue(key, xyz(sample[:3])) for key, sample in zip(keys, samples))
            t = tuple(VectorValue(tuple(sample[3:6])) for sample in samples)
            u = tuple(sample[6] for sample in samples)
            if with_frames:
                f = tuple(PlaneValue(point.xyz, tuple(sample[7:10]), tangent.xyz)
                          for point, tangent, sample in zip(p, t, samples))
        points.append(Branch(path, p, keys))
        tangents.append(Branch(path, t, keys))
        parameters.append(Branch(path, u, keys))
        if with_frames:
            frames.append(Branch(path, f, keys))
    result = {'P': DataTree(tuple(points)), 'T': DataTree(tuple(tangents)), 't': DataTree(tuple(parameters)),
              'Count': pending if values is None else sum(len(b.items) for b in points)}
    if with_frames:
        return {'F': DataTree(tuple(frames)), **result}
    return result


def evaluate_containment(state, trees, detail):
    layout = tuple(aligned(*matched_inputs([trees['P'], trees['C']])))
    sources, indices, rows = [], {}, []
    for _, matches in layout:
        branch = []
        for (point, curve), _ in matches:
            if curve not in indices:
                indices[curve] = len(sources)
                sources.append(curve.to_wire())
            branch.append((indices[curve], point.xyz))
        rows.append(branch)
    plan = {'operation': POINT_IN_CURVE, 'sources': sources, 'rows': rows}
    signature = request_signature(plan)
    request = bool(sources) and detail.get('signature') != signature
    pending = PendingGeometry('Waiting for point containment')
    if not sources:
        values = [() for _ in rows]
    elif request:
        values = [(pending,) * len(row) for row in rows]
    else:
        if detail.get('error'):
            raise ValueError(detail['error'])
        values = detail['values']
        if len(values) != len(rows) or any(len(a) != len(b) for a, b in zip(values, rows)):
            raise ValueError('Point In Curve returned incomplete classifications.')
    relations, inside = [], []
    for (path, matches), row in zip(layout, values):
        keys = tuple(provenance[0] for _, provenance in matches)
        relations.append(Branch(path, row, keys))
        inside.append(Branch(path, tuple(pending if request else value == 2 for value in row), keys))
    outputs = {'R': DataTree(tuple(relations)), 'I': DataTree(tuple(inside))}
    if request:
        outputs['_sampling'] = {**{key: state[key] for key in ('project_uuid', 'node_uuid')},
                                'signature': signature, 'plan': plan}
    return outputs


def _closest_samples(state, queries, detail):
    name = SAMPLING_SPECS[state['primitive']]['name']
    sources, indices, rows = [], {}, []
    if sum(map(len, queries)) > MAX_SAMPLES:
        raise ValueError(f'{name} supports up to {MAX_SAMPLES:,} queries.')
    for matches in queries:
        branch = []
        for point, curve, normalized in matches:
            if curve not in indices:
                indices[curve] = len(sources)
                sources.append(curve.to_wire())
            branch.append((indices[curve], point.xyz, normalized))
        rows.append(branch)
    plan = {'operation': CLOSEST_POINT, 'sources': sources, 'rows': rows}
    signature = request_signature(plan)
    waiting = bool(sources) and detail.get('signature') != signature
    pending = PendingGeometry('Waiting for native curve projection')
    if waiting or not sources:
        results = [(pending,) * len(row) for row in rows]
    else:
        if detail.get('error'):
            raise ValueError(detail['error'])
        results = detail['values']
        if len(results) != len(rows) or any(len(a) != len(b) for a, b in zip(results, rows)):
            raise ValueError(f'{name} returned incomplete results.')
    request = None
    if waiting:
        request = {**{key: state[key] for key in ('project_uuid', 'node_uuid')},
                   'signature': signature, 'plan': plan}
    return results, request


def evaluate_closest(state, trees, detail):
    layout = tuple(aligned(*matched_inputs([trees['P'], trees['C'], trees['N']])))
    queries = [tuple(items for items, _ in matches) for _, matches in layout]
    results, request = _closest_samples(state, queries, detail)
    outputs = {port: [] for port in ('P', 't', 'D')}
    for (path, matches), result in zip(layout, results):
        keys = tuple(f'{path}:{i}:{provenance[0]}' for i, (_, provenance) in enumerate(matches))
        if request:
            columns = (result,) * 3
        else:
            columns = (tuple(PointValue(key, xyz(sample[:3])) for key, sample in zip(keys, result)),
                       tuple(sample[3] for sample in result), tuple(sample[4] for sample in result))
        for port, values in zip(outputs, columns):
            outputs[port].append(Branch(path, values, keys))
    result = {port: DataTree(tuple(branches)) for port, branches in outputs.items()}
    if request:
        result['_sampling'] = request
    return result


def evaluate_sort_along_curve(state, trees, detail):
    layout, queries = [], []
    count = 0
    for path, (points, curves) in _list_branches(trees['P'], trees['C']):
        if points.items and len(curves.items) != 1:
            raise ValueError('Connect one guide curve per point branch, or Graft the curves.')
        count += len(points.items)
        if count > MAX_SAMPLES:
            raise ValueError(f'Sort Along Curve supports up to {MAX_SAMPLES:,} queries.')
        layout.append((path, points))
        queries.append(tuple((point, curves.items[0], False) for point in points.items))
    samples, request = _closest_samples(state, queries, detail)
    outputs = {port: [] for port in ('P', 'I', 't')}
    for (path, points), row in zip(layout, samples):
        if request:
            keys = points.keys
            columns = (row,) * 3
        else:
            indices = tuple(sorted(range(len(row)), key=lambda i: row[i][3]))
            keys = tuple(points.keys[i] for i in indices)
            columns = (tuple(points.items[i] for i in indices), indices, tuple(row[i][3] for i in indices))
        for port, values in zip(outputs, columns):
            outputs[port].append(Branch(path, values, keys))
    result = {port: DataTree(tuple(branches)) for port, branches in outputs.items()}
    if request:
        result['_sampling'] = request
    return result
