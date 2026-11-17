"""List and Boolean operations over typed data, independent of Qt and OCC."""
from dataclasses import replace
import hashlib
from heapq import nsmallest
from itertools import product
import math
from operator import itemgetter
from reprlib import repr as short_repr

from .arithmetic import finite_number
from .curves import CurveInput, input_tree
from .datatree import (Branch, DataTree, MAX_BRANCHES, MAX_ITEMS, as_tree, finite,
                       flip_matrix, simplify, tree_diagnostics)
from .point import PointValue
from .table_data import choice_entries, read_csv


CROSS_REFERENCE_MODES = {
    'holistic': 'Holistic',
    'diagonal': 'Diagonal',
    'coincident': 'Coincident',
    'upper': 'Upper',
    'upper_strict': 'Upper Strict',
    'lower': 'Lower',
    'lower_strict': 'Lower Strict',
}
POINT_SORT_ORDERS = ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX')

LIST_SPECS = {
    'bool': {'class': 'BoolNode', 'name': 'Bool', 'inputs': (
        CurveInput('V', 'Value', 'bool_cast', True),), 'outputs': ('B',)},
    'merge': {'class': 'MergeNode', 'name': 'Merge', 'inputs': tuple(
        CurveInput(port, f'Data {port}', 'items', optional=True) for port in 'ABCD'), 'outputs': ('D',)},
    'list_item': {'class': 'ListItemNode', 'name': 'List Item', 'inputs': (
        CurveInput('L', 'List', 'items'), CurveInput('I', 'Index', 'list_index', 0)), 'outputs': ('I',)},
    'shift_list': {'class': 'ShiftListNode', 'name': 'Shift List', 'inputs': (
        CurveInput('L', 'List', 'items'), CurveInput('S', 'Shift', 'list_index', 1),
        CurveInput('W', 'Wrap', 'boolean', True)), 'outputs': ('L',)},
    'cross_reference': {'class': 'CrossReferenceNode', 'name': 'Cross Reference', 'inputs': (
        CurveInput('A', 'List A', 'items'), CurveInput('B', 'List B', 'items')), 'outputs': ('A', 'B')},
    'simplify': {'class': 'SimplifyNode', 'name': 'Simplify', 'inputs': (
        CurveInput('D', 'Data Tree', 'items'),), 'outputs': ('T', 'B', 'N')},
    'flip_matrix': {'class': 'FlipMatrixNode', 'name': 'Flip Matrix', 'inputs': (
        CurveInput('D', 'Data Tree', 'items'),), 'outputs': ('T', 'B', 'N')},
    'list_length': {'class': 'ListLengthNode', 'name': 'List Length', 'inputs': (
        CurveInput('L', 'List', 'items'),), 'outputs': ('L', 'T', 'B')},
    'sort_list': {'class': 'SortListNode', 'name': 'Sort List', 'inputs': (
        CurveInput('K', 'Sort Keys', 'items'),
        CurveInput('A', 'Values to Reorder', 'items', optional=True)), 'outputs': ('K', 'A')},
    'sort_points': {'class': 'SortPointsNode', 'name': 'Sort Points', 'inputs': (
        CurveInput('P', 'Points', 'points'),), 'outputs': ('P', 'I')},
    'tree_branch': {'class': 'TreeBranchNode', 'name': 'Tree Branch', 'inputs': (
        CurveInput('T', 'Data Tree', 'items'), CurveInput('P', 'Paths', 'path_text', '{0}')), 'outputs': ('B',)},
    'replace_paths': {'class': 'ReplacePathsNode', 'name': 'Replace Paths', 'inputs': (
        CurveInput('T', 'Data Tree', 'items'), CurveInput('S', 'Source Paths', 'path_text', ''),
        CurveInput('P', 'New Paths', 'path_text', '{0}')), 'outputs': ('T',)},
    'text': {'class': 'TextNode', 'name': 'Text', 'inputs': (
        CurveInput('T', 'Text', 'text', ''),), 'outputs': ('T',)},
    'value_list': {'class': 'ValueListNode', 'name': 'Value List', 'inputs': (), 'outputs': ('V',)},
    'read_csv': {'class': 'ReadCsvNode', 'name': 'Read CSV', 'inputs': (
        CurveInput('P', 'File Path', 'text', ''),
        CurveInput('D', 'Delimiter', 'choice_index', 0, ('Comma', 'Semicolon', 'Tab')),
        CurveInput('H', 'First Row Is Header', 'boolean', True),
        CurveInput('N', 'Parse Numbers', 'boolean', False)), 'outputs': ('R', 'H', 'N')},
    'duplicate_data': {'class': 'DuplicateDataNode', 'name': 'Duplicate Data', 'inputs': (
        CurveInput('D', 'Data', 'items'), CurveInput('N', 'Number of Copies', 'grid_count', 2),
        CurveInput('O', 'Retain List Order', 'boolean', True)), 'outputs': ('D',)},
    'dispatch': {'class': 'DispatchNode', 'name': 'Dispatch', 'inputs': (
        CurveInput('L', 'List', 'items'),
        CurveInput('P', 'Boolean Pattern', 'bool_cast', optional=True)), 'outputs': ('A', 'B')},
    'weave': {'class': 'WeaveNode', 'name': 'Weave', 'inputs': (
        CurveInput('P', 'Stream Pattern', 'weave_index', optional=True),
        CurveInput('0', 'Stream 0', 'items', optional=True),
        CurveInput('1', 'Stream 1', 'items', optional=True)), 'outputs': ('W',)},
    'tree_viewer': {'class': 'TreeViewerNode', 'name': 'Tree Viewer', 'inputs': (
        CurveInput('D', 'Data Tree', 'items', optional=True),), 'outputs': ('V', 'P', 'B', 'N')},
    'cull_duplicate_points': {'class': 'CullDuplicatePointsNode', 'name': 'Cull Duplicate Points', 'inputs': (
        CurveInput('P', 'Points', 'points'), CurveInput('T', 'Tolerance', 'number', .001)), 'outputs': ('P', 'I')},
    'closest_points': {'class': 'ClosestPointsNode', 'name': 'Closest Points', 'inputs': (
        CurveInput('P', 'Query Points', 'points'), CurveInput('C', 'Candidate Points', 'points'),
        CurveInput('N', 'Count', 'list_index', 1)), 'outputs': ('P', 'I', 'D')},
}
for operation, spec in LIST_SPECS.items():
    spec.update(category='Inputs' if operation in ('bool', 'text', 'value_list') else 'Data', reference=False)
