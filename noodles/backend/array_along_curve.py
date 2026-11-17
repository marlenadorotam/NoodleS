"""Arc-length array plans and typed transforms for a single geometry owner."""
import hashlib

from .curves import CurveInput, input_tree, matched_inputs, normalize_curve_state
from .datatree import Branch, DataTree, aligned
from .parametric import ParametricObject
from .pull import request_signature
from .rigid_motion import from_wire
from .splines import PendingGeometry


ARRAY_ALONG_CURVE = 'array_along_curve'
ORIENTATIONS = ('None', 'Free', 'Road-like', 'Stair-like')
MAX_COPIES = 2000
SPEC = {'class': 'ArrayAlongCurveNode', 'name': 'Array Along Curve', 'category': 'Operations',
        'reference': False, 'primary': 'G', 'inputs': (
            CurveInput('G', 'Geometry', 'move_geometry', optional=True),
            CurveInput('C', 'Rail Curve', 'sample_curve'),
            CurveInput('N', 'Count', 'division_count', 6),
            CurveInput('O', 'Orientation', 'orientation', 1, ORIENTATIONS),
        ), 'outputs': ('G', 'X')}


def normalize_state(data):
    state = normalize_curve_state(ARRAY_ALONG_CURVE, data, spec=SPEC)
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Array Along Curve uses connected inputs.')
    return state


def evaluate(parameters, inputs):
    from .moves import transform_geometry

    state = normalize_state(parameters)
    if 'C' not in inputs:
        raise ValueError('Connect a rail curve to C.')
    has_geometry = 'G' in inputs
    trees = [input_tree(inputs.get(d.port, state['parameters'].get(d.port)), d,
                        state['tree_modes'].get(d.port, 'none'), d.port not in inputs)
             for d in SPEC['inputs'] if not d.optional or d.port in inputs]
    matched = tuple(aligned(*matched_inputs(trees)))
    split = any(len(rows) > 1 for _, rows in matched)
    plans, layout, indices = [], [], {}
    total = 0
    for path, rows in matched:
        if not rows:
            layout.append((path + ((0,) if split else ()), None, (), None))
        for slot, (values, provenance) in enumerate(rows):
            source = values[0] if has_geometry else None
            curve, count, orientation = values[-3:]
            total += count
            if total > MAX_COPIES:
                raise ValueError(f'Array Along Curve supports up to {MAX_COPIES:,} placements per node.')
            sample = (curve, count, orientation)
            if sample not in indices:
                indices[sample] = len(plans)
                plans.append({'curve': curve.to_wire(), 'count': count, 'orientation': orientation})
            layout.append((path + ((slot,) if split else ()), source, provenance, indices[sample]))

    plan = {'operation': ARRAY_ALONG_CURVE, 'rows': plans}
    signature = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    if plans and detail.get('signature') != signature:
        pending = PendingGeometry('Waiting for curve array frames')
        tree = DataTree(tuple(Branch(path, (pending,) if index is not None else ())
                              for path, _, _, index in layout))
        return {'G': tree if has_geometry else DataTree(()), 'X': tree, '_sampling': {
            **{key: state[key] for key in ('project_uuid', 'node_uuid')}, 'signature': signature, 'plan': plan}}
    if plans and detail.get('error'):
        raise ValueError(detail['error'])
    measurements = detail.get('values', []) if plans else []
    if len(measurements) != len(plans) or any(len(values) != row['count'] for row, values in zip(plans, measurements)):
        raise ValueError('Native worker returned incomplete array frames.')
    sampled = [tuple(from_wire(matrix) for matrix in matrices) for matrices in measurements]
    shapes, transforms, complexity = [], [], 0
    for path, source, provenance, index in layout:
        motions = sampled[index] if index is not None else ()
        prefix = hashlib.sha256(repr((path, provenance)).encode()).hexdigest()[:24]
        keys = tuple(f'{prefix}:{i}' for i in range(len(motions)))
        transforms.append(Branch(path, motions, keys))
        if has_geometry:
            items = tuple(transform_geometry(source, motion, key) for motion, key in zip(motions, keys))
            complexity += sum(getattr(item, 'complexity', 1) for item in items)
            if complexity > 10000:
                raise ValueError('Array Along Curve exceeds the geometry recipe limit.')
            shapes.append(Branch(path, items, keys))
    return {'G': DataTree(tuple(shapes)), 'X': DataTree(tuple(transforms))}


def object_from_outputs(parameters, outputs):
    if '_sampling' in outputs or not outputs['G'].count:
        return None
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['G'], kind='transforms')
