"""Typed graph data for coordinate systems and loft settings."""
from dataclasses import dataclass, replace
import hashlib
import math
from random import Random

from .curves import CurveInput, PlaneValue, add, cross, input_tree, matched_inputs, normalize_curve_state, plane, scale, unit
from .datatree import Branch, DataTree, MAX_ITEMS, aligned
from .domain import DomainValue
from .list_nodes import CROSS_REFERENCE_MODES, LIST_SPECS, POINT_SORT_ORDERS, evaluate_list
from .point import PointValue
from .annotations import GRADIENT, GRADIENT_SPEC, evaluate_gradient
from .table_data import DEFAULT_CHOICES, choice_entries


WORLD_PLANES = {f'{axes.lower()}_plane': axes for axes in ('XY', 'YZ', 'XZ')}

DATA_HELPER_SPECS = {
    **LIST_SPECS,
    GRADIENT: GRADIENT_SPEC,
    'deconstruct_point': {'class': 'DeconstructPointNode', 'name': 'Deconstruct Point', 'category': 'Math',
        'reference': False, 'inputs': (CurveInput('P', 'Points', 'points'),), 'outputs': ('X', 'Y', 'Z')},
    'random': {'class': 'RandomNode', 'name': 'Random', 'category': 'Math', 'reference': False,
        'inputs': (CurveInput('R', 'Range / Domain', 'dimension', 1.),
                   CurveInput('N', 'Count', 'population_2d_count', 1),
                   CurveInput('S', 'Seed', 'population_seed', 0)), 'outputs': ('R',)},
    'construct_plane': {'class': 'ConstructPlaneNode', 'name': 'Construct Plane', 'category': 'Math',
        'reference': False, 'inputs': (CurveInput('O', 'Origin', 'point', (0., 0., 0.)),
                   CurveInput('X', 'X Axis', 'vector', (1., 0., 0.)),
                   CurveInput('Y', 'Y Axis', 'vector', (0., 1., 0.))), 'outputs': ('P',)},
    'deconstruct_plane': {'class': 'DeconstructPlaneNode', 'name': 'Deconstruct Plane', 'category': 'Math',
        'reference': False, 'inputs': (CurveInput('P', 'Plane', 'plane', 'XY'),), 'outputs': ('O', 'X', 'Y', 'Z')},
    'plane_fit': {'class': 'PlaneFitNode', 'name': 'Plane Fit', 'category': 'Math',
        'reference': False, 'inputs': (CurveInput('P', 'Points', 'points'),), 'outputs': ('P', 'D', 'R')},
    'point_cylindrical': {'class': 'PointCylindricalNode', 'name': 'Point Cylindrical', 'category': 'Geometry',
        'reference': False, 'primary': 'P', 'inputs': (CurveInput('P', 'Base Plane', 'plane', 'XY'),
                   CurveInput('A', 'Angle (Radians)', 'number', 0.),
                   CurveInput('R', 'Radius', 'number', 1.),
                   CurveInput('E', 'Elevation', 'number', 0.)), 'outputs': ('P',)},
    **{operation: {'class': f'{axes}PlaneNode', 'name': f'Plane {axes}', 'category': 'Math', 'reference': False,
                   'inputs': (CurveInput('O', 'Origin', 'point', (0., 0., 0.)),), 'outputs': ('P',)}
       for operation, axes in WORLD_PLANES.items()},
    'plane_normal': {'class': 'PlaneNormalNode', 'name': 'Plane Normal', 'category': 'Math', 'reference': False,
        'inputs': (CurveInput('O', 'Origin', 'point', (0., 0., 0.)),
                   CurveInput('Z', 'Z Axis', 'vector', (0., 0., 1.))),
        'outputs': ('P',)},
    'loft_options': {'class':'LoftOptionsNode', 'name':'Loft Options', 'category':'Operations', 'reference':False,
        'inputs': (CurveInput('C','Closed Section Cycle','boolean',False),
                   CurveInput('A','Adjust Section Compatibility','boolean',True),
                   CurveInput('B','Rebuild','boolean',False), CurveInput('F','Refit','boolean',False),
                   CurveInput('T','Loft Type','loft_type',0,('Smooth','Ruled'))),
        'outputs': ('O',)},
}


@dataclass(frozen=True)
class LoftOptionsValue:
    closed: bool
    adjust: bool
    rebuild: bool
    refit: bool
    loft_type: int

    def __str__(self):
        style = 'Ruled' if self.loft_type else 'Smooth'
        return f'{style} · {"Closed" if self.closed else "Open"} · Adjust {"On" if self.adjust else "Off"}'


