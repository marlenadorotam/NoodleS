"""Deferred topology plans and typed piece outputs for the graph."""
from dataclasses import replace
import hashlib

from .curves import CurveInput, add, input_tree, matched_inputs, scale
from .booleans import BOOLEAN_SPLIT_PARAMETRIC, SPLIT_OPERANDS, SPLIT_PLANE
from .datatree import Branch, DataTree, MAX_BRANCHES, MAX_ITEMS, aligned
from .point import PointValue
from .profile_operations import FLIP_CURVE, MOVE_SEAM, SHATTER
from .pull import request_signature
from .splines import PendingGeometry
from .surface_modules import SURFACE_ISOCURVES


TOPOLOGY_INPUT = CurveInput('G', 'Geometry', 'geometry')
BREP_INPUT = CurveInput('B', 'Breps to Join', 'geometry')
SECTION = 'section'
CONTOUR = 'contour'
CURVE_CURVE = 'curve_curve'
REGION_BOOLEAN = 'region_boolean'
REGION_MODES = ('Union', 'Difference', 'Intersection')
SECTION_INPUTS = (CurveInput('B', 'Surfaces or Solids', 'native_boolean_operand'),
                  CurveInput('P', 'Section Plane', 'plane', 'XY'))
CONTOUR_INPUTS = (SECTION_INPUTS[0], CurveInput('P', 'Base Plane', 'plane', 'XY'),
                  CurveInput('D', 'Spacing', 'number', 3.),
                  CurveInput('N', 'Plane Count', 'division_count', 10))
CURVE_CURVE_INPUTS = (CurveInput('A', 'Curve A', 'sample_curve'),
                      CurveInput('B', 'Curve B', 'sample_curve'))
REGION_INPUTS = (CurveInput('A', 'Regions or Closed Curves A', 'geometry'),
                 CurveInput('B', 'Regions or Closed Curves B', 'geometry', optional=True))
SPLIT_INPUTS = (CurveInput('G', 'Target Geometry', 'geometry'),
                CurveInput('C', 'Cutting Geometry', 'geometry'))
TRIM_INPUTS = (*SPLIT_INPUTS, CurveInput('P', 'Remove At', 'point'))
TOPOLOGY_SOURCE_LIMITS = {'join': (2, 240), 'brep_join': (1, 240), 'explode': (1, 1),
                          'split': (2, 241), BOOLEAN_SPLIT_PARAMETRIC: (2, 241), 'trim': (2, 241), SECTION: (1, 1),
                          CURVE_CURVE: (2, 2), REGION_BOOLEAN: (1, 240),
                          SHATTER: (1, 1), FLIP_CURVE: (1, 2), MOVE_SEAM: (1, 1)}
TOPOLOGY_OPERATIONS = (*TOPOLOGY_SOURCE_LIMITS, CONTOUR, SURFACE_ISOCURVES)
TOPOLOGY_SOURCE_LIMITS['deconstruct_brep'] = (1, 1)
PIECE_KINDS = ('curve', 'surface', 'solid', 'compound')


def topology_input(state, inputs, descriptor):
    port = descriptor.port
    value = inputs.get(port, state['parameters'].get(port))
    return input_tree(value, descriptor, state['tree_modes'].get(port, 'none'), port not in inputs)


def group_branches(tree):
    return DataTree(tuple(Branch(branch.path, (branch.items,)) for branch in tree.branches))


def contour_planes(rows):
    for plane, distance, count in rows:
        if distance <= 0:
            raise ValueError('Contour spacing must be positive.')
        for index in range(count):
            yield replace(plane, origin=add(plane.origin, scale(plane.normal, index*distance)))


