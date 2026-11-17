"""DataTree operations for sizing modules and extracting trimmed UV rails."""
import hashlib

from .arithmetic import finite_number
from .curves import CurveInput, dot, input_tree, sub, xyz
from .datatree import Branch, DataTree, MAX_ITEMS, finite
from .pull import request_signature
from .splines import PendingGeometry
from .surface_uv import FACE_INDEX, SURFACE, SurfaceUvView, _match, surface_selection


SCALE_NON_UNIFORM = 'scale_non_uniform'
SURFACE_ISOCURVES = 'surface_isocurves'
ISO_DIRECTIONS = ('Both', 'Along U', 'Along V')
MAX_ISO_LOCI = 1024
SCALE_SPEC = {'class': 'ScaleNonUniformNode', 'name': 'Scale Non-Uniform', 'inputs': (
    CurveInput('G', 'Geometry', 'move_geometry'), CurveInput('P', 'Scale Plane', 'plane', 'XY'),
    *(CurveInput(axis, f'{axis} Factor', 'number', 1.) for axis in 'XYZ')), 'outputs': ('G',)}
ISOCURVE_SPEC = {'class': 'SurfaceIsocurvesNode', 'name': 'Surface Isocurves', 'primary': 'U', 'inputs': (
    SURFACE, CurveInput('u', 'Fixed U (Curve Along V)', 'number', .5),
    CurveInput('v', 'Fixed V (Curve Along U)', 'number', .5),
    CurveInput('N', 'Normalized', 'boolean', True),
    CurveInput('D', 'Directions', 'choice_index', 0, ISO_DIRECTIONS), FACE_INDEX),
    'outputs': ('U', 'V', 'Count')}


def scale_factors(values):
    factors = xyz(values)
    if any(abs(value) < 1e-9 for value in factors):
        raise ValueError('Scale factors must have absolute value at least 1e-9.')
    return factors


def scale_matrix(frame, factors):
    axes = frame.axis_x, frame.axis_y, frame.normal
    return tuple(tuple(sum(f*axis[i]*axis[j] for axis, f in zip(axes, factors))
                       for j in range(3)) for i in range(3))


def scale_point(point, frame, factors):
    offset = sub(point, frame.origin)
    return tuple(finite(origin + dot(row, offset))
                 for origin, row in zip(frame.origin, scale_matrix(frame, factors), strict=True))


def iso_span(data):
    if not isinstance(data, (tuple, list)) or len(data) != 4 or data[0] not in ('U', 'V'):
        raise ValueError('Invalid isocurve span.')
    axis, fixed, start, end = data
    fixed, start, end = map(finite_number, (fixed, start, end))
    if start >= end:
        raise ValueError('Isocurve interval must increase.')
    return axis, fixed, start, end


def evaluate_isocurves(state, inputs, details):
    from .operations import OperationValue

    trees = [input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                        state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
             for d in ISOCURVE_SPEC['inputs']]
    layout, sources, queries = [], {}, []
    for path, matches in _match(*trees):
        groups = []
        for index, ((surface, u, v, normalized, direction, face), _) in enumerate(matches):
            if len(queries) >= MAX_ISO_LOCI:
                raise ValueError(f'Surface Isocurves accepts up to {MAX_ISO_LOCI:,} UV loci.')
            source, face = surface_selection(surface, face)
            row = {'source': sources.setdefault(source, len(sources)), 'face': face,
                   'u': u, 'v': v, 'normalized': normalized, 'direction': direction}
            if isinstance(surface, SurfaceUvView):
                domain = surface.domain
                row['domain'] = [domain.u.start, domain.u.end, domain.v.start, domain.v.end]
            key = hashlib.sha256(repr((path, source.key, index)).encode()).hexdigest()[:24]
            groups.append((key, source, face))
            queries.append(row)
        layout.append((path, groups))
    plan = {'operation': SURFACE_ISOCURVES, 'sources': [source.to_wire() for source in sources], 'rows': queries}
    signature = request_signature(plan)
    if queries and details.get('signature') != signature:
        pending = PendingGeometry('Waiting for native isocurves')
        tree = DataTree(tuple(Branch(path, (pending,) if groups else ()) for path, groups in layout))
        return {'U': tree, 'V': tree, 'Count': pending, '_sampling': {
            'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan}}
    if queries and details.get('error'):
        raise ValueError(details['error'])
    results = details.get('values', []) if queries else []
    if len(results) != len(queries):
        raise ValueError('Native Surface Isocurves returned incomplete results.')
    values, output, budget, count = iter(results), {'U': [], 'V': []}, MAX_ITEMS, 0
    for path, groups in layout:
        parts = {'U': [], 'V': []}
        for key, source, face in groups:
            for index, span in enumerate(next(values)):
                axis = span[0]
                part = OperationValue(f'{key}:{axis}:{index}', SURFACE_ISOCURVES, (source,),
                                      face_index=face, iso=span)
                budget -= part.complexity
                if budget < 0:
                    raise ValueError('Surface Isocurves exceeds the 10,000-item recipe budget.')
                parts[axis].append(part)
                count += 1
        for axis, items in parts.items():
            output[axis].append(Branch(path, tuple(items), tuple(part.key for part in items)))
    return {**{axis: DataTree(tuple(branches)) for axis, branches in output.items()}, 'Count': count}
