"""Deferred C/S/T recipes for mapping curves by relative surface UV."""
from .curves import CurveInput, CurveValue, input_tree
from .datatree import Branch, DataTree
from .tessellation import MAX_CELLS, MAX_CONTOUR_VERTICES, MAX_VERTICES


MAP_SURFACE = 'map_surface'
MAP_SPEC = {'class': 'MapSurfaceNode', 'name': 'Map Surface', 'primary': 'C', 'inputs': (
    CurveInput('C', 'Curves to Map', 'curve'),
    CurveInput('S', 'Source Surface', 'geometry'),
    CurveInput('T', 'Target Surface', 'geometry')), 'outputs': ('C', 'Count')}


def is_polygon(value):
    return (isinstance(value, CurveValue) and value.kind == 'polyline' and value.closed
            and 3 <= len(value.points) <= MAX_CONTOUR_VERTICES and len(set(value.points)) == len(value.points))


def is_indexable(values):
    return all(map(is_polygon, values)) and len({p for value in values for p in value.points}) <= MAX_VERTICES


def evaluate(state, inputs, key):
    from .operations import OperationValue

    curves, source, target = [input_tree(inputs[d.port], d, state['tree_modes'].get(d.port, 'none'))
                              for d in MAP_SPEC['inputs']]
    indexed = is_indexable(curves.values())
    limit = MAX_CELLS if indexed else 1500
    if curves.count > limit:
        raise ValueError(f'Map Surface supports up to {limit} curves in this input.')
    paths = {b.path for b in curves.branches if b.items}
    def faces(tree):
        if not paths:
            return {}
        if tree.count == 1:
            return {path: tree.values() for path in paths}
        index = {b.path: b.items for b in tree.branches if b.items}
        if set(index) != paths:
            raise ValueError('Source/Target Surface needs one shared surface or matching curve paths.')
        return index
    sources, targets = faces(source), faces(target)
    branches, complexity, known_surfaces = [], 0, set()
    for branch in curves.branches:
        items = []
        if branch.items:
            pair = sources[branch.path], targets[branch.path]
            if any(len(v) not in (1, len(branch.items)) for v in pair):
                raise ValueError('Use one surface or one per curve on each branch.')
            for i, (curve, item_key) in enumerate(zip(branch.items, branch.keys)):
                a, b = (v[0] if len(v) == 1 else v[i] for v in pair)
                value = OperationValue(key((branch.path, item_key)), MAP_SURFACE, (curve, a, b))
                if indexed:
                    new_surfaces = {a,b} - known_surfaces
                    complexity += 2 + sum(getattr(s,'complexity',1) for s in new_surfaces)
                    known_surfaces.update(new_surfaces)
                else:
                    complexity += value.complexity
                if complexity > 10000:
                    raise ValueError('Map Surface exceeds the geometry recipe budget.')
                items.append(value)
        branches.append(Branch(branch.path, tuple(items), tuple(v.key for v in items)))
    return {'C': DataTree(tuple(branches)), 'Count': curves.count}