PASS_LIST_BINDINGS = frozenset((
    'merge', 'list_item', 'shift_list', 'cross_reference', 'simplify', 'flip_matrix', 'dispatch', 'weave',
    'cull_duplicate_points', 'closest_points', 'sort_list', 'sort_points', 'tree_branch', 'replace_paths',
))


def _rekey(value, key):
    from .moves import GridEditValue

    if isinstance(value, GridEditValue):
        return replace(value, key=key, source=replace(value.source, key=key))
    return replace(value, key=key)


def bool_value(value):
    if type(value) is bool:
        return value
    if type(value) in (int, float):
        return finite_number(value) != 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ('true', 'yes', 'on', '1'):
            return True
        if token in ('false', 'no', 'off', '0', ''):
            return False
    raise ValueError('Bool requires a Boolean, a finite Number, or text such as true or false.')


def list_index(value):
    value = finite(value)
    if int(value) != value:
        raise ValueError('Expected an integer.')
    return int(value)


def _merge(trees, bindings):
    from .moves import is_geometry

    groups, result_bindings = {}, {}
    total = 0
    for port, tree in trees.items():
        source_bindings = bindings.get(port, {})
        total += tree.count
        if total > MAX_ITEMS:
            raise ValueError(f'Merge exceeds the {MAX_ITEMS:,} item limit.')
        for branch in tree.branches:
            items, keys = groups.setdefault(branch.path, ([], []))
            for value, key in zip(branch.items, branch.keys):
                if is_geometry(value):
                    old_key = value.key
                    # Different owners may publish the same local geometry key.
                    # Scope only this forwarded value; the binding keeps the source key.
                    merged_key = hashlib.sha256(f'{port}:{old_key}'.encode()).hexdigest()[:24]
                    value = _rekey(value, merged_key)
                    if old_key in source_bindings:
                        result_bindings[merged_key] = source_bindings[old_key]
                    key = merged_key
                else:
                    key = hashlib.sha256(f'{port}:{key}'.encode()).hexdigest()[:24]
                items.append(value)
                keys.append(key)
    return DataTree(tuple(Branch(path, items, keys) for path, (items, keys) in groups.items())), result_bindings


