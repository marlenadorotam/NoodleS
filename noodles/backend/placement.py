"""Deferred copy layouts shared with native placement commands."""
import math

from .curves import CurveInput, input_tree, matched_inputs, unit, add, xyz
from .datatree import Branch, DataTree, aligned, topology
from .splines import integer


PLACEMENT_SPECS = {
    'array': {'class': 'ArrayNode', 'name': 'Array', 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'),
        CurveInput('Nx', 'Count X', 'array_count', 2),
        CurveInput('Ny', 'Count Y', 'array_count', 1),
        CurveInput('Dx', 'Spacing X', 'number', 10.),
        CurveInput('Dy', 'Spacing Y', 'number', 0.)), 'outputs': ('G', 'Count', 'Flat')},
    'array_polar': {'class': 'ArrayPolarNode', 'name': 'Array Polar', 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'),
        CurveInput('P', 'Axis Plane', 'plane', 'XY'),
        CurveInput('N', 'Count', 'polar_array_count'),
        CurveInput('A', 'Sweep Angle (Degrees)', 'number', 360.)), 'outputs': ('G', 'Count', 'Flat')},
    'objects_on_points': {'class': 'ObjectsOnPointsNode', 'name': 'Objects on Points', 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'),
        CurveInput('P', 'Placement Points', 'points'),
        CurveInput('N', 'Normal', 'vector', (0., 0., 1.)),
        CurveInput('I', 'Insertion Vector', 'vector', (0., 0., 0.)),
        CurveInput('T', 'Transform Scale', 'placement_scale', optional=True)), 'outputs': ('G', 'Count', 'Name')},
}
PLACEMENT_LIMITS = {'array': 1600, 'array_polar': 1200, 'objects_on_points': 2000}


def array_offsets(nx, ny, dx, dy):
    nx, ny = (integer(n, 'Array count', 1, 1600) for n in (nx, ny))
    if nx * ny > 1600:
        raise ValueError('Array supports at most 1600 cells per source.')
    return ((i, j, (i * dx, j * dy, 0.)) for i in range(nx) for j in range(ny) if i or j)


def polar_angles(count, angle):
    count = integer(count, 'Array Polar Count', 2, 360)
    if not 0 < abs(angle) <= 360:
        raise ValueError('Array Polar requires 0 < abs(Sweep Angle) <= 360 degrees.')
    divisor = count if abs(angle) == 360 else count - 1
    return (angle * i / divisor for i in range(count))


def placement_scale(value):
    from .arithmetic import VectorValue
    factors = value.xyz if isinstance(value, VectorValue) else (
        (value,) * 3 if type(value) in (int, float) else value)
    factors = xyz(factors)
    if any(f <= 0 for f in factors):
        raise ValueError('Transform Scale needs a positive number or positive XYZ factors.')
    return factors


def _point_scales(points, scales):
    if scales is None:
        return DataTree(tuple(Branch(b.path, tuple((p, (1., 1., 1.)) for p in b.items), b.keys)
                              for b in points.branches))
    by_path = {b.path: b.items for b in scales.branches}
    shared = scales.branches[0].items if len(scales.branches) == 1 else None
    if shared is None and set(by_path) != {b.path for b in points.branches}:
        raise ValueError('Transform Scale branches must match Placement Points.')
    flat = shared if shared is not None and len(shared) == points.count else None
    offset = 0
    result = []
    for branch in points.branches:
        values = flat[offset:offset+len(branch.items)] if flat is not None else (
            shared if shared is not None else by_path[branch.path])
        if branch.items and len(values) not in (1, len(branch.items)):
            raise ValueError('Use one Transform Scale or one per Placement Point.')
        result.append(Branch(branch.path, tuple((p, values[min(i, len(values)-1)])
                                                for i, p in enumerate(branch.items)), branch.keys))
        offset += len(branch.items)
    return DataTree(tuple(result))


def evaluate(operation, state, inputs, key):
    from .operations import OperationValue

    trees = []
    for d in PLACEMENT_SPECS[operation]['inputs']:
        if not d.optional or d.port in inputs:
            trees.append(input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                                   state['tree_modes'].get(d.port, 'none'), d.port not in inputs))
    if operation == 'objects_on_points':
        trees[1] = _point_scales(trees[1], trees.pop() if len(trees) == 5 else None)
    else:
        trees = matched_inputs(trees)
    branches = []
    count = complexity = 0
    for path, rows in aligned(*trees):
        placed = []
        for slot, ((source, *args), provenance) in enumerate(rows):
            if operation == 'array':
                items = (OperationValue(key((path, provenance, i, j)), operation, (source,), vector=offset)
                         for i, j, offset in array_offsets(*args))
            elif operation == 'array_polar':
                axis, n, angle = args
                items = (OperationValue(key((path, provenance, i)), operation, (source,), axis=axis, angle=a)
                         for i, a in enumerate(polar_angles(n, angle)))
            else:
                (point, factors), normal, insertion = args
                items = (OperationValue(key((path, provenance)), operation, (source,),
                                        vector=add(point.xyz, insertion.xyz), placement=(unit(normal.xyz), factors)),)
            values = []
            for item in items:
                count += 1
                complexity += item.complexity
                if count > PLACEMENT_LIMITS[operation] or complexity > 10000:
                    raise ValueError('Placement exceeds the copy or geometry recipe limit.')
                values.append(item)
            if operation == 'array':
                branches.append(Branch((*path, slot), tuple(values), tuple(v.key for v in values)))
            else:
                placed.extend(values)
        if operation != 'array':
            branches.append(Branch(path, tuple(placed), tuple(v.key for v in placed)))
    result = DataTree(tuple(branches))
    outputs = {'G': result, 'Count': count}
    if operation == 'objects_on_points':
        outputs['Name'] = state.get('name', 'Objects on Points')
    else:
        outputs['Flat'] = topology(result, 'flatten')
    return outputs
