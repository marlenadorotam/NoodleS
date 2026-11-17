"""Common recipe registry and state/runtime dispatch; publication remains universal."""
from .curves import CURVE_SPECS, normalize_curve_state, evaluate_curve, curve_object_from_outputs, curve_from_wire
from .solids import SOLID_SPECS, normalize_solid_state, evaluate_solid, solid_object_from_outputs, solid_from_wire
from .grids import GRID_SPECS, normalize_grid_state, evaluate_grid, grid_object_from_outputs, grid_from_wire
from .previews import PREVIEW_SPECS, UV_GRID_PREVIEW, normalize_preview_state, evaluate_preview
from .operations import NATIVE_SCENE_SPECS, OPERATION_SPECS,normalize_operation_state,evaluate_operation,operation_object_from_outputs,operation_from_wire
from .moves import MOVE_SPECS, normalize_move_state, geometry_from_wire, evaluate_move

from .pull import PULL_SPEC, evaluate_pull, normalize_pull_state
from .curve_sampling import SAMPLING_SPECS, evaluate_sampling, normalize_sampling_state
from .data_helpers import DATA_HELPER_SPECS, normalize_data_helper, evaluate_data_helper
from .surface_reference import SURFACE_REFERENCE_KIND, surface_reference_from_wire
from .surface_uv import SURFACE_CLOSEST_POINT, SURFACE_UV_SPECS, evaluate_surface_uv, normalize_surface_uv_state
from .topology_operations import TOPOLOGY_OPERATIONS
from .population import POPULATION_SPECS, evaluate as evaluate_population, normalize_state as normalize_population
from . import curve_collection
from . import delaunay_node
from . import surface_structure
from . import mesh_nodes
from . import mass_properties
from . import array_along_curve
from . import penrose_node
from .operations import PLANE_SURFACE_SPEC, evaluate_plane_surface
from .parametric import ParametricObject

MEASUREMENT_METHODS = {'pull_point': 'geometry.pull', **dict.fromkeys(SAMPLING_SPECS, 'geometry.sample'),
                       array_along_curve.ARRAY_ALONG_CURVE: 'geometry.sample',
                       UV_GRID_PREVIEW: 'geometry.uv_grid',
                       penrose_node.PENROSE: 'geometry.tessellation',
                       **dict.fromkeys(POPULATION_SPECS, 'geometry.population'),
                       **dict.fromkeys(delaunay_node.TESSELLATION_SPECS, 'geometry.tessellation'),
                       **dict.fromkeys(surface_structure.SPECS, 'geometry.surface_structure'),
                       **dict.fromkeys(TOPOLOGY_OPERATIONS, 'geometry.topology'),
                       mesh_nodes.BREP_TO_MESH: 'geometry.topology',
                       **dict.fromkeys(mass_properties.MASS_SPECS, 'geometry.mass_properties'),
                       **dict.fromkeys(SURFACE_UV_SPECS, 'geometry.surface_domain'),
                       SURFACE_CLOSEST_POINT: 'geometry.surface_closest'}
GEOMETRY_SPECS = {'pull_point': PULL_SPEC, **SAMPLING_SPECS, **SURFACE_UV_SPECS, **POPULATION_SPECS, **DATA_HELPER_SPECS, **CURVE_SPECS, **SOLID_SPECS, **GRID_SPECS, **PREVIEW_SPECS, **OPERATION_SPECS, **NATIVE_SCENE_SPECS, **MOVE_SPECS}
GEOMETRY_SPECS[curve_collection.CURVES] = curve_collection.CURVES_SPEC
GEOMETRY_SPECS.update(delaunay_node.TESSELLATION_SPECS)
GEOMETRY_SPECS.update(surface_structure.SPECS)
GEOMETRY_SPECS.update(mesh_nodes.MESH_SPECS)
GEOMETRY_SPECS.update(mass_properties.MASS_SPECS)
GEOMETRY_SPECS[array_along_curve.ARRAY_ALONG_CURVE] = array_along_curve.SPEC
GEOMETRY_SPECS[penrose_node.PENROSE] = penrose_node.SPEC
GEOMETRY_SPECS['plane_surface'] = PLANE_SURFACE_SPEC
GEOMETRY_NODE_OPERATIONS = {spec['class']: op for op, spec in GEOMETRY_SPECS.items()}


def normalize_geometry_state(operation, data):
    if operation == penrose_node.PENROSE:
        return penrose_node.normalize_state(data)
    if operation == 'plane_surface':
        state = normalize_curve_state(operation, data, spec=PLANE_SURFACE_SPEC)
        if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
            raise ValueError('Plane Surface uses Plane and dimension inputs.')
        return state
    if operation == array_along_curve.ARRAY_ALONG_CURVE:
        return array_along_curve.normalize_state(data)
    if operation in mesh_nodes.MESH_SPECS:
        return mesh_nodes.normalize_state(operation, data)
    if operation in mass_properties.MASS_SPECS:
        return mass_properties.normalize_state(operation, data)
    if operation in surface_structure.SPECS:
        return surface_structure.normalize_state(operation, data)
    if operation in delaunay_node.TESSELLATION_SPECS:
        return delaunay_node.normalize_state(data, operation)
    if operation == curve_collection.CURVES:
        return curve_collection.normalize_state(data)
    if operation in NATIVE_SCENE_SPECS:
        state = normalize_curve_state(operation, data, spec=NATIVE_SCENE_SPECS[operation])
        if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
            raise ValueError('Connect source geometry through the inputs.')
        return state
    if operation == 'pull_point':
        return normalize_pull_state(data)
    if operation in POPULATION_SPECS:
        return normalize_population(operation, data)
    if operation in SAMPLING_SPECS:
        return normalize_sampling_state(operation, data)
    if operation in SURFACE_UV_SPECS:
        return normalize_surface_uv_state(operation, data)
    if operation in DATA_HELPER_SPECS:
        return normalize_data_helper(operation, data)
    if operation in MOVE_SPECS:
        return normalize_move_state(operation,data)
    if operation in OPERATION_SPECS:
        return normalize_operation_state(operation,data)
    if operation in PREVIEW_SPECS:
        return normalize_preview_state(operation,data)
    if operation in GRID_SPECS:
        return normalize_grid_state(operation, data)
    return (normalize_solid_state if operation in SOLID_SPECS else normalize_curve_state)(operation, data)