def _select(source, indices):
    if not source.branches or not indices.branches:
        return DataTree(())
    left = {b.path: b for b in source.branches}
    right = {b.path: b for b in indices.branches}
    if len(left) > 1 and len(right) > 1 and left.keys() != right.keys():
        raise ValueError('List and Index tree paths must match, or one input must have a single branch.')
    paths = right if len(right) > len(left) else left
    if len(left) == len(right) == 1:
        path = indices.branches[0].path
        current = source.branches[0].path
        if len(path) > len(current) or current == (0,):
            paths = right
    branches = []
    total = 0
    for path in paths:
        branch = left.get(path, source.branches[0])
        index_branch = right.get(path, indices.branches[0])
        items, keys = [], []
        if branch.items:
            total += len(index_branch.items)
            if total > MAX_ITEMS:
                raise ValueError(f'List Item exceeds the {MAX_ITEMS:,} item limit.')
            for index in index_branch.items:
                if not -len(branch.items) <= index < len(branch.items):
                    label = ';'.join(map(str, path))
                    raise ValueError(f'Index {index} is out of range in branch {{{label}}} with {len(branch.items)} item(s).')
                items.append(branch.items[index])
                keys.append(branch.keys[index])
        branches.append(Branch(path, items, keys))
    return DataTree(tuple(branches))


def _list_branches(*trees):
    indexed = [{b.path: b for b in tree.branches} for tree in trees]
    multi = [paths for paths in indexed if len(paths) > 1]
    paths = multi[0] if multi else max(indexed, key=lambda p: (
        len(next(iter(p))), next(iter(p)) != (0,)) if p else (-1, False))
    if any(p.keys() != paths.keys() for p in multi):
        raise ValueError('Match DataTree paths or connect a single shared branch.')
    singletons = [next(iter(p.values()), None) for p in indexed]
    for path in paths:
        empty = Branch(path, ())
        yield path, tuple(p.get(path, first or empty) for p, first in zip(indexed, singletons))


def _sort_list(trees, bindings):
    from .moves import is_geometry

    paired = 'A' in trees
    groups = _list_branches(trees['K'], trees['A']) if paired else _list_branches(trees['K'])
    keys, values = [], []
    for path, branches in groups:
        key_branch = branches[0]
        items = key_branch.items
        if all(type(item) in (int, float) for item in items):
            for item in items:
                finite_number(item)
        elif not all(isinstance(item, str) for item in items):
            raise ValueError('Sort List keys must be all numbers or all text within each branch.')
        if paired and len(branches[1].items) != len(items):
            path_label = ';'.join(map(str, path))
            raise ValueError(f'Sort List needs equally many keys and values in branch {{{path_label}}}.')
        order = sorted(range(len(items)), key=items.__getitem__)
        keys.append(Branch(path, tuple(items[i] for i in order), tuple(key_branch.keys[i] for i in order)))
        if paired:
            branch = branches[1]
            values.append(Branch(path, tuple(branch.items[i] for i in order), tuple(branch.keys[i] for i in order)))
        else:
            values.append(Branch(path, ()))
    tree = DataTree(tuple(values))
    incoming = bindings.get('A', {})
    inherited = {value.key: incoming[value.key] for value in tree.values()
                 if is_geometry(value) and value.key in incoming}
    return {'K': DataTree(tuple(keys)), 'A': tree}, {'A': inherited}