def normalize_data_helper(operation, data):
    state = normalize_curve_state(operation, data, spec=DATA_HELPER_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Data nodes do not support scene references.')
    if operation == 'cross_reference':
        pairing = data.get('parameters', {}).get('pairing', 'holistic')
        if not isinstance(pairing, str) or pairing not in CROSS_REFERENCE_MODES:
            raise ValueError('Choose a valid Cross Reference pairing mode.')
        state['parameters']['pairing'] = pairing
    if operation == 'sort_points':
        order = data.get('parameters', {}).get('axis_order', 'XYZ')
        if order not in POINT_SORT_ORDERS:
            raise ValueError('Choose a valid Sort Points axis order.')
        state['parameters']['axis_order'] = order
    if operation == 'value_list':
        settings = data.get('parameters', {})
        options = settings.get('options', DEFAULT_CHOICES)
        selection = settings.get('selection', 0)
        if type(selection) is not int or not 0 <= selection < len(choice_entries(options)):
            raise ValueError('Choose an available Value List option.')
        state['parameters'].update(options=options, selection=selection)
    if operation == 'read_csv':
        revision = data.get('parameters', {}).get('reload', 0)
        if type(revision) is not int or revision < 0:
            raise ValueError('Invalid CSV reload revision.')
        state['parameters']['reload'] = revision
    return state


def evaluate_data_helper(operation, parameters, inputs):
    state = normalize_data_helper(operation, parameters)
    if operation in LIST_SPECS:
        return evaluate_list(operation, state, inputs, graph_directory=parameters.get('graph_directory'))[0]
    spec = DATA_HELPER_SPECS[operation]
    if operation == GRADIENT:
        if 'V' not in inputs:
            raise ValueError('Connect input V.')
        trees = {d.port: input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                                    state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
                 for d in spec['inputs'] if d.port in inputs or d.default is not None}
        return evaluate_gradient(trees)
    world_frame = plane(WORLD_PLANES[operation]) if operation in WORLD_PLANES else None
    trees = matched_inputs([input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
        state['tree_modes'].get(d.port, 'none'), d.port not in inputs) for d in spec['inputs']])
    if operation in ('deconstruct_plane', 'plane_fit'):
        from .plane_fit import evaluate_planes
        return evaluate_planes(operation, trees[0])
    if operation == 'deconstruct_point':
        return {axis: DataTree(tuple(Branch(b.path, tuple(p.xyz[i] for p in b.items), b.keys)
                                     for b in trees[0].branches)) for i, axis in enumerate(('X', 'Y', 'Z'))}
    if operation == 'random':
        return {'R': random_tree(trees)}
    branches = []
    for path, rows in aligned(*trees):
        widths = [len((next((b for b in t.branches if b.path == path), None) or t.branches[0]).items)
                  for t in trees if t.branches]
        if rows and any(n not in (1, len(rows)) for n in widths):
            raise ValueError('Use matching list lengths or one value per input.')
        values, keys = [], []
        for items, provenance in rows:
            if operation == 'loft_options':
                values.append(LoftOptionsValue(*items))
            elif operation == 'construct_plane':
                origin, xaxis, yaxis = items
                xdir, ydir = unit(xaxis.xyz), unit(yaxis.xyz)
                values.append(PlaneValue(origin.xyz, xdir, cross(xdir, ydir)))
            elif operation == 'point_cylindrical':
                key = hashlib.sha256(repr((path, len(values), provenance)).encode()).hexdigest()[:24]
                values.append(PointValue(key, cylindrical_coordinates(*items)))
            elif world_frame is not None:
                values.append(replace(world_frame, origin=items[0].xyz))
            else:
                origin, vector = items
                normal = unit(vector.xyz)
                guide = (0., 1., 0.) if abs(normal[0]) > .999 else (1., 0., 0.)
                values.append(PlaneValue(origin.xyz, guide, normal))
            keys.append(values[-1].key if operation == 'point_cylindrical' else '|'.join(provenance))
        branches.append(Branch(path, tuple(values), tuple(keys)))
    return {spec['outputs'][0]: DataTree(tuple(branches))}


def cylindrical_coordinates(frame, angle, radius, elevation):
    if radius < 0:
        raise ValueError('Radius must be nonnegative.')
    position = frame.at(radius * math.cos(angle), radius * math.sin(angle))
    return add(position, scale(frame.normal, elevation))


def random_tree(trees):
    matches = tuple(aligned(*trees))
    split = any(len(rows) > 1 for _, rows in matches)
    branches = []
    total = 0
    for path, rows in matches:
        if not rows:
            branches.append(Branch(path + (0,) if split else path, ()))
        for slot, ((interval, count, seed), _) in enumerate(rows):
            total += count
            if total > MAX_ITEMS:
                raise ValueError(f'Random supports up to {MAX_ITEMS:,} numbers in total.')
            start, end = (interval.start, interval.end) if isinstance(interval, DomainValue) else (0., interval)
            rng = Random(seed)
            # Convex interpolation also handles large finite endpoints of opposite sign.
            values = tuple((1 - t) * start + t * end for t in (rng.random() for _ in range(count)))
            branches.append(Branch(path + (slot,) if split else path, values))
    return DataTree(tuple(branches))
