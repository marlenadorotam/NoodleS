"""Match connected Reference inputs to captured geometry keys."""
from dataclasses import replace
import math

from .arithmetic import VectorValue
from .curves import (CURVE_SPECS, PlaneValue, arc, arc_center, circle, ellipse,
                     input_tree, line, matched_inputs, plane, polyline, rectangle,
                     dot, xyz)
from .datatree import Branch, DataTree, MAX_ITEMS, topology
from .domain import DomainValue
from .geometry import normalize_geometry_state
from .point import PointValue
from .grids import GRID_SPECS, grid_reference_tree
from .solids import SOLID_DIMENSION_PORTS, SOLID_SPECS
from .splines import spline

REFERENCE_SPECS = {**CURVE_SPECS, **SOLID_SPECS, **GRID_SPECS}


def build_reference_drive(operation, parameters, inputs):
    state = normalize_geometry_state(operation, parameters)
    modes = state['tree_modes']
    if operation in GRID_SPECS:
        keys = DataTree(tuple(Branch(b.path, b.keys) for b in grid_reference_tree(state).branches))
    else:
        keys = topology([r['key'] for r in state['references']], modes.get('References', 'none'))
    updates = {key: {} for key in keys.values()}
    for descriptor in REFERENCE_SPECS[operation]['inputs']:
        port = descriptor.port
        if port not in inputs:
            continue
        values = input_tree(inputs[port], descriptor, modes.get(port, 'none'), keep_normal=True)
        if descriptor.kind == 'points':
            groups = tuple(Branch(b.path, (tuple(p.xyz for p in b.items),))
                           for b in values.branches if b.items)
            values = DataTree(groups)
        ref_keys, values = matched_inputs([keys, values])
        by_path = {b.path: b.items for b in values.branches}
        if not by_path:
            raise ValueError(descriptor.label + ' has no values for the references.')
        if len(by_path) == 1:
            shared = next(iter(by_path.values()))
        else:
            shared = None
            if {b.path for b in ref_keys.branches} != set(by_path):
                raise ValueError(descriptor.label + ' paths must match References. Use Graft on Objects for one branch per object.')
        for branch in ref_keys.branches:
            items = shared if shared is not None else by_path[branch.path]
            if len(items) not in (1, len(branch.items)):
                raise ValueError('Use one value or one value per reference for ' + descriptor.label + '.')
            for i, key in enumerate(branch.items):
                value = items[0 if len(items) == 1 else i]
                if isinstance(value, (PointValue, VectorValue)):
                    value = list(value.xyz)
                elif isinstance(value, (PlaneValue, DomainValue)):
                    value = value.to_wire()
                if port in updates[key] and updates[key][port] != value:
                    raise ValueError('One reference received conflicting values for ' + descriptor.label + '.')
                updates[key][port] = value
    return {'updates': [{'key': key, 'values': values} for key, values in updates.items() if values]}


def decode_updates(operation, raw):
    descriptors = {d.port: d for d in REFERENCE_SPECS[operation]['inputs']}
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise ValueError('Invalid reference update list.')
    updates = {}
    for item in raw:
        key, values = item['key'], item['values']
        if not isinstance(key, str) or not 0 < len(key) <= 256 or key in updates:
            raise ValueError('Invalid or duplicate reference key.')
        if not isinstance(values, dict) or not values or set(values) - set(descriptors):
            raise ValueError('Invalid reference parameter ports.')
        updates[key] = {}
        for port, value in values.items():
            d = descriptors[port]
            if d.kind == 'points':
                if not isinstance(value, (list, tuple)) or not 0 < len(value) <= MAX_ITEMS:
                    raise ValueError('Invalid reference point list.')
                value = tuple(xyz(p) for p in value)
            else:
                if d.kind in ('point', 'center'):
                    value = PointValue('input', xyz(value))
                elif d.kind == 'plane':
                    value = PlaneValue(**value) if isinstance(value, dict) else VectorValue(xyz(value))
                elif d.kind == 'dimension' and isinstance(value, dict):
                    value = DomainValue(value['start'], value['end'])
                value = input_tree(value, d, keep_normal=True).values()[0]
            updates[key][port] = value
    return updates


def _frame(current, args, location):
    frame = current.frame
    source = args.get('P')
    origin = frame.origin
    if isinstance(source, PlaneValue):
        frame, origin = source, source.origin
    elif isinstance(source, VectorValue):
        normal = plane(source).normal
        axis_x = frame.axis_x if abs(dot(frame.axis_x, normal)) < 1 - 1e-10 else plane(source).axis_x
        frame = PlaneValue(origin, axis_x, normal)
    if location in args:
        origin = args[location].xyz
    return PlaneValue(origin, frame.axis_x, frame.normal)


def reference_target(operation, current, args):
    """Merge a validated patch into the current native definition."""
    key = current.key
    if operation in GRID_SPECS:
        spacing = ('Sx', 'Sy') if operation == 'grid_rectangle' else ('S',)
        extents = ('Er', 'Ep') if operation == 'grid_radial' else ('Ex', 'Ey')
        return replace(current, frame=_frame(current, args, 'O'),
                       spacing=tuple(args.get(p, v) for p, v in zip(spacing, current.spacing)),
                       extents=tuple(args.get(p, v) for p, v in zip(extents, current.extents)))
    if operation in SOLID_SPECS:
        ports = SOLID_DIMENSION_PORTS[operation]
        frame = _frame(current, args, 'O')
        if operation == 'sphere':
            frame = replace(current.frame, origin=frame.origin)
        return replace(current, frame=frame, dimensions=tuple(args.get(p, d) for p, d in zip(ports, current.dimensions)),
                       solid=args.get('S', current.solid))
    if operation in ('circle', 'ellipse', 'rectangle', 'arc_center'):
        frame = _frame(current, args, 'C')
        if operation == 'circle':
            return circle(key, frame.origin, args.get('R', current.radius), frame)
        if operation == 'ellipse':
            a, b = current.dimensions
            return ellipse(key, frame.origin, args.get('A', a), args.get('B', b), frame)
        if operation == 'rectangle':
            x, y = current.dimensions
            return rectangle(key, args.get('X', x), args.get('Y', y), frame.origin, frame)
        return arc_center(key, frame.origin, args.get('R', current.radius),
                          args.get('A', math.degrees(current.angle)), frame)
    if operation in ('line', 'arc'):
        ports = ('A', 'B') if operation == 'line' else ('A', 'M', 'B')
        points = tuple(args[p].xyz if p in args else old for p, old in zip(ports, current.points))
        return (line if operation == 'line' else arc)(key, *points)
    if operation == 'polyline':
        return polyline(key, args.get('P', current.points), args.get('C', current.closed))
    degree = args.get('D', current.degree)
    closed = args.get('C', current.closed)
    periodic = args.get('T', current.periodic)
    if operation == 'interpcurve' and 'T' in args and not periodic and 'C' not in args and current.periodic:
        closed = False
    options_changed = (degree, closed, periodic) != (current.degree, current.closed, current.periodic)
    if 'P' not in args:
        if not options_changed and 'K' not in args:
            return current
        if operation == 'interpcurve':
            raise ValueError('Connect P to change InterpCurve construction settings. The native spline stores control poles, not interpolation sites.')
    points = args.get('P', current.points)
    if operation == 'curve' and not options_changed and len(points) == len(current.points):
        if len(set(points)) < 2:
            raise ValueError('Curve needs distinct control points.')
        return current if points == current.points else replace(current, points=points, measured_length=None)
    return spline(key, operation, points, degree, closed, periodic, args.get('K', 1))
