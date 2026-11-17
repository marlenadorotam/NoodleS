"""Deferred point recipes and a ParametricObject, without Qt/OCC/scene calls."""
from dataclasses import dataclass
import hashlib
import json
import uuid

from .datatree import Branch, DataTree, MAX_ITEMS, aligned, finite, topology
from .parametric import ParametricObject


@dataclass(frozen=True)
class PointValue:
    key: str
    xyz: tuple

    @property
    def kind(self):
        return 'point'

    def to_wire(self):
        return {'key':self.key,'kind':'point','xyz':list(self.xyz)}

    def __post_init__(self):
        if len(self.xyz) != 3:
            raise ValueError("A point needs three coordinates.")
        object.__setattr__(self, "xyz", tuple(finite(v) for v in self.xyz))


def normalize_point_state(data):
    mode = data.get("mode", "generate")
    if mode not in ("generate", "reference"):
        raise ValueError("Unknown Point mode.")
    identities = {}
    for name in ("project_uuid", "node_uuid"):
        raw = data.get(name)
        if raw is not None and not isinstance(raw, str):
            raise ValueError("Invalid Point UUID.")
        identities[name] = str(uuid.UUID(raw)) if raw else ""
    modifiers = data.get("tree_modes", {})
    if not isinstance(modifiers, dict) or set(modifiers) - {"X", "Y", "Z", "Points"}:
        raise ValueError("Invalid Point input modifiers.")
    if any(value not in ("none", "graft", "flatten") for value in modifiers.values()):
        raise ValueError("Invalid Point input modifier.")
    refs = data.get("references", [])
    if not isinstance(refs, list) or len(refs) > MAX_ITEMS:
        raise ValueError("Invalid Point reference collection.")
    clean_refs = []
    for record in refs:
        if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k]
                                                  for k in ("key", "id")):
            raise ValueError("Invalid Point reference.")
        if any(len(record[k]) > 256 for k in ("key", "id")):
            raise ValueError("Point reference key is too long.")
        xyz = record.get("xyz")
        if not isinstance(xyz, (list, tuple)) or len(xyz) != 3:
            raise ValueError("Invalid referenced coordinates.")
        name = record.get("name", "")
        if not isinstance(name, str) or len(name) > 1000:
            raise ValueError("Invalid referenced point name.")
        clean_refs.append({"key": record["key"], "id": record["id"], "name": name,
                           "xyz": [finite(v) for v in xyz]})
        if 'move_offset' in record:
            offset=record['move_offset']
            if not isinstance(offset,(list,tuple)) or len(offset)!=3:
                raise ValueError('Invalid reference Move offset.')
            clean_refs[-1]['move_offset']=[finite(v) for v in offset]
        if 'move_transform' in record:
            from .rigid_motion import from_wire
            clean_refs[-1]['move_transform'] = from_wire(record['move_transform']).to_wire()
    if len({r["key"] for r in clean_refs}) != len(clean_refs):
        raise ValueError("Duplicate Point reference key.")
    return {"mode": mode, **identities, "x": finite(data.get("x", 0)),
            "y": finite(data.get("y", 0)), "z": finite(data.get("z", 0)),
            "tree_modes": {key: value for key, value in modifiers.items() if value != "none"},
            "references": clean_refs}


def reference_tree(state):
    values = tuple(PointValue(r["key"], tuple(r["xyz"])) for r in state["references"])
    return topology(DataTree((Branch((0,), values, tuple(p.key for p in values)),)),
                    state["tree_modes"].get("Points", "none"))


def reference_drive(parameters, inputs):
    """Coordinate patches for existing keys; never duplicate a native object.

    Only connected axes are written. Output geometry still comes from live
    scene reads, so moving a point by mouse does not reassert an old input.
    """
    state = normalize_point_state(parameters)
    axes = tuple(axis for axis in ("X", "Y", "Z") if axis in inputs)
    updates = {}
    if axes:
        coordinates = [topology(inputs[axis], state["tree_modes"].get(axis, "none")) for axis in axes]
        for _, rows in aligned(reference_tree(state), *coordinates):
            for values, _ in rows:
                point = values[0]
                patch = {axis: finite(value) for axis, value in zip(axes, values[1:])}
                if point.key in updates and updates[point.key] != patch:
                    raise ValueError("Coordinate inputs give one referenced point multiple positions. Match the Points and axis tree structures.")
                updates[point.key] = patch
    return {"axes": list(axes), "updates": [
        {"key": record["key"], "coordinates": updates[record["key"]]}
        for record in state["references"] if record["key"] in updates]}