def evaluate_geometry(operation, parameters, inputs):
    if operation == penrose_node.PENROSE:
        return penrose_node.evaluate(parameters, inputs)
    if operation == 'plane_surface':
        return evaluate_plane_surface(normalize_geometry_state(operation, parameters), inputs)
    if operation == array_along_curve.ARRAY_ALONG_CURVE:
        return array_along_curve.evaluate(parameters, inputs)
    if operation in mesh_nodes.MESH_SPECS:
        return mesh_nodes.evaluate(operation, parameters, inputs)
    if operation in mass_properties.MASS_SPECS:
        return mass_properties.evaluate(operation, parameters, inputs)
    if operation in surface_structure.SPECS:
        return surface_structure.evaluate(operation, parameters, inputs)
    if operation in delaunay_node.TESSELLATION_SPECS:
        return delaunay_node.evaluate(parameters, inputs, operation)
    if operation == curve_collection.CURVES:
        return curve_collection.evaluate(parameters, inputs)
    if operation == 'pull_point':
        return evaluate_pull(parameters, inputs)
    if operation in POPULATION_SPECS:
        return evaluate_population(operation, parameters, inputs)
    if operation in SAMPLING_SPECS:
        return evaluate_sampling(operation, parameters, inputs)
    if operation in SURFACE_UV_SPECS:
        return evaluate_surface_uv(operation, parameters, inputs)
    if operation in DATA_HELPER_SPECS:
        return evaluate_data_helper(operation, parameters, inputs)
    if operation in MOVE_SPECS:
        return evaluate_move(operation, parameters, inputs)[0]
    if operation in OPERATION_SPECS:
        return evaluate_operation(operation,parameters,inputs)
    if operation in PREVIEW_SPECS:
        return evaluate_preview(operation,parameters,inputs)
    if operation in GRID_SPECS:
        return evaluate_grid(operation, parameters, inputs)
    return (evaluate_solid if operation in SOLID_SPECS else evaluate_curve)(operation, parameters, inputs)


def geometry_object_from_outputs(parameters, outputs):
    if parameters['primitive'] == penrose_node.PENROSE:
        return None if '_sampling' in outputs else penrose_node.object_from_outputs(parameters, outputs)
    if parameters['primitive'] == 'point_cylindrical':
        return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['P'])
    if parameters['primitive'] == 'plane_surface':
        return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['P'], kind='operations')
    if parameters['primitive'] == array_along_curve.ARRAY_ALONG_CURVE:
        return array_along_curve.object_from_outputs(parameters, outputs)
    if parameters['primitive'] in mesh_nodes.MESH_PUBLISHERS:
        return None if '_sampling' in outputs else mesh_nodes.object_from_outputs(parameters, outputs)
    if parameters['primitive'] in mesh_nodes.MESH_SPECS:
        return None
    if parameters['primitive'] in (surface_structure.BRACED_GRID, surface_structure.UV_PANELS,
                                    surface_structure.SURFACE_BOX):
        return None if '_sampling' in outputs else surface_structure.object_from_outputs(parameters, outputs)
    if parameters['primitive'] in delaunay_node.TESSELLATION_SPECS:
        return None if '_sampling' in outputs else delaunay_node.object_from_outputs(parameters, outputs)
    if parameters['primitive'] == curve_collection.CURVES and parameters['mode'] == 'generate':
        return None
    if parameters['primitive'] in TOPOLOGY_OPERATIONS:
        return None if '_sampling' in outputs else operation_object_from_outputs(parameters, outputs)
    if parameters['primitive'] in MOVE_SPECS or parameters['primitive'] in MEASUREMENT_METHODS:
        return None  # GraphEngine resolves ownership and in-place effects.
    if parameters['primitive'] in OPERATION_SPECS:
        return operation_object_from_outputs(parameters,outputs)
    if parameters['primitive'] in PREVIEW_SPECS or parameters['primitive'] in DATA_HELPER_SPECS:
        return None  # A viewport helper never owns CAD geometry.
    if parameters['primitive'] in GRID_SPECS:
        return grid_object_from_outputs(parameters, outputs)
    return (solid_object_from_outputs if parameters['primitive'] in SOLID_SPECS else curve_object_from_outputs)(parameters, outputs)


def recipe_from_wire(data):
    if data.get('kind') == SURFACE_REFERENCE_KIND:
        return surface_reference_from_wire(data)
    if data.get('kind') in ('translated','rigid_transform','grid_edit','point'):
        return geometry_from_wire(data)
    if data.get('kind') in OPERATION_SPECS:
        return operation_from_wire(data)
    if data.get('kind') in GRID_SPECS:
        return grid_from_wire(data)
    return (solid_from_wire if data.get('kind') in SOLID_SPECS else curve_from_wire)(data)