def _path_operation(operation, trees):
    source = {branch.path: branch for branch in trees['T'].branches}
    targets = trees['P'].values()
    if operation == 'tree_branch':
        branches = []
        for path in dict.fromkeys(targets):
            if path not in source:
                raise ValueError(f'No branch at path {{{";".join(map(str, path))}}}.')
            branches.append(source[path])
        return 'B', DataTree(tuple(branches))

    raw = trees['S'].values()
    origins = tuple(source) if raw == ('',) else raw
    if len(origins) != len(targets) or len(set(origins)) != len(origins):
        raise ValueError('Replace Paths needs one new path for each distinct source path.')
    if any(path not in source for path in origins):
        raise ValueError('Replace Paths contains a source path absent from the tree.')
    mapping = dict(zip(origins, targets))
    groups = {}
    for path, branch in source.items():
        items, keys = groups.setdefault(mapping.get(path, path), ([], []))
        items.extend(branch.items)
        keys.extend(branch.keys)
    return 'T', DataTree(tuple(Branch(path, items, keys) for path, (items, keys) in groups.items()))


_NEIGHBOR_CELLS = tuple(product((-1, 0, 1), repeat=3))


def _unique_indices(points, tolerance):
    if tolerance == 0:
        first = {}
        for index, point in enumerate(points):
            first.setdefault(point.xyz, index)
        return tuple(first.values())

    numerator, denominator = tolerance.as_integer_ratio()
    cells, kept = {}, []
    for index, point in enumerate(points):
        # Exact cell coordinates also work when coordinate / tolerance would overflow.
        x, y, z = (a * denominator // (b * numerator)
                   for a, b in (value.as_integer_ratio() for value in point.xyz))
        if any(math.dist(point.xyz, candidate) <= tolerance
               for dx, dy, dz in _NEIGHBOR_CELLS
               for candidate in cells.get((x + dx, y + dy, z + dz), ())):
            continue
        cells.setdefault((x, y, z), []).append(point.xyz)
        kept.append(index)
    return tuple(kept)


def _point_columns(rows, ports, incoming):
    columns = {port: [] for port in ports}
    inherited = {}
    for path, source, indices, *extra in rows:
        values = tuple(source.items[i] for i in indices)
        keys = tuple(source.keys[i] for i in indices)
        for port, items in zip(ports, (values, indices, *extra)):
            columns[port].append(Branch(path, items, keys))
        inherited.update((p.key, incoming[p.key]) for p in values if p.key in incoming)
    return {port: DataTree(tuple(branches)) for port, branches in columns.items()}, {'P': inherited}


def _cull_duplicate_points(trees, bindings):
    def rows():
        total = 0
        for path, (points, tolerances) in _list_branches(trees['P'], trees['T']):
            if not points.items:
                yield path, points, ()
                continue
            if len(tolerances.items) != 1 or tolerances.items[0] < 0:
                raise ValueError('Use one nonnegative tolerance per point branch.')
            total += len(points.items)
            if total > MAX_ITEMS:
                raise ValueError(f'Cull Duplicate Points exceeds {MAX_ITEMS:,} matched points.')
            yield path, points, _unique_indices(points.items, tolerances.items[0])

    return _point_columns(rows(), ('P', 'I'), bindings.get('P', {}))


def _sort_points(tree, incoming, axis_order):
    coordinates = itemgetter(*map('XYZ'.index, axis_order))

    def rows():
        for branch in tree.branches:
            order = tuple(sorted(range(len(branch.items)), key=lambda index: coordinates(branch.items[index].xyz)))
            yield branch.path, branch, order

    return _point_columns(rows(), ('P', 'I'), incoming)


