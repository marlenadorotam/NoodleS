"""DataTree planning for the non-destructive Boolean variants."""
from dataclasses import replace
from .curves import CurveInput
from .fillet_curves import FILLET, FILLET_INPUTS, FILLET_PARAMETRIC


BASE = CurveInput('A', 'Subtract From', 'boolean_solid')
CUTTERS = CurveInput('B', 'Subtract With', 'boolean_solid')
OBJECTS = CurveInput('O', 'Solid Operands', 'boolean_solid')
BOOLEAN_SPLIT = 'boolean_split'
BOOLEAN_SPLIT_PARAMETRIC = 'boolean_split_parametric'
SPLIT_OPERANDS = (CurveInput('A', 'Solids to Split', 'boolean_solid'),
                  CurveInput('B', 'Cutting Geometry', 'geometry'))
SPLIT_PLANE = CurveInput('P', 'Cutting Plane', 'plane', 'XY')
PARAMETRIC_BOOLEANS = {
    'boolean_union_parametric': ('Union', (OBJECTS,)),
    'boolean_difference_parametric': ('Difference', (BASE, CUTTERS)),
    'boolean_intersection_parametric': ('Intersection', (OBJECTS,)),
}
NATIVE_BOOLEANS = {
    key.removesuffix('_parametric'): (name, tuple(replace(
        d, kind='native_boolean_operand', label='Solid or Surface Operands' if d.port == 'O' else d.label)
        for d in inputs))
    for key, (name, inputs) in PARAMETRIC_BOOLEANS.items()
}
NATIVE_BOOLEANS[BOOLEAN_SPLIT] = ('Split', SPLIT_OPERANDS)
NATIVE_SCENE_OPERATIONS = {**NATIVE_BOOLEANS, FILLET: ('Fillet', FILLET_INPUTS)}
SHOW_PARENT_OPERATIONS = frozenset((*PARAMETRIC_BOOLEANS, BOOLEAN_SPLIT_PARAMETRIC,
                                    FILLET_PARAMETRIC, 'array_polar', 'objects_on_points',
                                    'join', 'brep_join'))


def can_hide_sources(part):
    from .moves import RigidValue, TranslatedValue

    while isinstance(part, (RigidValue, TranslatedValue)):
        part = part.source
    return part.kind in SHOW_PARENT_OPERATIONS


def hidden_parents(parameters, bindings):
    if parameters.get('parameters', {}).get('show_parent', True):
        return ()
    return visibility_targets(binding for port in bindings.values() for binding in port.values())


def visibility_targets(bindings):
    return tuple(sorted({
        ('reference' if binding.reference_id else 'owner', binding.project,
         binding.source_uuid, binding.part.split('/', 1)[0] if binding.reference_id else '')
        for binding in bindings
    }))


def is_boolean_operand(value, *, solid_only=True):
    from .curves import is_curve_recipe
    from .moves import RigidValue, TranslatedValue
    from .operations import OperationValue
    from .solids import SolidValue
    from .surface_reference import SurfaceReferenceValue
    while isinstance(value, (RigidValue, TranslatedValue)):
        value = value.source
    if isinstance(value, SolidValue):
        return value.solid or not solid_only
    if isinstance(value, SurfaceReferenceValue):
        return value.native_kind in ('solid', 'compound') or not solid_only and value.native_kind == 'surface'
    return isinstance(value, OperationValue) and not is_curve_recipe(value) and value.result_kind in (
        (None, 'solid', 'compound') if solid_only else (None, 'surface', 'solid', 'compound'))


def difference_branches(sources, tools, *, allow_shared):
    if len(tools) == 1 and (allow_shared or len(sources) == 1):
        return ((branch, tools[0]) for branch in sources)
    cutters = {b.path: b for b in tools}
    if set(cutters) != {b.path for b in sources}:
        raise ValueError('With must match the From paths.' if not allow_shared else
                         'With must have one shared branch or match the From paths.')
    return ((branch, cutters[branch.path]) for branch in sources)


