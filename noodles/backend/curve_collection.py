"""Pass through typed curves or expose a mixed selection of native curves."""
from .curves import CurveInput, input_tree, normalize_curve_state
from .datatree import Branch, DataTree, topology
from .surface_reference import (MAX_REFERENCE_ARCHIVES, MAX_REFERENCE_OBJECTS,
                                SURFACE_REFERENCE_KIND, surface_reference_from_wire)


CURVES = 'curves'
CURVES_INPUT = CurveInput('C', 'Curves', 'curve')
CURVES_SPEC = {'class': 'CurvesNode', 'name': 'Curves', 'reference': True,
               'inputs': (CURVES_INPUT,), 'outputs': ('C',), 'primary': 'C'}


def normalize_state(data):
    state = normalize_curve_state(CURVES, data, spec=CURVES_SPEC, decoder=surface_reference_from_wire,
                                  reference_kind=SURFACE_REFERENCE_KIND)
    records = state['references']
    if (len(records) > MAX_REFERENCE_OBJECTS or
            sum(len(record['recipe']['brep']) for record in records) > MAX_REFERENCE_ARCHIVES):
        raise ValueError('Curve references exceed the archive or object limit.')
    if any(record['recipe']['native_kind'] != 'curve' for record in records):
        raise ValueError('Curves accepts only curve references.')
    return state


def evaluate(parameters, inputs):
    state = normalize_state(parameters)
    modes = state['tree_modes']
    if state['mode'] == 'generate':
        return {'C': input_tree(inputs['C'], CURVES_INPUT, modes.get('C', 'none'))}
    if parameters.get('reference_error'):
        raise ValueError(parameters['reference_error'])
    values = tuple(surface_reference_from_wire(record['recipe']) for record in state['references'])
    if not values:
        raise ValueError('Select native curves in Serpentine, then click Set reference.')
    tree = DataTree((Branch((0,), values, tuple(value.key for value in values)),))
    return {'C': topology(tree, modes.get('References', 'none'))}
