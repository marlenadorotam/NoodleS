"""Shared DataTree planning for the two curve Fillet nodes."""
from .curves import CurveInput, input_tree, matched_inputs
from .datatree import Branch, DataTree, aligned, finite
from .fillet_edges import capture_target


FILLET = 'fillet'
FILLET_PARAMETRIC = 'fillet_parametric'
FILLET_INPUTS = (
    CurveInput('A', 'Curve 1', 'curve'),
    CurveInput('B', 'Curve 2', 'curve'),
    CurveInput('N', 'Near Corner', 'point'),
    CurveInput('R', 'Fillet Radius', 'number', 1.),
)


def checked_radius(value):
    radius = finite(value)
    if radius <= 0:
        raise ValueError('Fillet Radius must be positive.')
    return radius


def settings(parameters, inputs, *, controls_only=False):
    descriptors = FILLET_INPUTS[2:] if controls_only else FILLET_INPUTS
    return [input_tree(inputs.get(d.port, parameters['parameters'].get(d.port, d.default)), d,
                       parameters['tree_modes'].get(d.port, 'none'), d.port not in inputs)
            for d in descriptors]


def slots(trees):
    trees = matched_inputs(trees)
    widths = [{branch.path: len(branch.items) for branch in tree.branches} for tree in trees]
    for path, rows in aligned(*trees):
        if rows and any(width.get(path, next(iter(width.values()), 0)) not in (1, len(rows)) for width in widths):
            raise ValueError('Fillet lists must have equal lengths or one item. Match the DataTree explicitly.')
        yield path, rows


def native_plan(parameters, inputs, bindings, records):
    if records:
        # Match fresh controls to the existing result slots, using the same
        # paths even when the original curves are no longer in the scene.
        groups = {}
        for record in records:
            groups.setdefault(tuple(record['path']), []).append(record)
        existing = DataTree(tuple(Branch(path, tuple(group)) for path, group in groups.items()))
        rows = []
        for path, items in slots([existing, *settings(parameters, inputs, controls_only=True)]):
            for (record, near, radius), _ in items:
                if path != tuple(record['path']):
                    raise ValueError('Update must keep the original Fillet result paths.')
                rows.append({'path': list(path), 'key': record['recipe']['key'],
                             'corner': list(near.xyz), 'radius': checked_radius(radius)})
        if [row['key'] for row in rows] != [record['recipe']['key'] for record in records]:
            raise ValueError('Update must keep the original Fillet result slots.')
        if all(row['corner'] == record['corner'] and row['radius'] == record['radius']
               for row, record in zip(rows, records)):
            return None
    else:
        rows = []
        for path, items in slots(settings(parameters, inputs)):
            for (a, b, near, radius), _ in items:
                targets = [capture_target(bindings.get(port, {}).get(value.key))
                           for port, value in zip(('A', 'B'), (a, b))]
                if any(target is None for target in targets) or targets[0] == targets[1]:
                    raise ValueError('Native Fillet needs two distinct published or referenced curves per result.')
                rows.append({'path': list(path), 'targets': targets, 'corner': list(near.xyz),
                             'radius': checked_radius(radius)})
        if not 1 <= len(rows) <= 250:
            raise ValueError('Native Fillet needs 1–250 curve pairs.')
    return {**{field: parameters[field] for field in ('project_uuid', 'node_uuid', 'primitive')},
            'rows': rows, 'update': bool(records)}


def fillet_shape(first, second, radius, corner):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from serpentine3d.core import geometry as g

    a, b = (g.unwrap_compound(shape) for shape in (first, second))
    if any(g.shape_kind(shape) != 'curve' for shape in (a, b)):
        raise ValueError('Fillet requires two curves.')
    # Serpentine's current fillet already trims the clicked segment and
    # retains the rest of its polyline. The source BREP may be cached.
    pieces = g.fillet_curves(g.copy_shape(a), g.copy_shape(b), radius, corner)
    result = g.join_curves(pieces)
    if not BRepCheck_Analyzer(result).IsValid():
        raise ValueError('OpenCascade returned an invalid Fillet curve.')
    return result
