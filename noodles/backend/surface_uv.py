"""UV views, typed intervals and read-only surface measurement plans."""
from dataclasses import dataclass
import math

from .arithmetic import VectorValue
from .curves import CurveInput, PlaneValue, input_tree, matched_inputs, normalize_curve_state
from .datatree import Branch, DataTree, MAX_ITEMS, aligned, as_tree
from .domain import DomainValue
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry


MAX_UV_MEASUREMENTS = 5000
MAX_UV_SAMPLES = 2500  # A sample carries up to 14 numbers in the bridge frame.
SURFACE_CLOSEST_POINT = 'surface_closest_point'
FACE_INDEX = CurveInput('F', 'Face Index (0 = Auto)', 'face_index', 0)
SURFACE = CurveInput('S', 'Surface', 'uv_surface')
DOMAIN_OR_SURFACE = CurveInput('I', 'Domain² / Surface', 'domain2_or_surface')
SURFACE_UV_SPECS = {
    'surface_domain': {'class': 'SurfaceDomainNode', 'name': 'Surface Domain',
                       'category': 'Operations', 'reference': False,
                       'inputs': (SURFACE, FACE_INDEX),
                       'outputs': ('U', 'V', 'D')},
    'deconstruct_domain2': {'class': 'DeconstructDomain2Node', 'name': 'Deconstruct Domain²',
                            'category': 'Operations', 'reference': False,
                            'inputs': (DOMAIN_OR_SURFACE, FACE_INDEX),
                            'outputs': ('U', 'V')},
    'divide_domain2': {'class': 'DivideDomain2Node', 'name': 'Divide Domain²',
                       'category': 'Operations', 'reference': False, 'primary': 'S',
                       'inputs': (DOMAIN_OR_SURFACE, CurveInput('U', 'U Count', 'grid_count', 10),
                                  CurveInput('V', 'V Count', 'grid_count', 10), FACE_INDEX),
                       'outputs': ('S',)},
    'reparameterize_surface': {'class': 'ReparameterizeSurfaceNode', 'name': 'Reparameterize Surface',
                               'category': 'Operations', 'reference': False,
                               'inputs': (SURFACE, CurveInput('U', 'New U Domain', 'uv_domain', optional=True),
                                          CurveInput('V', 'New V Domain', 'uv_domain', optional=True), FACE_INDEX),
                               'outputs': ('S',)},
    'surface_evaluate': {'class': 'SurfaceEvaluateNode', 'name': 'Surface Evaluate',
                         'category': 'Operations', 'reference': False, 'primary': 'P',
                         'inputs': (SURFACE, CurveInput('U', 'U Parameters', 'number', optional=True),
                                    CurveInput('V', 'V Parameters', 'number', optional=True),
                                    CurveInput('N', 'Normalized', 'boolean', False), FACE_INDEX),
                         'outputs': ('P', 'N', 'U', 'V', 'F', 'Count', 'u', 'v', 'Skipped')},
    SURFACE_CLOSEST_POINT: {'class': 'SurfaceClosestPointNode', 'name': 'Surface Closest Point',
                            'category': 'Operations', 'reference': False, 'primary': 'P',
                            'inputs': (CurveInput('P', 'Query Points', 'points'), SURFACE,
                                       CurveInput('N', 'Normalized', 'boolean', False), FACE_INDEX),
                            'outputs': ('P', 'U', 'V', 'D')},
}


@dataclass(frozen=True)
class Domain2Value:
    u: DomainValue
    v: DomainValue

    def __str__(self):
        return f'U [{self.u.start:.8g} → {self.u.end:.8g}] · V [{self.v.start:.8g} → {self.v.end:.8g}]'


UNIT_DOMAIN = DomainValue(0, 1)
UV_VALUE_PORTS = ('P', 'N', 'U', 'V', 'F', 'u', 'v')


@dataclass(frozen=True)
class SurfaceUvView:
    source: object
    face: int
    domain: Domain2Value

    def __str__(self):
        return 'Surface UV · ' + str(self.domain)


def is_uv_geometry(value):
    from .moves import RigidValue, TranslatedValue
    from .operations import OperationValue
    from .solids import SolidValue
    from .surface_reference import SurfaceReferenceValue

    while isinstance(value, (TranslatedValue, RigidValue)):
        value = value.source
    if isinstance(value, SurfaceReferenceValue):
        return value.native_kind != 'curve'
    return isinstance(value, (OperationValue, SolidValue, SurfaceReferenceValue, SurfaceUvView))


def checked_uv_domain(value):
    if not isinstance(value, DomainValue) or not 0 < value.end - value.start < math.inf:
        raise ValueError('UV domain requires a finite increasing interval.')
    return value


def surface_selection(value, face):
    if not isinstance(value, SurfaceUvView):
        return value, face
    if face and face != (value.face or 1):
        raise ValueError('Face Index conflicts with the selected UV view. Select the face before reparameterizing.')
    return value.source, value.face or face


