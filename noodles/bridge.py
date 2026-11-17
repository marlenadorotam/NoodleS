"""Qt-free, bounded localhost transport, adapted from the former Ryven RPC client."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import time
import uuid

PROTOCOL_VERSION = 1
MAX_FRAME = 1048576
METHODS = ("hello", "status", "events.subscribe", "points.prepare", "points.job",
           "points.remove", "points.capture", "points.read", "points.drive")
METHODS += ('geometry.prepare', 'geometry.job', 'geometry.remove', 'geometry.capture', 'geometry.read', 'geometry.drive', 'geometry.pull', 'geometry.sample', 'geometry.move_refs', 'curves.capture', 'curves.read')
METHODS += ('previews.sync', 'geometry.surface_domain', 'geometry.surface_closest')
METHODS += ('geometry.boolean_apply', 'geometry.boolean_read')
METHODS += ('geometry.topology', 'geometry.uv_grid', 'geometry.population', 'geometry.tessellation')
METHODS += ('viewport.set', 'ui.panels.set')
METHODS += ('geometry.surface_structure',)
METHODS += ('geometry.mass_properties',)
METHODS += ('geometry.ungroup',)
METHODS += ('scene.link_graph',)


class BridgeError(RuntimeError):
    pass


class BridgeUnavailable(BridgeError):
    pass


class BridgeReplyTimeout(BridgeUnavailable):
    """The local socket connected, but the bridge did not answer in time."""


class BridgeProtocolError(BridgeError):
    pass


class BridgeRemoteError(BridgeError):
    pass


def scene_matches_graph(scene, project_uuid, link):
    """Allow a CAD save to precede a later save in the same graph history."""
    if scene.get("document_uuid") != link["document_uuid"]:
        return False
    saved = scene.get("graph_link") or {}
    if not saved:
        return link.get("accept_unpaired_scene", False)
    return saved.get("project_uuid") == project_uuid and (
        saved.get("revision") == link["revision"]
        or saved.get("revision") in link.get("previous_revisions", ())
    )


class BridgeClient:
    def __init__(self, descriptor=None, timeout=1.0, *, scene_scope=None, discover=None, session_id=None):
        self.descriptor = Path(descriptor) if descriptor else Path.home() / ".serpentine3d" / "noodles" / "bridge.json"
        self.timeout = timeout
        self.scene_scope = scene_scope
        self.discover = descriptor is None if discover is None else discover
        self.session_id = scene_scope[0] if scene_scope else session_id

    def for_scene(self, scope):
        return BridgeClient(self.descriptor, self.timeout, scene_scope=scope, discover=self.discover)

    def for_session(self, session_id):
        return BridgeClient(self.descriptor, self.timeout, discover=self.discover, session_id=session_id)

    @property
    def _instances(self):
        return self.descriptor.with_suffix(".instances")

    def _status_candidates(self, exclude=()):
        if not self.discover:
            return
        seen = set(exclude)
        for path in sorted(self._instances.glob("*.json")):
            if path.stem in seen:
                continue
            try:
                # A dead descriptor should not delay opening an unrelated graph.
                info = BridgeClient(path, min(self.timeout, 0.3), session_id=path.stem).call("status")
            except BridgeError:
                continue
            seen.add(path.stem)
            yield info
        # Older adapters publish only the shared descriptor.
        legacy = BridgeClient(self.descriptor, min(self.timeout, 0.3))
        try:
            session_id = legacy._endpoint()["session_id"]
            if session_id not in seen:
                yield legacy.for_session(session_id).call("status")
        except BridgeError:
            pass

    def read_status(self, method="status"):
        try:
            return self.call(method)
        except BridgeUnavailable:
            if not self.session_id:
                for info in self._status_candidates():
                    return info
            raise

    def find_scene(self, project_uuid, link, *, exclude=()):
        match = None
        for info in self._status_candidates(exclude):
            if scene_matches_graph(info["scene"], project_uuid, link):
                if match:
                    # Two live copies can carry the same saved identity.
                    return None
                match = info
        return match

    def _endpoint(self):
        try:
            path = self.descriptor
            if self.discover and self.session_id:
                session_path = self._instances / (str(uuid.UUID(self.session_id)) + ".json")
                if session_path.is_file():
                    path = session_path
            raw = path.read_bytes()
            if len(raw) > MAX_FRAME:
                raise ValueError("Descriptor is too large.")
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError("Invalid descriptor.")
            if record.get("host") != "127.0.0.1":
                raise ValueError("The bridge must use localhost.")
            if type(record.get("port")) is not int or not 1 <= record["port"] <= 65535:
                raise ValueError("Invalid bridge port.")
            if type(record.get("protocol")) is not int or record["protocol"] != PROTOCOL_VERSION:
                raise BridgeProtocolError("Incompatible bridge. Update the NoodleS plugin in Serpentine.")
            if not isinstance(record.get("token"), str) or len(record["token"]) < 20:
                raise ValueError("Invalid bridge token.")
            if not isinstance(record.get("session_id"), str) or not record["session_id"]:
                raise ValueError("Missing bridge session.")
            if self.session_id and record["session_id"] != self.session_id:
                raise BridgeUnavailable("The Serpentine connection changed.")
            return record
        except BridgeError:
            raise
        except FileNotFoundError as exc:
            raise BridgeUnavailable("Start Serpentine3D with the NoodleSBridge plugin installed.") from exc
        except (OSError, ValueError) as exc:
            raise BridgeUnavailable("Unable to read the local NoodleS bridge descriptor.") from exc

    def call(self, method="hello", params=None):
        if method not in METHODS:
            raise BridgeProtocolError("Unsupported bridge method.")
        endpoint = self._endpoint()  # Re-read on every call, including after Serpentine restarts.
        request_id = uuid.uuid4().hex
        request = {"method": method, "params": params or {}, "id": request_id,
                   "protocol": PROTOCOL_VERSION, "token": endpoint["token"]}
        if self.scene_scope:
            request["scene_token"] = self.scene_scope[1]
        frame = json.dumps(request, allow_nan=False).encode("utf-8") + b"\n"
        if len(frame) > MAX_FRAME:
            raise BridgeProtocolError("Point data exceeds the local bridge frame limit.")
        deadline = time.monotonic() + self.timeout
        sent = False
        try:
            with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=self.timeout) as connection:
                connection.settimeout(max(0.001, deadline - time.monotonic()))
                connection.sendall(frame)
                sent = True
                buffer = bytearray()
                while b"\n" not in buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    connection.settimeout(remaining)
                    chunk = connection.recv(min(8192, MAX_FRAME + 1 - len(buffer)))
                    if not chunk:
                        raise BridgeProtocolError("Serpentine closed the connection before replying.")
                    buffer.extend(chunk)
                    if len(buffer) > MAX_FRAME:
                        raise BridgeProtocolError("Bridge response exceeds the size limit.")
        except TimeoutError as exc:
            if sent:
                raise BridgeReplyTimeout("Serpentine did not respond in time.") from exc
            raise BridgeUnavailable("Serpentine is unavailable or did not respond in time.") from exc
        except OSError as exc:
            raise BridgeUnavailable("Serpentine is unavailable or did not respond in time.") from exc
        try:
            response = json.loads(bytes(buffer).split(b"\n", 1)[0])
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise ValueError("Mismatched response ID.")
            if "error" in response:
                if response.get("code") == "operation_failed":
                    raise BridgeRemoteError(str(response["error"]))
                raise BridgeProtocolError("Bridge rejected the request: " + str(response["error"]))
            result = response["result"]
            if result.get("application") != "Serpentine3D" or type(result.get("protocol")) is not int or result["protocol"] != PROTOCOL_VERSION:
                raise ValueError("Unexpected application or protocol.")
            if result.get("session_id") != endpoint["session_id"]:
                raise ValueError("The Serpentine session changed during connection.")
            if not {"status", "scene_summary"}.issubset(result.get("capabilities", [])):
                raise ValueError("Missing required bridge capabilities.")
            scene = result["scene"]
            if any(type(scene.get(key)) is not int or scene[key] < 0 for key in ("revision", "object_count")):
                raise ValueError("Invalid scene summary.")
            if type(scene.get("busy")) is not bool or (scene.get("path") is not None and not isinstance(scene["path"], str)):
                raise ValueError("Invalid scene state.")
            if not all(isinstance(result.get(key), str) for key in ("serpentine_version", "plugin_version")):
                raise ValueError("Missing bridge version information.")
            return result
        except BridgeError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BridgeProtocolError("Invalid response from the NoodleS bridge.") from exc

    def events(self, stop):
        endpoint = self._endpoint()
        request_id = uuid.uuid4().hex
        request = {"method": "events.subscribe", "params": {}, "id": request_id,
                   "protocol": PROTOCOL_VERSION, "token": endpoint["token"]}
        try:
            with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=self.timeout) as connection:
                connection.settimeout(0.5)
                connection.sendall(json.dumps(request).encode() + b"\n")
                buffer = bytearray()
                last = time.monotonic()
                first = True
                while not stop.is_set():
                    try:
                        chunk = connection.recv(8192)
                    except socket.timeout:
                        if time.monotonic() - last > 4:
                            raise BridgeUnavailable("Scene event stream timed out.")
                        continue
                    if not chunk:
                        raise BridgeUnavailable("Scene event stream closed.")
                    buffer.extend(chunk)
                    if len(buffer) > MAX_FRAME:
                        raise BridgeProtocolError("Scene event frame is too large.")
                    while b"\n" in buffer:
                        line, _, tail = buffer.partition(b"\n")
                        buffer = bytearray(tail)
                        data = json.loads(line)
                        last = time.monotonic()
                        if first:
                            if data.get("id") != request_id or data.get("result", {}).get("session_id") != endpoint["session_id"]:
                                raise BridgeProtocolError("Invalid event handshake. Update NoodleSBridge.")
                            first = False
                            yield {"event": "scene_changed"}
                        else:
                            if data.get("session_id") != endpoint["session_id"]:
                                raise BridgeProtocolError("Scene event session changed.")
                            yield data
        except (OSError, ValueError, AttributeError) as exc:
            raise BridgeUnavailable("Unable to receive Serpentine scene events.") from exc
