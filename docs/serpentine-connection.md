# NoodleSBridge connection

NoodleS runs in its own process. **NoodleSBridge** runs inside Serpentine3D and connects the graph to that app's scene and OpenCascade runtime. For installation, compatibility, and troubleshooting, see [Getting started](getting-started.md).

## Session and document selection

NoodleS connects automatically when a bridge is available. The status in the canvas header shows the connection state. Click it to reconnect, or use the corresponding connect and disconnect actions in the main menu. A manual disconnect pauses automatic retries. After connecting, isolated status timeouts are tolerated before showing a disconnect. An unavailable endpoint or invalid protocol response can be reported immediately.

The bridge records active sessions through descriptors in `~/.serpentine3d/noodles/bridge.instances/`. A compatibility descriptor is available at `~/.serpentine3d/noodles/bridge.json`. NoodleS uses document and session information to connect a linked graph when multiple CAD windows are open. Save both the .noodles file and the .serp file while connected, in either order, to persist the pair. The graph-document mismatch dialog lets you continue explicitly, choose another graph, or cancel. [Document pairing](getting-started.md)

Three identities serve different purposes. A bridge session identifies a running connection, a document identifier identifies the CAD model, and graph and node identifiers identify bindings within the model. The bridge checks the open scene when accepting and committing geometry updates.

## Transport and geometry requests

The bridge listens only on the local loopback interface. Protocol 1 uses newline-delimited JSON frames. Requests carry an ID, method, params, protocol version, and session token. Responses use the request ID and a result or error. The descriptor contains the endpoint and token. Keep descriptors out of logs, issue attachments, and shared graph files.

Hello and status return session information, supported capabilities, and a lightweight scene summary. Event subscriptions carry scene changes and heartbeats. Geometry requests use explicit allowlisted methods. The worker prepares BREP and display data, and scene mutations are applied on Qt after validation. The common frame limit is 1 MiB. [ParametricObject](parametric-object-contract.md)

The bridge tests use loopback sockets and a real Qt server to exercise timeouts, protocol compatibility, scene changes, and reconnect behavior. [Bridge tests](../tests/test_bridge.py)