def boolean_slots(operation, trees, bindings):
    """Yield result recipes per branch. Cutter branches match as whole lists."""
    sources = trees[0].branches
    if len(sources) > 250:
        raise ValueError('Boolean operations support up to 250 result slots.')
    def unique(items, port):
        upstream = bindings.get(port, {})
        ids = set()
        for value in items:
            binding = upstream.get(value.key)
            if binding is None:
                identity = (id(value),)
            elif binding.reference_id:
                identity = ('reference', binding.reference_id)
            else:
                identity = (binding.owner, binding.part)
            ids.add(identity)
        if len(ids) != len(items):
            raise ValueError('Duplicate Boolean operand in one branch.')
        return ids

    if operation != 'boolean_difference_parametric':
        for branch in sources:
            if not 2 <= len(branch.items) <= 100:
                raise ValueError('Each Boolean branch needs 2–100 solid operands.')
            unique(branch.items, 'O')
            yield branch.path, ((branch.items, branch.keys),)
        return
    for branch, tool_branch in difference_branches(sources, trees[1].branches, allow_shared=True):
        if not 1 <= len(branch.items) <= 100 or not 1 <= len(tool_branch.items) <= 100:
            raise ValueError('Each Difference branch needs 1–100 bases and 1–100 cutters.')
        cutter_ids = unique(tool_branch.items, 'B')
        if unique(branch.items, 'A') & cutter_ids:
            raise ValueError('A Difference base cannot cut itself.')
        yield branch.path, tuple(((base, *tool_branch.items), (key,))
                                 for key, base in zip(branch.keys, branch.items))


def native_boolean_plan(operation, parameters, inputs, bindings):
    from .curves import input_tree
    trees = [input_tree(inputs[d.port], d, parameters['tree_modes'].get(d.port, 'none'))
             for d in NATIVE_BOOLEANS[operation][1]]
    sources = trees[0].branches
    if not 1 <= len(sources) <= 250:
        raise ValueError('Native Boolean needs 1–250 nonempty branches.')

    def targets(branch, port):
        groups = {}
        for operand in branch.items:
            binding = bindings.get(port, {}).get(operand.key)
            if binding is None or binding.selectors:
                raise ValueError('Native Boolean needs whole published or referenced objects.')
            identity = (binding.project, binding.source_uuid, binding.part if binding.reference_id else '')
            group = groups.setdefault(identity, {
                'project_uuid': binding.project, 'node_uuid': binding.source_uuid,
                'key': binding.part, 'reference': bool(binding.reference_id), 'parts': [],
            })
            if binding.part in group['parts']:
                raise ValueError('Native Boolean cannot consume a source twice.')
            group['parts'].append(binding.part)
        return list(groups.values())

    rows = []
    if operation in ('boolean_difference', BOOLEAN_SPLIT):
        split = operation == BOOLEAN_SPLIT
        for branch, cutters in difference_branches(sources, trees[1].branches, allow_shared=split):
            base, tools = targets(branch, 'A'), targets(cutters, 'B')
            if not 1 <= len(base) <= (100 if split else 1) or not 1 <= len(tools) <= 100:
                if split:
                    raise ValueError('Native Boolean Split needs 1–100 whole targets and 1–100 cutters per branch.')
                raise ValueError('Native Difference needs one whole base and 1–100 cutters per branch.')
            rows.extend({'path': list(branch.path), 'targets': [target, *tools]} for target in base)
            if len(rows) > 250:
                raise ValueError('Native Boolean Split supports up to 250 targets.')
    else:
        for branch in sources:
            operands = targets(branch, 'O')
            if not 2 <= len(operands) <= 100:
                raise ValueError('Native Boolean needs 2–100 whole objects per branch.')
            rows.append({'path': list(branch.path), 'targets': operands})
    return {'project_uuid': parameters['project_uuid'], 'node_uuid': parameters['node_uuid'],
            'primitive': operation, 'rows': rows}


def native_boolean_outputs(node, records):
    from .datatree import Branch, DataTree
    from .moves import Binding
    from .surface_reference import surface_reference_from_wire
    branches, radii, bindings = {}, {}, {}
    for record in records:
        value = surface_reference_from_wire(record['recipe'])
        path = tuple(record['path'])
        branches.setdefault(path, []).append(value)
        if node.operation == FILLET:
            radii.setdefault(path, []).append(record['radius'])
        bindings[value.key] = Binding(node.id, value.key, reference_id=record['id'],
            project=node.parameters['project_uuid'], source_uuid=node.parameters['node_uuid'])
    geometry = DataTree(tuple(Branch(path, tuple(values), tuple(value.key for value in values))
                              for path, values in branches.items()))
    outputs = {'G': geometry}
    if node.operation == BOOLEAN_SPLIT:
        outputs['Count'] = geometry.count
    if node.operation == FILLET:
        outputs['R'] = DataTree(tuple(Branch(b.path, tuple(radii[b.path]), b.keys) for b in geometry.branches))
    return outputs, {'G': bindings}
