"""DataTree planning and serializable edge selection for Fillet Edge."""
import hashlib
import json

from .curves import xyz
from .datatree import Branch, aligned


FILLET_EDGE = 'fillet_edge'
MAX_PICKS = 256
MAX_SLOTS = 300
SAMPLE_COUNT = 5


def capture_target(binding):
    if binding is None or binding.selectors:
        return None
    return {'project_uuid': binding.project, 'node_uuid': binding.source_uuid,
            'reference': bool(binding.reference_id), 'key': binding.part}


def target_key(target):
    return hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()


def inactive_ports(operation, parameters):
    if operation == FILLET_EDGE and parameters.get('fillet_mode', 'all') == 'all':
        return ('E',)
    return ()


def selection(value):
    """A topology count and five orientation-independent samples per picked edge."""
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError('Invalid saved edge selection.')
    count, edges = value
    if (type(count) is not int or not 1 <= count <= 10000 or not isinstance(edges, (tuple, list))
            or not 1 <= len(edges) <= min(count, MAX_PICKS)):
        raise ValueError('Invalid saved edge selection.')
    if any(not isinstance(samples, (tuple, list)) or len(samples) != SAMPLE_COUNT for samples in edges):
        raise ValueError('Invalid saved edge samples.')
    return count, tuple(tuple(xyz(p) for p in samples) for samples in edges)


def normalize_parameters(raw):
    mode = raw.get('fillet_mode', 'all')
    if mode not in ('all', 'selected'):
        raise ValueError('Choose All or Selected for Fillet Edge.')
    picks = raw.get('fillet_selection', {})
    if (not isinstance(picks, dict) or len(picks) > MAX_SLOTS
            or any(not isinstance(key, str) or len(key) != 64 for key in picks)):
        raise ValueError('Invalid saved Fillet Edge sources.')
    picks = {key: selection(value) for key, value in picks.items()}
    if sum(len(value[1]) for value in picks.values()) > 1000:
        raise ValueError('Too many saved edge picks.')
    return {'fillet_mode': mode, 'fillet_selection': picks}


def recipe_branches(state, trees, bindings, key):
    from .curves import matched_inputs
    from .operations import OperationValue

    selected = state['fillet_mode'] == 'selected'
    solids, radii = matched_inputs(trees[:2])
    rows = tuple(aligned(solids, radii))
    pick_branches = trees[2].branches if selected and len(trees) == 3 else ()
    picks_by_path = {branch.path: branch.items for branch in pick_branches}
    if selected and len(trees) == 3 and not picks_by_path and any(items for _, items in rows):
        raise ValueError('Connect one or more Edge Points.')
    if len(picks_by_path) > 1 and set(picks_by_path) != {path for path, _ in rows}:
        if len(rows) != 1 or len(rows[0][1]) != 1:
            raise ValueError('Edge Points need one shared branch or paths matching the solids.')
        rows = tuple((path, rows[0][1]) for path in picks_by_path)
    if sum(len(items) for _, items in rows) > MAX_SLOTS:
        raise ValueError('Fillet Edge supports up to 300 result slots.')
    widths = [{b.path: len(b.items) for b in tree.branches} for tree in (solids, radii)]
    for path, items in rows:
        if items and any(w.get(path, next(iter(w.values()), 0)) not in (1, len(items)) for w in widths):
            raise ValueError('Solid and Radius lists must have equal lengths or one item.')
        picks = picks_by_path.get(path, pick_branches[0].items if pick_branches else ())
        if picks_by_path and items and (not picks or len(items) > 1 and len(picks) not in (1, len(items))):
            raise ValueError('Use a list of Edge Points for one solid, or one point per solid in a shared branch.')
        values = []
        for index, ((source, radius), provenance) in enumerate(items):
            points, saved = (), None
            if picks_by_path:
                points = tuple(p.xyz for p in picks) if len(items) == 1 else (picks[min(index, len(picks) - 1)].xyz,)
            elif selected:
                target = capture_target(bindings.get('G', {}).get(source.key))
                saved = state['fillet_selection'].get(target_key(target)) if target else None
                if saved is None:
                    raise ValueError('Select edges on each connected solid in Serpentine and click Set Edges, or connect Edge Points.')
            values.append(OperationValue(key((path, *provenance)), FILLET_EDGE, (source,), radius=radius,
                                         fillet_points=points, fillet_selection=saved))
        yield Branch(path, tuple(values), tuple(v.key for v in values))
