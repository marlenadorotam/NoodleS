"""DataTree contracts for native Brep topology and surface framing."""
import hashlib

from .curves import CurveInput, input_tree, line, normalize_curve_state
from .datatree import Branch, DataTree, MAX_ITEMS, aligned
from .parametric import ParametricObject
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry, integer
from .surface_uv import FACE_INDEX, SURFACE, _match, surface_selection


DECONSTRUCT = 'deconstruct_brep'
BRACED_GRID = 'braced_grid_1d'
UV_PANELS = 'uv_panels'
SURFACE_BOX = 'surface_box'
LINE_NETWORK = 'line_network'
MAX_MEMBERS = 6000
MAX_SOURCES = 240
MAX_DIVISIONS = 128
MAX_PANELS = 1024
SPECS = {
    DECONSTRUCT: {'class': 'DeconstructBrepNode', 'name': 'Deconstruct Brep',
                  'inputs': (CurveInput('B', 'Brep', 'geometry'),), 'outputs': ('F', 'E', 'V')},
    BRACED_GRID: {'class': 'BracedGrid1DStructureNode', 'name': 'Braced Grid 1-D Structure',
                  'inputs': (CurveInput('S', 'Surface', 'uv_surface'),
                             CurveInput('U', 'U Divisions', 'braced_grid_count', 10),
                             CurveInput('V', 'V Divisions', 'braced_grid_count', 10)),
                  'outputs': ('A', 'B', 'N')},
    UV_PANELS: {'class': 'UVPanelsNode', 'name': 'UV Panels', 'outputs': ('S', 'Count'),
                'inputs': (SURFACE, CurveInput('U', 'U Count', 'grid_count', 10),
                           CurveInput('V', 'V Count', 'grid_count', 10), FACE_INDEX)},
    SURFACE_BOX: {'class': 'SurfaceBoxNode', 'name': 'Surface Box', 'outputs': ('B', 'Count', 'Skipped'),
                  'inputs': (SURFACE, CurveInput('U', 'U Count', 'grid_count', 4),
                             CurveInput('V', 'V Count', 'grid_count', 4),
                             CurveInput('H', 'Normal Height', 'number', 1.), FACE_INDEX)},
}
for spec in SPECS.values():
    spec.update(category='Operations', reference=False, primary=spec['outputs'][0])


def divisions(value, label):
    return integer(value, label, 1, MAX_DIVISIONS)


def panel_count(u, v, previous=0, label='UV Panels'):
    count = previous + u * v
    if count > MAX_PANELS:
        raise ValueError(f'{label} supports up to {MAX_PANELS:,} U × V cells in total.')
    return count


def normalize_state(operation, data):
    state = normalize_curve_state(operation, data, spec=SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Connect native geometry through the inputs.')
    return state


def evaluate(operation, parameters, inputs):
    from .moves import geometry_wire
    from .operations import OperationValue

    spec = SPECS[operation]
    state = normalize_state(operation, parameters)
    trees = [input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                        state['tree_modes'].get(d.port, 'none'), default=d.port not in inputs)
             for d in spec['inputs']]
    if operation in (UV_PANELS, SURFACE_BOX):
        return evaluate_panels(operation, state, trees, parameters.get('sampling_details') or {})
    rows, layout, occurrences = [], [], {}
    for path, items in aligned(*trees):
        if not items:
            layout.append((path + (0,), None, None))
        for i, (values, keys) in enumerate(items):
            value = values[0]
            source, face = (value, 0) if operation == DECONSTRUCT else surface_selection(value, 0)
            provenance = path, keys, source.key, face
            count = occurrences.get(provenance, 0)
            occurrences[provenance] = count + 1
            key = hashlib.sha256(repr((provenance, count)).encode()).hexdigest()[:20]
            layout.append((path + (i,), source, key))
            if operation == DECONSTRUCT:
                rows.append({'shape': geometry_wire(value)})
            else:
                rows.append({'shape': geometry_wire(source), 'face': face, 'u': values[1], 'v': values[2]})
    if len(rows) > MAX_SOURCES:
        raise ValueError(f'Connect up to {MAX_SOURCES} geometry items.')
    plan = {'operation': operation, 'rows': rows}
    stamp = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if rows and detail.get('signature') != stamp:
        pending = PendingGeometry('Waiting for native topology' if operation == DECONSTRUCT else 'Waiting for the braced grid')
        tree = DataTree(tuple(Branch(path, (pending,) if key is not None else ()) for path, _, key in layout))
        return {**dict.fromkeys(spec['outputs'], tree), '_sampling': {
            'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'], 'signature': stamp, 'plan': plan}}
    if rows and detail.get('error'):
        raise ValueError(detail['error'])
    results = detail.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native worker returned incomplete surface data.')
    measured = iter(results)
    out = [[], [], []]
    for path, source, key in layout:
        groups = (), (), ()
        if source is not None:
            data = next(measured)
            if operation == DECONSTRUCT:
                faces, edges, points = data
                groups = (tuple(OperationValue(f'{key}:f:{i}', operation, (source,), piece_index=i,
                                               result_kind='surface') for i in range(faces)),
                          tuple(OperationValue(f'{key}:e:{i}', operation, (source,), piece_index=faces+i,
                                               result_kind='curve') for i in range(edges)),
                          tuple(PointValue(f'{key}:v:{i}', p) for i, p in enumerate(points)))
            else:
                vertices, primary, braces = data
                points = {i: xyz for i, xyz in vertices}
                def members(pairs):
                    return tuple(line(f'{key}:{a}:{b}', points[a], points[b]) for a, b in pairs)
                groups = (members(primary), members(braces),
                          tuple(PointValue(f'{key}:v:{i}', xyz) for i, xyz in vertices))
        for branches, group in zip(out, groups):
            branches.append(Branch(path, group, tuple(item.key for item in group)))
    return {port: DataTree(tuple(branches)) for port, branches in zip(spec['outputs'], out)}