def _closest_points(trees, bindings):
    from .pull import MAX_COMPARISONS

    matches = tuple(_list_branches(trees['P'], trees['C'], trees['N']))
    split = any(len(query.items) > 1 and len(counts.items) == 1 and counts.items[0] > 1
                for _, (query, _, counts) in matches)
    if split and sum(max(1, len(query.items)) for _, (query, _, _) in matches) > MAX_BRANCHES:
        raise ValueError(f'Closest Points exceeds {MAX_BRANCHES:,} query branches.')

    def rows():
        comparisons = total = 0
        for path, (query, cloud, counts) in matches:
            if not query.items:
                yield path + ((0,) if split else ()), cloud, (), ()
                continue
            if len(counts.items) != 1 or counts.items[0] < 1:
                raise ValueError('Use one positive neighbor count per query branch.')
            count = min(counts.items[0], len(cloud.items))
            comparisons += len(query.items) * len(cloud.items)
            total += len(query.items) * count
            if comparisons > MAX_COMPARISONS or total > MAX_ITEMS:
                raise ValueError(f'Closest Points exceeds {MAX_COMPARISONS:,} comparisons or {MAX_ITEMS:,} results.')
            groups = ((point,) for point in query.items) if split else (query.items,)
            for index, group in enumerate(groups):
                neighbors = [pair for point in group
                             for pair in nsmallest(count, ((math.dist(point.xyz, p.xyz), i)
                                                         for i, p in enumerate(cloud.items)))] if count else ()
                distances, indices = zip(*neighbors) if neighbors else ((), ())
                yield path + ((index,) if split else ()), cloud, indices, distances

    return _point_columns(rows(), ('P', 'I', 'D'), bindings.get('C', {}))


def _duplicate_data(trees):
    branches, total = [], 0
    for path, (data, count, order) in _list_branches(trees['D'], trees['N'], trees['O']):
        if not data.items or not count.items or not order.items:
            branches.append(Branch(path, ()))
            continue
        if len(count.items) != 1 or len(order.items) != 1:
            raise ValueError('Duplicate Data needs one count and one order setting per branch.')
        copies = count.items[0]
        total += len(data.items) * copies
        if total > MAX_ITEMS:
            raise ValueError(f'Duplicate Data exceeds the {MAX_ITEMS:,}-item limit.')
        slots = ((i, j) for j in range(copies) for i in range(len(data.items))) if order.items[0] else (
            (i, j) for i in range(len(data.items)) for j in range(copies))
        values, keys = [], []
        for i, j in slots:
            values.append(data.items[i])
            keys.append(f'{data.keys[i]}:{i}:{j}')
        branches.append(Branch(path, values, keys))
    return {'D': DataTree(tuple(branches))}, {}


def _shift_list(trees):
    branches, total = [], 0
    for path, (source, shift, wrap) in _list_branches(trees['L'], trees['S'], trees['W']):
        if not source.items or not shift.items or not wrap.items:
            branches.append(Branch(path, ()))
            continue
        if len(shift.items) != 1 or len(wrap.items) != 1:
            raise ValueError('Shift List needs one shift and one wrap setting per branch.')
        count = len(source.items)
        offset = shift.items[0]
        if wrap.items[0]:
            start, stop = offset % count, count
            total += count
        else:
            start, stop = min(count, max(0, offset)), max(0, count + min(0, offset))
            total += stop - start
        if total > MAX_ITEMS:
            raise ValueError(f'Shift List exceeds the {MAX_ITEMS:,}-item limit.')
        items, keys = source.items[start:stop], source.keys[start:stop]
        if wrap.items[0]:
            items += source.items[:start]
            keys += source.keys[:start]
        branches.append(Branch(path, items, keys))
    return DataTree(tuple(branches))


def _cross_columns(pairing, i, width):
    if pairing in ('diagonal', 'coincident'):
        # With two lists both modes exclude equal indices.
        return range(min(i, width)), range(i + 1, width)
    if pairing in ('upper', 'upper_strict'):
        return (range(i + (pairing == 'upper_strict'), width),)
    if pairing in ('lower', 'lower_strict'):
        return (range(min(i + (pairing == 'lower'), width)),)
    return (range(width),)