def evaluate_section(operation, state, inputs, details):
    from .operations import OperationValue

    contour = operation == CONTOUR
    trees = [topology_input(state, inputs, desc) for desc in (CONTOUR_INPUTS if contour else SECTION_INPUTS)]
    if contour:
        settings = DataTree(tuple(Branch(path, (tuple(args for args, _ in rows),))
                                  for path, rows in aligned(*matched_inputs(trees[1:]))))
        pairs = aligned(group_branches(trees[0]), settings)
    else:
        pairs = aligned(*map(group_branches, trees))
    pairs = [(path, *rows[0][0]) for path, rows in pairs]
    split_planes = contour or any(len(planes) > 1 for _, _, planes in pairs)
    layout, requests, sources = [], [], {}
    for path, breps, planes in pairs:
        cuts = contour_planes(planes) if contour and planes else planes or (None,)
        for slot, plane in enumerate(cuts):
            if len(layout) >= MAX_BRANCHES:
                raise ValueError('Section or Contour exceeds the 10000-level branch budget.')
            level = path + (slot,) if split_planes else path
            items = tuple((source, plane) for source in breps) if plane is not None else ()
            if len(requests) + len(items) > MAX_ITEMS:
                raise ValueError('Section exceeds the 10000-cut budget.')
            layout.append((level, items))
            requests.extend([sources.setdefault(source, len(sources)), plane.to_wire()] for source, plane in items)
    plan = {'operation': SECTION, 'sources': [source.to_wire() for source in sources], 'rows': requests}
    signature = request_signature(plan)
    if requests and details.get('signature') != signature:
        pending = PendingGeometry('Waiting for native sections')
        tree = DataTree(tuple(Branch(path, (pending,) if items else ()) for path, items in layout))
        return {'C': tree, 'R': tree, '_sampling': {'project_uuid': state['project_uuid'],
                'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan}}
    if requests and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if requests else []
    if len(results) != len(requests):
        raise ValueError('Native Section returned incomplete results.')
    values = iter(results)
    curves, regions, budget = [], [], MAX_ITEMS
    for path, items in layout:
        pieces = {'curve': [], 'surface': []}
        for slot, (source, plane) in enumerate(items):
            prefix = hashlib.sha256(repr((path, source.key, slot)).encode()).hexdigest()[:24]
            for index, kind in enumerate(next(values)):
                part = OperationValue(f'{prefix}:{index}', SECTION, (source,), axis=plane,
                                      piece_index=index, result_kind=kind)
                budget -= part.complexity
                if budget < 0:
                    raise ValueError('Section exceeds the 10000-item recipe budget.')
                pieces[kind].append(part)
        curves.append(Branch(path, pieces['curve'], tuple(p.key for p in pieces['curve'])))
        regions.append(Branch(path, pieces['surface'], tuple(p.key for p in pieces['surface'])))
    return {'C': DataTree(tuple(curves)), 'R': DataTree(tuple(regions))}


def region_parameters(mode, a_count, total):
    if (mode not in REGION_MODES or type(a_count) is not int or not 1 <= a_count <= total
            or (mode == 'Intersection' and a_count == total)):
        raise ValueError('Invalid Region Boolean operand groups.')
    return mode, a_count


def evaluate_intersections(operation, state, inputs, details):
    from .operations import OperationValue

    regions = operation == REGION_BOOLEAN
    descriptors = REGION_INPUTS if regions else CURVE_CURVE_INPUTS
    a = topology_input(state, inputs, descriptors[0])
    rows, layout, sources = [], [], {}

    def query(operands, options=None):
        indices = [sources.setdefault(source, len(sources)) for source in operands]
        rows.append(indices if options is None else {'indices': indices, 'region': options})
        return operands, options

    if regions:
        mode = state['parameters']['region_mode']
        if mode != 'Union' and 'B' not in inputs:
            raise ValueError('Connect input B for ' + mode + '.')
        b = topology_input(state, inputs, descriptors[1]) if 'B' in inputs else DataTree((Branch((0,), ()),))
        for path, matched in aligned(group_branches(a), group_branches(b)):
            (left, right), _ = matched[0]
            if not left or (mode == 'Intersection' and not right):
                layout.append((path, ()))
                continue
            operands = (*left, *right)
            if len(operands) > TOPOLOGY_SOURCE_LIMITS[REGION_BOOLEAN][1]:
                raise ValueError('Region Boolean accepts at most 240 operands per branch.')
            layout.append((path, (query(operands, region_parameters(mode, len(left), len(operands))),)))
        ports = ('R', 'C')
    else:
        b = topology_input(state, inputs, descriptors[1])
        for path, matched in aligned(*matched_inputs((a, b))):
            layout.append((path, tuple(query(operands) for operands, _ in matched)))
        ports = ('P', 'tA', 'tB', 'C')

    plan = {'operation': operation, 'sources': [source.to_wire() for source in sources], 'rows': rows}
    signature = request_signature(plan)
    if rows and details.get('signature') != signature:
        pending = PendingGeometry('Waiting for native intersections')
        tree = DataTree(tuple(Branch(path, (pending,) if groups else ()) for path, groups in layout))
        return {**dict.fromkeys(ports, tree), '_sampling': {'project_uuid': state['project_uuid'],
                'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan}}
    if rows and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native intersection returned incomplete results.')
    values = iter(results)
    branches, budget = {port: [] for port in ports}, MAX_ITEMS
    for path, groups in layout:
        items, keys = {port: [] for port in ports}, {port: [] for port in ports}
        for slot, (operands, options) in enumerate(groups):
            result = next(values)
            prefix = hashlib.sha256(repr((path, slot)).encode()).hexdigest()[:24]
            kinds = result if regions else result['kinds']
            for index, kind in enumerate(kinds):
                key = f'{prefix}:shape:{index}'
                part = OperationValue(key, operation, operands, piece_index=index, result_kind=kind,
                                      region=options)
                port = 'R' if kind == 'surface' else 'C'
                items[port].append(part)
                keys[port].append(key)
                budget -= part.complexity
            for index, event in enumerate(() if regions else result['events']):
                key = f'{prefix}:event:{index}'
                for port, value in zip(('P', 'tA', 'tB'), (PointValue(key, tuple(event[:3])), *event[3:]), strict=True):
                    items[port].append(value)
                    keys[port].append(key)
                budget -= 1
            if budget < 0:
                raise ValueError('Intersection exceeds the 10000-item recipe budget.')
        for port in ports:
            branches[port].append(Branch(path, tuple(items[port]), tuple(keys[port])))
    return {port: DataTree(tuple(groups)) for port, groups in branches.items()}


def split_layout(targets, cutters):
    if not targets.branches:
        return
    by_path = {branch.path: branch.items for branch in cutters.branches}
    shared = cutters.branches[0].items if len(cutters.branches) == 1 else None
    if shared is None and by_path.keys() != {branch.path for branch in targets.branches}:
        raise ValueError('Split cutters need matching paths or one shared branch.')
    for branch in targets.branches:
        tools = shared if shared is not None else by_path[branch.path]
        if branch.items and not 1 <= len(tools) <= 240:
            raise ValueError('Split needs 1–240 cutters for each nonempty target branch.')
        yield branch.path, tuple((target, *tools) for target in branch.items)


def trim_layout(layout, points):
    by_path = {branch.path: branch.items for branch in points.branches}
    shared = points.branches[0].items if len(points.branches) == 1 else None
    if layout and shared is None and by_path.keys() != {path for path, _ in layout}:
        raise ValueError('Trim Remove At needs matching paths or one shared branch.')
    for path, groups in layout:
        picks = shared if shared is not None else by_path[path]
        if groups and len(picks) not in (1, len(groups)):
            raise ValueError('Trim needs one shared Remove At point or one point per target in each branch.')
        yield path, tuple((sources, picks[0 if len(picks) == 1 else index].xyz)
                          for index, sources in enumerate(groups))


def evaluate_topology(operation, state, inputs, details):
    from .operations import OperationValue

    brep = operation == 'brep_join'
    boolean_split = operation == BOOLEAN_SPLIT_PARAMETRIC
    descriptor = SPLIT_OPERANDS[0] if boolean_split else BREP_INPUT if brep else TOPOLOGY_INPUT
    port = descriptor.port
    tree = input_tree(inputs[port], descriptor, state['tree_modes'].get(port, 'none'))
    if boolean_split or operation in ('split', 'trim'):
        cutters = topology_input(state, inputs, SPLIT_OPERANDS[1] if boolean_split else SPLIT_INPUTS[1])
        layout = list(split_layout(tree, cutters))
    else:
        layout = []
        for branch in tree.branches:
            if operation in ('join', 'brep_join') and branch.items:
                minimum, maximum = TOPOLOGY_SOURCE_LIMITS[operation]
                if not minimum <= len(branch.items) <= maximum:
                    name = 'Brep Join' if brep else 'Join'
                    raise ValueError(f'{name} needs {minimum}–{maximum} items per nonempty branch.')
                groups = (branch.items,)
            else:
                groups = tuple((source,) for source in branch.items)
            layout.append((branch.path, groups))

    if boolean_split:
        planes = topology_input(state, inputs, SPLIT_PLANE)
        by_path = {branch.path: branch.items for branch in planes.branches}
        shared = planes.branches[0].items if len(planes.branches) == 1 else None
        if layout and shared is None and by_path.keys() != {path for path, _ in layout}:
            raise ValueError('Boolean Split planes need matching paths or one shared branch.')
        matched = []
        for path, groups in layout:
            frames = shared if shared is not None else by_path[path]
            if groups and len(frames) != 1:
                raise ValueError('Boolean Split needs one cutting plane per target branch.')
            matched.append((path, tuple((sources, frames[0]) for sources in groups)))
        layout = matched
    elif operation == 'trim':
        points = input_tree(inputs['P'], TRIM_INPUTS[2], state['tree_modes'].get('P', 'none'))
        layout = list(trim_layout(layout, points))
    else:
        layout = [(path, tuple((sources, None) for sources in groups)) for path, groups in layout]
    rows = []
    for _, groups in layout:
        for sources, option in groups:
            operands = [source.to_wire() for source in sources]
            if boolean_split:
                rows.append({'sources': operands, 'plane': option.to_wire()})
            else:
                rows.append(operands if option is None else {'sources': operands, 'remove_at': option})
    plan = {'operation': operation, 'rows': rows}
    signature = request_signature(plan)
    pending = PendingGeometry('Waiting for native topology')
    if rows and details.get('signature') != signature:
        branches = tuple(Branch(path, (pending,) if groups else ()) for path, groups in layout)
        tree = DataTree(branches)
        outputs = {'B': tree, 'C': tree} if brep else {'G': tree, 'Count': pending}
        return {**outputs,
                '_sampling': {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                              'signature': signature, 'plan': plan}}
    if rows and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native topology returned incomplete results.')
    values = iter(results)
    branches, count, complexity = [], 0, 0
    for path, groups in layout:
        pieces = []
        occurrences = {}
        for sources, option in groups:
            kinds = next(values)
            source_key = '' if operation in ('join', 'brep_join') else sources[0].key
            occurrence = occurrences.get(source_key, 0)
            occurrences[source_key] = occurrence + 1
            slot = hashlib.sha256(repr((path, source_key, occurrence)).encode()).hexdigest()[:24]
            for index, kind in enumerate(kinds):
                # This identifies a topology slot, not the coordinates or OCC handle.
                key = f'{slot}:{index}'
                part = OperationValue(key, operation, sources, piece_index=index,
                                      result_kind=kind, **({'axis': option} if boolean_split else {'remove_at': option}))
                count += 1
                complexity += part.complexity
                if count > MAX_ITEMS or complexity > MAX_ITEMS:
                    raise ValueError('Topology operation exceeds the 10000-item recipe budget.')
                pieces.append(part)
        branches.append(Branch(path, tuple(pieces), tuple(piece.key for piece in pieces)))
    tree = DataTree(tuple(branches))
    if brep:
        closed = DataTree(tuple(Branch(b.path, tuple(v.result_kind == 'solid' for v in b.items), b.keys)
                                for b in branches))
        return {'B': tree, 'C': closed}
    return {'G': tree, 'Count': count}