def evaluate_panels(operation, state, trees, detail):
    from .moves import geometry_wire
    from .operations import OperationValue

    boxes = operation == SURFACE_BOX
    spec = SPECS[operation]
    sources, rows, layout, total = {}, [], [], 0
    for path, matches in _match(*trees):
        group = []
        for slot, (values, provenance) in enumerate(matches):
            surface, u, v, *height, face = values
            total = panel_count(u, v, total, spec['name'])
            source, face = surface_selection(surface, face)
            key = hashlib.sha256(repr((path, provenance, slot, face)).encode()).hexdigest()[:24]
            group.append((source, face, key))
            rows.append({'source': sources.setdefault(source, len(sources)), 'face': face, 'u': u, 'v': v})
            if boxes:
                rows[-1]['height'] = height[0]
        layout.append((path, group))
    if len(rows) > MAX_SOURCES:
        raise ValueError(f'Connect up to {MAX_SOURCES} geometry items.')
    plan = {'operation': operation, 'sources': [geometry_wire(source) for source in sources], 'rows': rows}
    stamp = request_signature(plan)
    if rows and detail.get('signature') != stamp:
        pending = PendingGeometry('Waiting for native ' + spec['name'])
        tree = DataTree(tuple(Branch(path, (pending,) if group else ()) for path, group in layout))
        outputs = dict.fromkeys(spec['outputs'], pending)
        return {**outputs, spec['primary']: tree, '_sampling': {
            'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'], 'signature': stamp, 'plan': plan}}
    if rows and detail.get('error'):
        raise ValueError(detail['error'])
    results = detail.get('values', []) if rows else []
    if len(results) != len(rows):
        raise ValueError('Native worker returned incomplete UV panel data.')
    measured = iter(results)
    branches, complexity = [], 0
    for path, group in layout:
        parts = []
        for source, face, key in group:
            for i, j, data in next(measured):
                part_key = f'{key}:{i}:{j}'
                part = (OperationValue(part_key, SURFACE_BOX, (), box_corners=data) if boxes else
                        OperationValue(part_key, 'isotrim', (source,), uv_trim=tuple(data), face_index=face))
                complexity += part.complexity
                if complexity > MAX_ITEMS:
                    raise ValueError(spec['name'] + ' exceeds the 10,000-recipe budget.')
                parts.append(part)
        branches.append(Branch(path, parts, tuple(part.key for part in parts)))
    tree = DataTree(tuple(branches))
    outputs = {spec['primary']: tree, 'Count': tree.count}
    if boxes:
        outputs['Skipped'] = total - tree.count
    return outputs


def object_from_outputs(parameters, outputs):
    if parameters['primitive'] == SURFACE_BOX:
        return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['B'], kind='operations')
    if parameters['primitive'] == UV_PANELS:
        return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['S'], kind=UV_PANELS)
    branches = []
    for a, b in zip(outputs['A'].branches, outputs['B'].branches):
        branches.append(Branch(a.path, a.items + b.items, a.keys + b.keys))
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], DataTree(tuple(branches)),
                            kind=LINE_NETWORK)


def panel_model_wire(model, header):
    from .moves import geometry_wire

    sources, branches = {}, []
    for branch in model.parts.branches:
        parts = [{'key': part.key, 'source': sources.setdefault(part.sources[0], len(sources)),
                  'trim': list(part.uv_trim), 'face': part.face_index} for part in branch.items]
        branches.append({'path': list(branch.path), 'parts': parts})
    return {**header, 'sources': [geometry_wire(source) for source in sources], 'branches': branches}


def panel_model_from_wire(data):
    from .curves import curve_object_from_wire
    from .moves import geometry_from_wire
    from .operations import OperationValue
    from .surface_uv import is_uv_geometry

    sources = data.get('sources')
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError('Invalid UV Panels sources.')
    budget = [MAX_ITEMS]
    geometry = tuple(geometry_from_wire(source, budget=budget) for source in sources)
    if not all(map(is_uv_geometry, geometry)):
        raise ValueError('UV Panels needs geometry with native faces.')

    def decode(record):
        index = record.get('source') if isinstance(record, dict) else None
        if type(index) is not int or not 0 <= index < len(geometry):
            raise ValueError('Invalid UV panel source.')
        return OperationValue(record.get('key'), 'isotrim', (geometry[index],),
                              uv_trim=record.get('trim'), face_index=record.get('face'))

    model = curve_object_from_wire(data, decoder=decode, kind=UV_PANELS)
    if model.parts.count > MAX_PANELS or sum(part.complexity for part in model.parts.values()) > MAX_ITEMS:
        raise ValueError('UV Panels exceeds the panel or recipe budget.')
    return model


def line_network_from_wire(data):
    from .curves import curve_object_from_wire, xyz

    vertices = data.get('vertices')
    if not isinstance(vertices, list) or len(vertices) > MAX_ITEMS:
        raise ValueError('Invalid line network vertices.')
    points = tuple(xyz(p) for p in vertices)

    def decode(record):
        pair = record.get('indices') if isinstance(record, dict) else None
        if (not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]
                or any(type(i) is not int or not 0 <= i < len(points) for i in pair)):
            raise ValueError('Invalid line network edge.')
        return line(record.get('key'), *(points[i] for i in pair))

    model = curve_object_from_wire(data, decoder=decode, kind=LINE_NETWORK)
    if model.parts.count > MAX_MEMBERS:
        raise ValueError('Too many members in the braced grid.')
    return model