def _cross_reference(trees, bindings, pairing):
    from .moves import is_geometry

    left, right, total = [], [], 0
    for path, (a, b) in _list_branches(trees['A'], trees['B']):
        width = len(b.items)
        if not width or not a.items:
            empty = Branch(path, ())
            left.append(empty)
            right.append(empty)
            continue
        a_items, b_items, a_keys, b_keys = [], [], [], []
        prefix = '.'.join(map(str, path))
        height = min(len(a.items), width) if pairing in ('upper', 'upper_strict') else len(a.items)
        for i in range(height):
            for columns in _cross_columns(pairing, i, width):
                total += len(columns)
                if total > MAX_ITEMS:
                    raise ValueError(f'Cross Reference exceeds the {MAX_ITEMS:,}-pair limit.')
                for j in columns:
                    a_items.append(a.items[i])
                    b_items.append(b.items[j])
                    pair = f'{prefix}:{i}:{j}'
                    a_keys.append(f'{pair}:{a.keys[i]}')
                    b_keys.append(f'{pair}:{b.keys[j]}')
        left.append(Branch(path, a_items, a_keys))
        right.append(Branch(path, b_items, b_keys))
    outputs = {'A': DataTree(tuple(left)), 'B': DataTree(tuple(right))}
    inherited = {}
    for port, tree in outputs.items():
        incoming = bindings.get(port, {})
        inherited[port] = {value.key: incoming[value.key] for value in tree.values()
                           if is_geometry(value) and value.key in incoming}
    return outputs, inherited


def _dispatch(trees, bindings):
    from .moves import is_geometry

    outputs = {'A': [], 'B': []}
    for path, (source, pattern) in _list_branches(trees['L'], trees.get('P', as_tree([True, False]))):
        if source.items and not pattern.items:
            raise ValueError('Dispatch needs a nonempty Boolean pattern.')
        groups = {'A': ([], []), 'B': ([], [])}
        for i, (value, key) in enumerate(zip(source.items, source.keys)):
            items, keys = groups['A' if pattern.items[i % len(pattern.items)] else 'B']
            items.append(value)
            keys.append(key)
        for port, (items, keys) in groups.items():
            outputs[port].append(Branch(path, items, keys))
    trees = {p: DataTree(tuple(b)) for p, b in outputs.items()}
    incoming = bindings.get('L', {})
    inherited = {port: {value.key: incoming[value.key] for value in tree.values()
                        if is_geometry(value) and value.key in incoming}
                 for port, tree in trees.items()}
    return trees, inherited


def _weave(trees, bindings):
    from .moves import is_geometry

    empty = DataTree(())
    branches, inherited, total = [], {}, 0
    left, right = trees.get('0', empty), trees.get('1', empty)
    owners = [bindings.get(port, {}) for port in ('0', '1')]
    for path, (a, b, pattern) in _list_branches(left, right, trees.get('P', as_tree([0, 1]))):
        if any(index not in (0, 1) for index in pattern.items) or (not pattern.items and (a.items or b.items)):
            raise ValueError('Weave needs a nonempty pattern of stream numbers 0 and 1.')
        streams = a, b
        remaining = [len(stream.items) for stream in streams]
        active = tuple(i for i in pattern.items if remaining[i])
        total += sum(remaining[i] for i in set(active))
        if total > MAX_ITEMS:
            raise ValueError(f'Weave exceeds the {MAX_ITEMS:,}-item limit.')
        cursor = 0
        values, keys = [], []
        while active:
            port = active[cursor]
            stream = streams[port]
            index = len(stream.items) - remaining[port]
            value = stream.items[index]
            if is_geometry(value):
                binding = owners[port].get(value.key)
                if binding is not None:
                    key = hashlib.sha256(f'{port}:{value.key}'.encode()).hexdigest()[:24]
                    value = _rekey(value, key)
                    inherited[value.key] = binding
            values.append(value)
            keys.append(f'{port}:{stream.keys[index]}:{index}')
            remaining[port] -= 1
            cursor = (cursor + 1) % len(active)
            if not remaining[port]:
                active = tuple(i for i in active if remaining[i])
                cursor = 0
        branches.append(Branch(path, values, keys))
    return {'W': DataTree(tuple(branches))}, {'W': inherited}


