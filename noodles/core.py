"""Qt-free dataflow runtime for scalars, DataTree and deferred Point recipes.

The UI supplies a snapshot. Only inputs/parameters determine computation;
node positions, selection and canvas state have no computational meaning.
Failed results contain no outputs, so stale values cannot flow downstream.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from typing import Any

from .slider import normalize_slider_state
from .numeric import normalize_number_state
from .backend.point import evaluate_point, object_from_outputs, ParametricObject
from .backend.domain import evaluate_domain
from .backend.range import evaluate_range
from .backend.arithmetic import evaluate_arithmetic
from .backend.math_nodes import MATH_SPECS, evaluate_math
from .backend.geometry import GEOMETRY_SPECS, evaluate_geometry, geometry_object_from_outputs
from .backend.splines import PendingGeometry
from .backend.datatree import DataTree
from .backend.list_nodes import PASS_LIST_BINDINGS, evaluate_list
from .backend.curve_sampling import SORT_ALONG_CURVE
from .backend.data_helpers import normalize_data_helper
from .backend.reference_drive import REFERENCE_SPECS, build_reference_drive
from .backend.moves import MOVE_SPECS,evaluate_move,source_bindings,apply_effects,inactive_motion_ports
from .backend.operations import evaluate_operation
from .backend.fillet_edges import FILLET_EDGE, inactive_ports as inactive_fillet_ports
from .backend.curve_collection import CURVES
from .backend.previews import HIDE, evaluate_hide, normalize_preview_state
from .backend.fillet_curves import FILLET, FILLET_PARAMETRIC, native_plan as native_fillet_plan
from .backend.booleans import (NATIVE_SCENE_OPERATIONS, SHOW_PARENT_OPERATIONS, hidden_parents,
                               native_boolean_outputs, native_boolean_plan)


@dataclass(frozen=True)
class Connection:
    node_id: str
    output: str


@dataclass(frozen=True)
class NodeSpec:
    id: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Connection] = field(default_factory=dict)
    disabled: bool = False


@dataclass(frozen=True)
class NodeResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    blocked: bool = False
    parametric_object: ParametricObject | None = None
    bindings:dict=field(default_factory=dict)
    movements:tuple=()
    motion_errors:tuple=()
    reference_drive: dict | None = None
    hidden_parents: tuple = ()
    boolean_plan: dict | None = None
    action_error: str | None = None


@dataclass(frozen=True)
class Evaluation:
    results: dict[str, NodeResult]
    computed: tuple[str, ...]
    revision: int
    reference_moves:tuple=()
    frozen_owners:frozenset=frozenset()


def number(value: Any) -> float:
    if type(value) not in (int, float):
        raise ValueError("Expected a single number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("The number must be finite.")
    return value


def compute(operation: str, parameters: dict, inputs: dict) -> dict:
    if operation in GEOMETRY_SPECS:
        return evaluate_geometry(operation, parameters, inputs)
    if operation in MATH_SPECS:
        return evaluate_math(operation, parameters, inputs)
    if operation == "slider":
        return {"Number": normalize_slider_state(parameters)["value"]}
    if operation == "number":
        return {"Number": normalize_number_state(parameters)["value"]}
    if operation in ("addition", "multiplication"):
        return evaluate_arithmetic(operation, parameters, inputs)
    if operation == "domain":
        return evaluate_domain(parameters, inputs)
    if operation == "range":
        return evaluate_range(parameters, inputs)
    if operation == "point":
        if "mode" in parameters:
            return evaluate_point(parameters, inputs)
        # Legacy scalar snapshots remain readable; new Point always supplies mode.
        return {"Point": tuple(number(inputs[axis]) for axis in ("X", "Y", "Z"))}
    if operation == "watch":
        return {"Value": inputs["Value"]}
    raise ValueError("Unknown operation: " + operation)


REQUIRED_INPUTS = {
    "number": (), "slider": (), "addition": ("A", "B"),
    "multiplication": ("A", "B"), "point": ("X", "Y", "Z"),
    "watch": ("Value",), "domain": ("A", "B"), "range": ("D", "N"),
}
REQUIRED_INPUTS.update({op: tuple(i.port for i in spec["inputs"]) for op, spec in MATH_SPECS.items()})
REQUIRED_INPUTS.update({op: tuple(i.port for i in spec['inputs']) for op, spec in GEOMETRY_SPECS.items()})


class GraphEngine:
    """Topological evaluation with a cache of exact input snapshots.

    Synchronous for numeric/tree operations and lightweight recipes. Native
    geometry is materialized by the separate Serpentine adapter worker.
    """

    def __init__(self):
        self._cache: dict[str, tuple[Any, NodeResult]] = {}
        self.revision = 0

    def evaluate(self, nodes: list[NodeSpec]) -> Evaluation:
        self.revision += 1
        specs = {node.id: node for node in nodes}
        if len(specs) != len(nodes):
            raise ValueError("Duplicate node identifier.")
        results: dict[str, NodeResult] = {}
        children = {key: [] for key in specs}
        indegrees = {key: 0 for key in specs}
        for node in nodes:
            parents = {ref.node_id for ref in node.inputs.values() if ref.node_id in specs}
            indegrees[node.id] = len(parents)
            for parent in sorted(parents):
                children[parent].append(node.id)
        ready = deque(sorted(key for key, degree in indegrees.items() if not degree))
        computed = []
        while ready:
            key = ready.popleft()
            node = specs[key]
            inputs, error, blocked = {}, None, False
            if node.disabled:
                error, blocked = "Node disabled.", True
            elif node.operation not in REQUIRED_INPUTS:
                error = "Unknown operation: " + node.operation
            else:
                optional = node.operation in ("domain", "range") or (node.operation == "point" and "mode" in node.parameters) or node.operation in GEOMETRY_SPECS
                ports = tuple(node.inputs) if optional else REQUIRED_INPUTS[node.operation]
                if node.operation in GEOMETRY_SPECS:
                    if node.parameters.get('mode') == 'reference':
                        ports = tuple(node.inputs) if node.operation in REFERENCE_SPECS else ()
                    else:
                        ports = tuple(dict.fromkeys((*[i.port for i in GEOMETRY_SPECS[node.operation]['inputs'] if i.default is None and not i.optional], *node.inputs)))
                if node.operation in MATH_SPECS:
                    required = tuple(i.port for i in MATH_SPECS[node.operation]["inputs"] if not i.defaults)
                    ports = tuple(dict.fromkeys((*required, *node.inputs)))
                if node.operation in NATIVE_SCENE_OPERATIONS and node.parameters.get('boolean_records'):
                    ports = tuple(port for port in ports if port in ('N', 'R')) if node.operation == FILLET else ()
                inactive = (*inactive_motion_ports(node.operation, node.inputs),
                            *inactive_fillet_ports(node.operation, node.parameters.get('parameters', {})))
                if inactive:
                    ports = tuple(port for port in ports if port not in inactive)
                for port in ports:
                    ref = node.inputs.get(port)
                    if ref is None:
                        error = "Connect input " + port + "."
                        break
                    source = results.get(ref.node_id)
                    if source is None or source.error:
                        error, blocked = "No valid value at input " + port + ".", True
                        break
                    if ref.output not in source.outputs:
                        error, blocked = "Missing output " + ref.output + ".", True
                        break
                    inputs[port] = source.outputs[ref.output]
                    leaves = inputs[port].values() if isinstance(inputs[port], DataTree) else (inputs[port],)
                    if any(isinstance(value, PendingGeometry) for value in leaves):
                        error, blocked = 'Waiting for native curve measurement at input '+port+'.', True
                        break
            binding_input={}
            source_owners = set()
            if node.operation in MOVE_SPECS and 'G' in node.inputs:
                ref=node.inputs['G']
                parent=results.get(ref.node_id)
                if parent is not None:
                    binding_input=parent.bindings.get(ref.output,{})
                    if node.operation not in ('move_gh', 'orient'):
                        source_owners.update(b.owner for b in binding_input.values())
                        if parent.error:
                            source_owners.add(ref.node_id)
                            source_owners.update(parent.motion_errors)
            tracked = node.operation in NATIVE_SCENE_OPERATIONS or node.operation in SHOW_PARENT_OPERATIONS or node.operation == HIDE
            curve_passthrough = node.operation == CURVES and node.parameters.get('mode') != 'reference'
            sorted_points = node.operation == SORT_ALONG_CURVE
            if node.operation in PASS_LIST_BINDINGS or node.operation == 'watch' or tracked or curve_passthrough or sorted_points:
                for port, ref in node.inputs.items():
                    if sorted_points and port != 'P':
                        continue
                    if node.operation == FILLET_PARAMETRIC and port not in ('A', 'B'):
                        continue
                    if node.operation in ('array_polar', 'objects_on_points') and port != 'G':
                        continue
                    parent = results.get(ref.node_id)
                    if parent is not None:
                        port_bindings = parent.bindings.get(ref.output, {})
                        binding_input[port] = port_bindings
                        if not tracked:
                            source_owners.update(binding.owner for binding in port_bindings.values())
                            source_owners.update(parent.motion_errors)
            if node.operation == FILLET_EDGE and (ref := node.inputs.get('G')) and ref.node_id in results:
                binding_input['G'] = results[ref.node_id].bindings.get(ref.output, {})
            signature = (node.operation, dict(node.parameters), dict(inputs), error, blocked, binding_input, source_owners)
            cached = self._cache.get(key)
            if cached is not None and cached[0] == signature:
                result = cached[1]
            else:
                computed.append(key)
                records = node.parameters.get('boolean_records', ())
                if error and records and node.operation == FILLET and not node.disabled:
                    outputs, inherited = native_boolean_outputs(node, records)
                    result = NodeResult(outputs, bindings=inherited, action_error=error)
                elif error:
                    frozen = tuple(sorted(source_owners)) if not node.disabled else ()
                    result = NodeResult(error=error, blocked=blocked,motion_errors=frozen)
                else:
                    try:
                        if node.operation in NATIVE_SCENE_OPERATIONS:
                            outputs, inherited = native_boolean_outputs(node, records)
                            if node.operation == FILLET:
                                try:
                                    plan = native_fillet_plan(node.parameters, inputs, binding_input, records)
                                    result = NodeResult(outputs, bindings=inherited, boolean_plan=plan)
                                except ValueError as exc:
                                    if not records:
                                        raise
                                    result = NodeResult(outputs, bindings=inherited, action_error=str(exc))
                            else:
                                plan = None if records else native_boolean_plan(node.operation, node.parameters, inputs, binding_input)
                                result = NodeResult(outputs, bindings=inherited, boolean_plan=plan)
                        elif node.operation in MOVE_SPECS:
                            outputs,entity,bindings,movements=evaluate_move(node.operation,node.parameters,inputs,binding_input,node.id)
                            bindings.setdefault('G',{}).update(source_bindings(node,outputs,entity).get('G',{}))
                            result=NodeResult(outputs,parametric_object=entity,bindings=bindings,movements=movements)
                        elif node.operation in PASS_LIST_BINDINGS:
                            state = normalize_data_helper(node.operation, node.parameters)
                            outputs, inherited = evaluate_list(node.operation, state, inputs, binding_input)
                            result = NodeResult(outputs, bindings=inherited)
                        elif node.operation == HIDE:
                            outputs = evaluate_hide(normalize_preview_state(HIDE, node.parameters), inputs,
                                                    binding_input.get('G', {}))
                        elif node.operation in SHOW_PARENT_OPERATIONS or node.operation == FILLET_EDGE:
                            outputs = evaluate_operation(node.operation, node.parameters, inputs, binding_input)
                        else:
                            outputs = compute(node.operation, node.parameters, inputs)
                        if node.operation not in MOVE_SPECS and node.operation not in PASS_LIST_BINDINGS and node.operation not in NATIVE_SCENE_OPERATIONS:
                            entity = (object_from_outputs(node.parameters, outputs)
                                  if node.operation == "point" and "mode" in node.parameters else None)
                            if node.operation in GEOMETRY_SPECS:
                                entity = geometry_object_from_outputs(node.parameters, outputs)
                            drive = None
                            if node.operation in REFERENCE_SPECS and node.parameters.get('mode') == 'reference' and inputs:
                                drive = build_reference_drive(node.operation, node.parameters, inputs)
                            result = NodeResult(outputs, parametric_object=entity, bindings=source_bindings(node, outputs, entity),
                                                reference_drive=drive, hidden_parents=hidden_parents(node.parameters, binding_input)
                                                if node.operation in SHOW_PARENT_OPERATIONS else ())
                            if node.operation=='watch' and node.inputs:
                                result.bindings['Value'] = binding_input.get('Value', {})
                            if curve_passthrough:
                                result.bindings['C'] = binding_input.get('C', {})
                            if sorted_points and '_sampling' not in outputs:
                                result.bindings['P'] = binding_input.get('P', {})
                    except (ValueError, TypeError, OverflowError, KeyError) as exc:
                        frozen = tuple(sorted(source_owners))
                        result = NodeResult(error=str(exc),motion_errors=tuple(getattr(exc,'owners',frozen)))
                self._cache[key] = (signature, result)
            results[key] = result
            for child in children[key]:
                indegrees[child] -= 1
                if indegrees[child] == 0:
                    ready.append(child)
        for key in specs.keys() - results.keys():
            results[key] = NodeResult(error="Dependency cycle or a dependency on a cycle.", blocked=True)
            self._cache.pop(key, None)
        self._cache = {key: value for key, value in self._cache.items() if key in specs}
        results,reference_moves,frozen=apply_effects(results,nodes)
        return Evaluation(results, tuple(computed), self.revision,reference_moves,frozen)
