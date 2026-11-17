"""Deferred operations for preparing curves before Loft and Sweep."""
import hashlib

from .arithmetic import finite_number
from .curve_sampling import CURVES, MAX_FRAME_PARAMETERS, NORMALIZED, _layout
from .curves import CurveInput, input_tree
from .datatree import Branch, DataTree, MAX_ITEMS
from .domain import DomainValue
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry


SHATTER, FLIP_CURVE, MOVE_SEAM = 'shatter', 'flip_curve', 'move_seam'
PROFILE_SPECS = {
    SHATTER: {'class': 'ShatterNode', 'name': 'Shatter', 'inputs': (
        CURVES, CurveInput('t', 'Split Parameters', 'number', .5), NORMALIZED), 'outputs': ('C', 'D')},
    FLIP_CURVE: {'class': 'FlipCurveNode', 'name': 'Flip Curve', 'inputs': (
        CURVES, CurveInput('G', 'Guide Curve', 'sample_curve', optional=True)), 'outputs': ('C', 'F')},
    MOVE_SEAM: {'class': 'MoveSeamNode', 'name': 'Move Seam', 'inputs': (
        CURVES, CurveInput('t', 'Seam Parameter', 'number', 0.), NORMALIZED), 'outputs': ('C', 'P')},
}


def profile_options(operation, options):
    if operation == FLIP_CURVE:
        if options is not None:
            raise ValueError('Flip Curve only accepts its optional guide.')
        return None
    if (not isinstance(options, (tuple, list)) or len(options) != 2 or type(options[0]) is not bool
            or not isinstance(options[1], (tuple, list))):
        raise ValueError('Invalid curve profile parameters.')
    values = tuple(map(finite_number, options[1]))
    if len(values) > MAX_FRAME_PARAMETERS or (operation == MOVE_SEAM and len(values) != 1):
        raise ValueError('Use one seam parameter or up to 512 split parameters per curve.')
    return options[0], values


def evaluate_profiles(operation, state, inputs, details):
    from .operations import OperationValue

    trees = {}
    for desc in PROFILE_SPECS[operation]['inputs']:
        port = desc.port
        if port in inputs or desc.default is not None:
            trees[port] = input_tree(inputs.get(port, state['parameters'].get(port)), desc,
                                     state['tree_modes'].get(port, 'none'), port not in inputs)
    cuts = trees.pop('t') if operation == SHATTER else DataTree(())
    layout, split = _layout(tuple(trees.values()), False, split_items=operation == SHATTER)
    by_path = {branch.path: branch.items for branch in cuts.branches}
    shared_cuts = cuts.branches[0].items if len(cuts.branches) == 1 else None
    sources, rows, groups = {}, [], []
    for path, entries in layout:
        query = []
        for slot, (source_key, curve, *options) in enumerate(entries):
            operands = (curve, *options) if operation == FLIP_CURVE else (curve,)
            if operation == SHATTER:
                params = shared_cuts if shared_cuts is not None else by_path.get(path)
                if params is None and split:
                    params = by_path.get(path[:-1])
                if params is None:
                    raise ValueError('Shatter needs one shared parameter list or matching paths.')
                profile = profile_options(operation, (options[0], params))
            elif operation == MOVE_SEAM:
                profile = profile_options(operation, (options[1], (options[0],)))
            else:
                profile = None
            key = hashlib.sha256(repr((path, source_key, slot)).encode()).hexdigest()[:24]
            query.append((key, operands, profile))
            rows.append({'indices': [sources.setdefault(source, len(sources)) for source in operands],
                         'profile': profile})
        groups.append((path, query))
    plan = {'operation': operation, 'sources': [source.to_wire() for source in sources], 'rows': rows}
    signature = request_signature(plan)
    ports = PROFILE_SPECS[operation]['outputs']
    if rows and details.get('signature') != signature:
        pending = PendingGeometry('Waiting for native curve profiles')
        tree = DataTree(tuple(Branch(path, (pending,) if query else ()) for path, query in groups))
        return {**dict.fromkeys(ports, tree), '_sampling': {'project_uuid': state['project_uuid'],
                'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan}}
    if rows and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native curve profile operation returned incomplete results.')
    values = iter(results)
    curves, secondary, budget = [], [], MAX_ITEMS
    for path, query in groups:
        parts, data, data_keys = [], [], []
        for key, operands, profile in query:
            result = next(values)
            fragment_keys = []
            for i, kind in enumerate(result['kinds']):
                fragment_key = f'{key}:{i}'
                span = (False, result['meta'][i]) if operation == SHATTER else profile
                part = OperationValue(fragment_key, operation, operands, piece_index=0, result_kind=kind, profile=span)
                budget -= part.complexity
                if budget < 0:
                    raise ValueError('Curve profiles exceed the 10,000-item recipe budget.')
                parts.append(part)
                fragment_keys.append(fragment_key)
            if operation == SHATTER:
                data.extend(DomainValue(*span) for span in result['meta'])
                data_keys.extend(fragment_keys)
            else:
                data.append(PointValue(key, tuple(result['meta'])) if operation == MOVE_SEAM else result['meta'])
                data_keys.append(key)
        curves.append(Branch(path, tuple(parts), tuple(part.key for part in parts)))
        secondary.append(Branch(path, tuple(data), tuple(data_keys)))
    return {'C': DataTree(tuple(curves)), ports[1]: DataTree(tuple(secondary))}