def _tree_preview(tree):
    branch_limit, item_limit = 24, 6
    lines = [f'{tree.count} item(s) · {len(tree.branches)} branch(es)']
    for branch in tree.branches[:branch_limit]:
        path = ';'.join(map(str, branch.path))
        items = []
        for value in branch.items[:item_limit]:
            if isinstance(value, PointValue):
                items.append(short_repr(value.xyz))
            elif getattr(value, 'kind', None) and hasattr(value, 'key'):
                items.append(value.kind.replace('_', ' ').title())
            else:
                items.append(short_repr(value))
        remaining = len(branch.items) - len(items)
        if remaining:
            items.append(f'… {remaining} more')
        lines.append(f"{{{path}}}: {', '.join(items) or '(empty)'}")
    remaining = len(tree.branches) - branch_limit
    if remaining > 0:
        lines.append(f'… {remaining} more branch(es)')
    return '\n'.join(lines)


def evaluate_list(operation, state, inputs, bindings=None, *, graph_directory=None):
    from .moves import is_geometry

    for d in LIST_SPECS[operation]['inputs']:
        if d.default is None and not d.optional and d.port not in inputs:
            raise ValueError('Connect input ' + d.port + '.')
    trees = {d.port: input_tree(inputs[d.port] if d.port in inputs else state['parameters'][d.port],
                              d, state['tree_modes'].get(d.port, 'none'))
             for d in LIST_SPECS[operation]['inputs'] if d.port in inputs or d.default is not None}
    bindings = bindings or {}
    if operation == 'text':
        tree = trees['T']
        return {'T': tree if 'T' in inputs or state['tree_modes'] else tree.values()[0]}, {}
    if operation == 'value_list':
        parameters = state['parameters']
        return {'V': choice_entries(parameters['options'])[parameters['selection']][1]}, {}
    if operation == 'read_csv':
        return read_csv(trees, graph_directory), {}
    if operation == 'bool':
        tree = trees['V']
        value = inputs.get('V', state['parameters']['V'])
        return {'B': tree if isinstance(value, (DataTree, list, tuple)) or state['tree_modes'] else tree.values()[0]}, {}
    if operation == 'merge':
        tree, inherited = _merge(trees, bindings)
        return {'D': tree}, {'D': inherited}
    if operation == 'duplicate_data':
        return _duplicate_data(trees)
    if operation == 'cross_reference':
        return _cross_reference(trees, bindings, state['parameters']['pairing'])
    if operation == 'cull_duplicate_points':
        return _cull_duplicate_points(trees, bindings)
    if operation == 'closest_points':
        return _closest_points(trees, bindings)
    if operation == 'dispatch':
        return _dispatch(trees, bindings)
    if operation == 'weave':
        return _weave(trees, bindings)
    if operation == 'sort_list':
        return _sort_list(trees, bindings)
    if operation == 'sort_points':
        return _sort_points(trees['P'], bindings.get('P', {}), state['parameters']['axis_order'])
    if operation in ('tree_branch', 'replace_paths'):
        port, tree = _path_operation(operation, trees)
        incoming = bindings.get('T', {})
        inherited = {value.key: incoming[value.key] for value in tree.values()
                     if is_geometry(value) and value.key in incoming}
        return {port: tree}, {port: inherited}
    if operation in ('list_item', 'shift_list'):
        port = 'I' if operation == 'list_item' else 'L'
        tree = _select(trees['L'], trees['I']) if operation == 'list_item' else _shift_list(trees)
        incoming = bindings.get('L', {})
        inherited = {v.key: incoming[v.key] for v in tree.values() if is_geometry(v) and v.key in incoming}
        return {port: tree}, {port: inherited}
    if operation in ('simplify', 'flip_matrix'):
        transform = simplify if operation == 'simplify' else flip_matrix
        tree = transform(trees['D'])
        return {'T': tree, 'B': len(tree.branches), 'N': tree.count}, {'T': bindings.get('D', {})}
    if operation == 'tree_viewer':
        tree = trees.get('D')
        preview = _tree_preview(tree) if tree is not None else 'No data connected.'
        return {'V': preview, **tree_diagnostics(tree if tree is not None else DataTree(()))}, {}
    tree = trees['L']
    lengths = DataTree(tuple(Branch(b.path, (len(b.items),)) for b in tree.branches))
    return {'L': lengths, 'T': tree.count, 'B': len(tree.branches)}, {}