def evaluate_point(parameters, inputs):
    state = normalize_point_state(parameters)
    if state["mode"] == "reference":
        if not state["references"]:
            raise ValueError("Select points in Serpentine, then click Set reference points.")
        if parameters.get("reference_error"):
            raise ValueError(parameters["reference_error"])
        reference_drive(state, inputs)  # Validate driving inputs before any scene mutation.
        points = reference_tree(state)
    else:
        coordinates = [topology(inputs.get(axis, state[axis.lower()]), state["tree_modes"].get(axis, "none"))
                       for axis in ("X", "Y", "Z")]
        branches, occurrences = [], {}
        for path, rows in aligned(*coordinates):
            values = []
            for xyz, provenance in rows:
                signature = json.dumps(provenance)
                occurrence = occurrences.get(signature, 0)
                occurrences[signature] = occurrence + 1
                key = hashlib.sha256(f"{signature}:{occurrence}".encode()).hexdigest()[:24]
                values.append(PointValue(key, tuple(finite(v) for v in xyz)))
            branches.append(Branch(path, tuple(values), tuple(v.key for v in values)))
        points = DataTree(tuple(branches))
    result = {"P": points}
    for index, axis in enumerate(("X", "Y", "Z")):
        result[axis] = DataTree(tuple(Branch(b.path, tuple(p.xyz[index] for p in b.items), b.keys)
                                     for b in points.branches))
    return result


def object_from_outputs(parameters, outputs):
    source_refs = (tuple((r["key"], r["id"]) for r in parameters.get("references", []))
                   if parameters["mode"] == "reference" else ())
    return ParametricObject(parameters["project_uuid"], parameters["node_uuid"],
                            outputs["P"], parameters["mode"], source_refs)


def object_from_wire(data):
    if isinstance(data, dict) and data.get('kind') == 'uv_panels':
        from .surface_structure import panel_model_from_wire
        return panel_model_from_wire(data)
    if isinstance(data, dict) and data.get('kind') == 'meshes':
        from .mesh_nodes import object_from_wire as mesh_object_from_wire
        return mesh_object_from_wire(data)
    if isinstance(data, dict) and data.get('kind') == 'line_network':
        from .surface_structure import line_network_from_wire
        return line_network_from_wire(data)
    if isinstance(data, dict) and data.get('kind') in ('tessellation', 'penrose_p2'):
        from .tessellation import model_from_wire
        return model_from_wire(data)
    if isinstance(data, dict) and data.get('kind') == 'mapped_tessellation':
        from .tessellation import mapped_model_from_wire
        return mapped_model_from_wire(data)
    if isinstance(data,dict) and data.get('kind')=='transforms':
        from .moves import object_from_wire as moved_object_from_wire
        return moved_object_from_wire(data)
    if isinstance(data,dict) and data.get('kind')=='operations':
        from .operations import operation_object_from_wire
        return operation_object_from_wire(data)
    if isinstance(data, dict) and data.get('kind') == 'grids':
        from .grids import grid_object_from_wire
        return grid_object_from_wire(data)
    if isinstance(data, dict) and data.get('kind') == 'solids':
        from .solids import solid_object_from_wire
        return solid_object_from_wire(data)
    if isinstance(data, dict) and data.get("kind") == "curves":
        from .curves import curve_object_from_wire
        return curve_object_from_wire(data)
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or data.get("kind") != "points":
        raise ValueError("Unsupported ParametricObject schema.")
    state = normalize_point_state(data)
    if not state["project_uuid"] or not state["node_uuid"] or state["mode"] != "generate":
        raise ValueError("Invalid generated Point identity.")
    branches = data.get("branches")
    if not isinstance(branches, list) or len(branches) > MAX_ITEMS:
        raise ValueError("Invalid Point branches.")
    result = []
    for branch in branches:
        if not isinstance(branch, dict) or not isinstance(branch.get("points"), list):
            raise ValueError("Invalid Point branch.")
        values = []
        for point in branch["points"]:
            if not isinstance(point, dict) or not isinstance(point.get("key"), str) or not point["key"]:
                raise ValueError("Invalid generated Point key.")
            xyz = point.get("xyz")
            if not isinstance(xyz, list):
                raise ValueError("Invalid generated Point coordinates.")
            values.append(PointValue(point["key"], tuple(xyz)))
        result.append(Branch(branch.get("path", ()), tuple(values), tuple(v.key for v in values)))
    tree = DataTree(tuple(result))
    if len({p.key for p in tree.values()}) != tree.count:
        raise ValueError("Generated Point keys must be unique.")
    return ParametricObject(state["project_uuid"], state["node_uuid"], tree)
