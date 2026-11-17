"""Versioned graph files. No Python code or geometry is executed on load."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import uuid

from .slider import normalize_slider_state
from .numeric import normalize_number_state
from .backend.point import normalize_point_state
from .backend.domain import normalize_domain_state
from .backend.range import normalize_range_state
from .backend.arithmetic import normalize_arithmetic_state
from .backend.math_nodes import MATH_NODE_OPERATIONS, normalize_math_state
from .backend.geometry import GEOMETRY_NODE_OPERATIONS, normalize_geometry_state


class DocumentError(ValueError):
    pass


def validate_document(data: object, node_ports: dict) -> dict:
    if not isinstance(data, dict) or data.get("format") != "NoodleS":
        raise DocumentError("This is not a NoodleS graph file.")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise DocumentError("Unsupported NoodleS file version.")
    session = data.get("session")
    if not isinstance(session, dict) or not isinstance(session.get("nodes"), dict):
        raise DocumentError("The file does not contain a valid graph.")
    nodes = session["nodes"]
    if len(nodes) > 5000:
        raise DocumentError("This version supports a maximum of 5,000 nodes per file.")
    # Reconstruct only supported fields. Library internals and arbitrary widget
    # configuration from a file are not passed to the NodeGraphQt deserializer.
    source_graph = session.get("graph", {})
    if not isinstance(source_graph, dict):
        raise DocumentError("Invalid graph settings.")
    point_projects = []
    for candidate in nodes.values():
        if not isinstance(candidate, dict) or not isinstance(candidate.get("type_"), str):
            continue
        custom = candidate.get("custom", {})
        if (candidate["type_"].endswith(".PointNode") or candidate['type_'].rsplit('.', 1)[-1] in GEOMETRY_NODE_OPERATIONS) and isinstance(custom, dict):
            project = custom.get("project_uuid")
            if isinstance(project, str) and project:
                point_projects.append(project)
    try:
        project_uuid = str(uuid.UUID(source_graph.get("project_uuid") or next(iter(point_projects), str(uuid.uuid4()))))
    except (ValueError, TypeError, AttributeError):
        raise DocumentError("Invalid graph project UUID.")
    clean = {"nodes": {}, "connections": [], "graph": {"acyclic": True, "project_uuid": project_uuid}}
    if "scene_link" in source_graph:
        link = source_graph["scene_link"]
        try:
            name = link["scene_name"]
            if not isinstance(name, str):
                raise TypeError
            normalized = {
                "document_uuid": uuid.UUID(link["document_uuid"]).hex,
                "revision": uuid.UUID(link["revision"]).hex,
                "scene_name": name,
            }
            if "previous_revisions" in link:
                revisions = link["previous_revisions"]
                if not isinstance(revisions, list):
                    raise TypeError
                normalized["previous_revisions"] = list(dict.fromkeys(
                    uuid.UUID(revision).hex for revision in revisions
                ))
            if "accept_unpaired_scene" in link:
                flag = link["accept_unpaired_scene"]
                if type(flag) is not bool:
                    raise TypeError
                normalized["accept_unpaired_scene"] = flag
            clean["graph"]["scene_link"] = normalized
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DocumentError("Invalid Serpentine document link.") from exc
    point_ids = set()
    for key, node in nodes.items():
        if not isinstance(key, str) or not isinstance(node, dict):
            raise DocumentError("Invalid node record.")
        kind = node.get("type_")
        if not isinstance(kind, str) or kind not in node_ports:
            raise DocumentError("Unsupported node: " + str(kind))
        position = node.get("pos", [0, 0])
        if not isinstance(position, (list, tuple)) or len(position) != 2 or any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9 for v in position
        ):
            raise DocumentError("Invalid node position.")
        custom = node.get("custom", {})
        if not isinstance(custom, dict):
            raise DocumentError("Invalid node parameters.")
        props = {}
        if kind.rsplit('.', 1)[-1] in GEOMETRY_NODE_OPERATIONS:
            try:
                props.update(normalize_geometry_state(GEOMETRY_NODE_OPERATIONS[kind.rsplit('.', 1)[-1]], {**custom,
                    'node_uuid': custom.get('node_uuid') or str(uuid.uuid4()),
                    'project_uuid': custom.get('project_uuid') or project_uuid}))
                if props['project_uuid'] != project_uuid or props['node_uuid'] in point_ids:
                    raise ValueError('Geometry identity does not match this graph or is duplicated.')
                point_ids.add(props['node_uuid'])
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith(".PointNode"):
            try:
                props.update(normalize_point_state({**custom,
                    "node_uuid": custom.get("node_uuid") or str(uuid.uuid4()),
                    "project_uuid": custom.get("project_uuid") or project_uuid}))
                if props["project_uuid"] != project_uuid or props["node_uuid"] in point_ids:
                    raise ValueError("Point identity does not match this graph or is duplicated.")
                point_ids.add(props["node_uuid"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.rsplit(".", 1)[-1] in MATH_NODE_OPERATIONS:
            try:
                props.update(normalize_math_state(MATH_NODE_OPERATIONS[kind.rsplit(".", 1)[-1]], custom))
            except (ValueError, TypeError, OverflowError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith((".AdditionNode", ".MultiplicationNode")):
            try:
                props.update(normalize_arithmetic_state(custom))
            except (ValueError, TypeError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith(".RangeNode"):
            try:
                props.update(normalize_range_state(custom))
            except (ValueError, TypeError, OverflowError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith(".DomainNode"):
            try:
                props.update(normalize_domain_state(custom))
            except (ValueError, TypeError, OverflowError) as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith(".SliderNode"):
            try:
                props.update(normalize_slider_state(custom))
            except ValueError as exc:
                raise DocumentError(str(exc)) from exc
        elif kind.endswith(".NumberNode"):
            try:
                props.update(normalize_number_state(custom))
            except ValueError as exc:
                raise DocumentError(str(exc)) from exc
        elif "value" in custom:
            value = custom["value"]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise DocumentError("Value must be a finite number.")
            if abs(value) > 1e9:
                raise DocumentError("Value is outside the range supported by this node.")
            props["value"] = value
        if kind == "nodeGraphQt.nodes.BackdropNode":
            text = custom.get("backdrop_text", "")
            if not isinstance(text, str) or len(text) > 10000:
                raise DocumentError("Invalid backdrop description.")
            props["backdrop_text"] = text
        name = node.get("name", "Node")
        if kind.endswith(".PointNode") and name == "Point XYZ":
            name = "Point"
        if not isinstance(name, str) or len(name) > 500:
            raise DocumentError("Invalid node name.")
        if type(node.get("disabled", False)) is not bool:
            raise DocumentError("Invalid node state.")
        clean["nodes"][key] = {
            "type_": kind, "name": name, "pos": list(position),
            "disabled": node.get("disabled", False), "custom": props,
        }
        for attr in ("color", "border_color", "text_color"):
            if attr in node:
                color = node[attr]
                if not isinstance(color, (list, tuple)) or len(color) != 4 or any(
                    type(channel) is not int or not 0 <= channel <= 255 for channel in color
                ):
                    raise DocumentError("Invalid node color.")
                clean["nodes"][key][attr] = list(color)
        if kind == "nodeGraphQt.nodes.BackdropNode":
            for attr in ("width", "height"):
                size = node.get(attr, 300)
                if type(size) not in (int, float) or not math.isfinite(size) or not 1 <= size <= 1e9:
                    raise DocumentError("Invalid backdrop size.")
                clean["nodes"][key][attr] = size
    connections = session.get("connections", [])
    if not isinstance(connections, list) or len(connections) > 20000:
        raise DocumentError("Invalid connection list.")
    occupied = set()
    children = {key: [] for key in nodes}
    indegrees = {key: 0 for key in nodes}
    for connection in connections:
        if not isinstance(connection, dict):
            raise DocumentError("Invalid connection.")
        ends = {}
        for direction, port_index in (("in", 0), ("out", 1)):
            endpoint = connection.get(direction)
            if not isinstance(endpoint, (list, tuple)) or len(endpoint) != 2 or any(
                not isinstance(v, str) for v in endpoint
            ):
                raise DocumentError("Invalid connection endpoint.")
            key, port = endpoint
            if direction == "out" and nodes.get(key, {}).get("type_", "").endswith(".PointNode") and port == "Point":
                port = "P"
            if direction == "out" and nodes.get(key, {}).get("type_", "").endswith((".AdditionNode", ".MultiplicationNode")) and port == "Number":
                port = "R"
            if key not in nodes or port not in node_ports[nodes[key]["type_"]][port_index]:
                raise DocumentError("A connection references a missing port.")
            ends[direction] = [key, port]
        target = tuple(ends["in"])
        if target in occupied:
            raise DocumentError("An input has more than one source.")
        occupied.add(target)
        parent, child = ends["out"][0], ends["in"][0]
        children[parent].append(child)
        indegrees[child] += 1
        clean["connections"].append(ends)
    ready = [key for key, degree in indegrees.items() if degree == 0]
    count = 0
    while ready:
        key = ready.pop()
        count += 1
        for child in children[key]:
            indegrees[child] -= 1
            if indegrees[child] == 0:
                ready.append(child)
    if count != len(nodes):
        raise DocumentError("The file contains a dependency cycle.")
    return clean


def read_document(path: Path, node_ports: dict) -> dict:
    if path.stat().st_size > 20_000_000:
        raise DocumentError("The graph file is too large.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise DocumentError("Unable to read the JSON file.") from exc
    return validate_document(data, node_ports)


def write_document(path: Path, session: dict) -> None:
    """Replace only after a complete file was successfully flushed to disk."""
    data = {"format": "NoodleS", "schema_version": 1, "session": session}
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