def normalize_surface_uv_state(operation, data):
    state = normalize_curve_state(operation, data, spec=SURFACE_UV_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Surface UV nodes use connected data.')
    return state


def _match(*trees):
    trees = matched_inputs(trees)
    for path, rows in aligned(*trees):
        for tree in trees:
            branch = next((b for b in tree.branches if b.path == path), tree.branches[0])
            if rows and len(branch.items) not in (1, len(rows)):
                raise ValueError('Surface UV option lists must match or have one shared value.')
        yield path, rows


def _queries(state, parameters, sources, requests, *, samples=False, closest=False):
    limit = MAX_UV_SAMPLES if samples or closest else MAX_UV_MEASUREMENTS
    if len(requests) > limit:
        raise ValueError(f'Surface UV exceeds the {limit:,}-measurement limit.')
    if not requests:
        return (), {}
    plan = {'sources': [source.to_wire() for source in sources], 'rows': requests}
    if samples:
        plan['evaluate'] = True
    signature = request_signature(plan)
    record = parameters.get('sampling_details') or {}
    if record.get('signature') == signature:
        if record.get('error'):
            raise ValueError(record['error'])
        values = record['values']
        if len(values) != len(requests):
            raise ValueError('Surface UV returned incomplete measurements.')
        return values, {}
    pending = PendingGeometry('Waiting for closest surface points' if closest else
                              'Waiting for native surface evaluation' if samples else 'Waiting for native surface UV bounds')
    return (pending,) * len(requests), {'_sampling': {
        'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan,
    }}


def _bounds_value(value):
    if isinstance(value, PendingGeometry):
        return value
    a, b, c, d = value
    return Domain2Value(DomainValue(a, b), DomainValue(c, d))


def _domains(operation, state, parameters, trees, inputs):
    reparameterize = operation == 'reparameterize_surface'
    divide = operation == 'divide_domain2'
    sources, requests = {}, []
    layout, segment_count = [], 0
    for path, rows in _match(*trees.values()):
        items, keys = [], []
        for (value, *options, face), provenance in rows:
            keys.append('|'.join(provenance))
            if isinstance(value, Domain2Value):
                domain = value
            else:
                source, face = surface_selection(value, face)
                if isinstance(value, SurfaceUvView):
                    domain = value.domain
                else:
                    domain = len(requests)
                    requests.append({'source': sources.setdefault(source, len(sources)), 'face': face})
            if reparameterize:
                items.append((source, face, domain, *options))
            elif divide:
                u, v = options
                segment_count += u * v
                if segment_count > MAX_ITEMS:
                    raise ValueError(f'Divide Domain² exceeds the {MAX_ITEMS:,}-segment limit.')
                items.append((domain, u, v))
            else:
                items.append(domain)
        layout.append((path, items, keys))

    response, pending = _queries(state, parameters, sources, requests)
    bounds = tuple(map(_bounds_value, response))

    def domain(value):
        return bounds[value] if type(value) is int else value

    if divide:
        return {'S': _divide_domains(layout, domain), **pending}

    if reparameterize:
        def view(item):
            source, face, existing, u, v = item
            existing = domain(existing)
            if isinstance(existing, PendingGeometry):
                return existing
            if 'U' not in inputs and 'V' not in inputs:
                u = v = UNIT_DOMAIN
            return SurfaceUvView(source, face, Domain2Value(u or existing.u, v or existing.v))

        return {'S': DataTree(tuple(Branch(path, tuple(map(view, items)), keys)
                                    for path, items, keys in layout)), **pending}

    domains = DataTree(tuple(Branch(path, tuple(domain(value) for value in items), keys)
                             for path, items, keys in layout))
    result = {axis.upper(): DataTree(tuple(Branch(b.path, tuple(getattr(v, axis, v) for v in b.items), b.keys)
                                           for b in domains.branches)) for axis in ('u', 'v')}
    if operation == 'surface_domain':
        result['D'] = domains
    return {**result, **pending}


def _equal_intervals(domain, count):
    checked_uv_domain(domain)
    start, end = domain.start, domain.end
    points = [start + (end - start) * (index / count) for index in range(count)] + [end]
    if any(a >= b for a, b in zip(points, points[1:])):
        raise ValueError('The UV span is too small for this many representable intervals.')
    return tuple(DomainValue(a, b) for a, b in zip(points, points[1:]))


def uv_cells(domain, u_count, v_count):
    u_intervals = _equal_intervals(domain.u, u_count)
    v_intervals = _equal_intervals(domain.v, v_count)
    for j, v in enumerate(v_intervals):
        for i, u in enumerate(u_intervals):
            yield i, j, Domain2Value(u, v)


def _divide_domains(layout, resolve_domain):
    branches = []
    for path, items, keys in layout:
        segments, segment_keys, occurrences = [], [], {}
        for (reference, u_count, v_count), key in zip(items, keys):
            domain = resolve_domain(reference)
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            if isinstance(domain, PendingGeometry):
                segments.append(domain)
                segment_keys.append(f'{key}:{occurrence}:pending')
                continue
            for i, j, cell in uv_cells(domain, u_count, v_count):
                segments.append(cell)
                segment_keys.append(f'{key}:{occurrence}:{i}:{j}')
        branches.append(Branch(path, segments, segment_keys))
    return DataTree(tuple(branches))


def _surface_selections(trees):
    selections = list(_match(trees['S'], trees['F'], trees['N']))
    split = any(len(rows) > 1 for _, rows in selections)
    branches = []
    for path, rows in selections:
        if not rows:
            branches.append(Branch(path + (0,) if split else path, ()))
        for index, (item, keys) in enumerate(rows):
            branches.append(Branch(path + (index,) if split else path, (item,), ('|'.join(keys),)))

    return DataTree(tuple(branches))


def _surface_row(selection, sources):
    value, face, normalized = selection
    source, face = surface_selection(value, face)
    row = {'source': sources.setdefault(source, len(sources)), 'face': face, 'normalized': normalized}
    if isinstance(value, SurfaceUvView):
        row['domain'] = [value.domain.u.start, value.domain.u.end, value.domain.v.start, value.domain.v.end]
    return row


def _sample_surfaces(state, parameters, trees):
    sources, requests, layout = {}, [], []
    for path, rows in aligned(_surface_selections(trees), trees['U'], trees['V']):
        keys = []
        for (selection, u, v), provenance in rows:
            requests.append({**_surface_row(selection, sources), 'u': u, 'v': v})
            keys.append(request_signature(provenance)[:24])
        layout.append((path, keys))

    response, pending = _queries(state, parameters, sources, requests, samples=True)
    return _sample_outputs(layout, iter(response), pending)


def _closest_points(state, parameters, trees):
    sources, requests, layout = {}, [], []
    for path, rows in aligned(_surface_selections(trees), trees['P']):
        keys = []
        for index, ((selection, point), provenance) in enumerate(rows):
            requests.append({**_surface_row(selection, sources), 'point': point.xyz})
            keys.append(request_signature((path, index, provenance))[:24])
        layout.append((path, keys))

    response, pending = _queries(state, parameters, sources, requests, closest=True)
    values = iter(response)
    outputs = {port: [] for port in ('P', 'U', 'V', 'D')}
    for path, keys in layout:
        columns = {port: [] for port in outputs}
        for key in keys:
            value = next(values)
            if isinstance(value, PendingGeometry):
                row = (value,) * len(outputs)
            else:
                row = (PointValue(key, value[:3]), *value[3:])
            for port, item in zip(columns, row, strict=True):
                columns[port].append(item)
        for port, items in columns.items():
            outputs[port].append(Branch(path, items, keys))
    return {**{port: DataTree(tuple(branches)) for port, branches in outputs.items()}, **pending}


def _sample_outputs(layout, values, pending):
    ports = {port: [] for port in UV_VALUE_PORTS}
    count = skipped = 0
    for path, keys in layout:
        columns = {port: [] for port in ports}
        kept = []
        for key in keys:
            value = next(values)
            if value is None:
                skipped += 1
                continue
            if isinstance(value, PendingGeometry):
                row = (value,) * len(ports)
            else:
                p = PointValue(key, tuple(value[:3]))
                n, du, dv = (VectorValue(tuple(value[i:i+3])) for i in (3, 6, 9))
                length = math.hypot(*du.xyz)
                frame = PlaneValue(p.xyz, tuple(v / length for v in du.xyz), n.xyz)
                row = (p, n, du, dv, frame, value[12], value[13])
                count += 1
            kept.append(key)
            for port, item in zip(ports, row):
                columns[port].append(item)
        for port in ports:
            ports[port].append(Branch(path, columns[port], kept))
    waiting = PendingGeometry('Waiting for native surface evaluation')
    return {**{port: DataTree(tuple(b)) for port, b in ports.items()},
            'Count': waiting if pending else count, 'Skipped': waiting if pending else skipped, **pending}


def evaluate_surface_uv(operation, parameters, inputs):
    state = normalize_surface_uv_state(operation, parameters)
    trees = {}
    for d in SURFACE_UV_SPECS[operation]['inputs']:
        if d.optional and d.port not in inputs:
            trees[d.port] = as_tree(None)
        else:
            trees[d.port] = input_tree(inputs.get(d.port, state['parameters'].get(d.port, [])), d,
                                       state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
    if operation == 'surface_evaluate':
        return _sample_surfaces(state, parameters, trees)
    if operation == SURFACE_CLOSEST_POINT:
        return _closest_points(state, parameters, trees)
    return _domains(operation, state, parameters, trees, inputs)
