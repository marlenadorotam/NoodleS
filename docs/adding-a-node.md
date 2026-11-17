# Add a NoodleS node

Follow this guide when a user asks for a new node. Start by agreeing on its inputs,
outputs, defaults, and how it should handle single values, lists, and DataTrees.
Install or update the local editor using the [Windows setup guide](getting-started.md).
The same guide explains how to uninstall the editor and bridge.

## Add the operation and register its node

1. Pick an existing node in the same family as a template. For a pure numerical
   operation, follow **Square** in [backend/math_nodes.py](../noodles/backend/math_nodes.py).
   Add an operation key to `MATH_SPECS` with the class name, full English label,
   input descriptors, output keys, and defaults. Implement the operation in
   `evaluate_math` and reuse the existing input parsing and DataTree helpers.
   For instance, `map_values` applies an item-wise operation while keeping branch paths.
2. Add a `NumericMathNode` subclass in [math_nodes.py](../noodles/math_nodes.py)
   with `NODE_NAME` and `OPERATION`, then include it in `MATH_NODE_CLASSES`.
   The equivalent class tuple in the chosen family feeds `NODE_CLASSES` in
   [nodes.py](../noodles/nodes.py). The editor uses this registry for the Library,
   search and graph loading. Preserve published operation keys, class identifiers
   and port keys so saved `.noodles` files continue to open.
3. Add a short English description keyed by class name in
   [node_descriptions.py](../noodles/node_descriptions.py). Check the full English
   names of the input and output ports in [port_names.py](../noodles/port_names.py).
   The common node layout and Properties panel handle sizing, defaults and undo
   for nodes using the existing specs. Use the existing per-input **Graft** and
   **Flatten** controls where the node accepts trees.

## Add native geometry when needed

- Follow the nearest shape or operation in [backend/geometry.py](../noodles/backend/geometry.py).
  Register its spec, state validation, evaluator and output recipe through the same
  family. The editor keeps descriptions of geometry in the DataTree. The shared
  bridge worker prepares the OCC shapes and publishes all parts of a generating
  node as one ParametricObject. See the [ParametricObject contract](parametric-object-contract.md).
- If Serpentine3D is missing the operation, make a reusable shape factory in
  `noodles/backend/` and expose it via a Serpentine command registered by
  [NoodleSBridge.py](../noodles/serpentine_plugin/NoodleSBridge.py).
  The native command and the node use the same factory. For example, see
  [primitive_shapes.py](../noodles/backend/primitive_shapes.py).
- When a node supports the two modes, follow the [Reference editing contract](reference-editing.md).
  **Generate** publishes the node's own result. **Reference** reads or updates the
  selected scene objects using the existing binding, with input behavior defined by the node.

## Verify and load the change

- Run the relevant evaluator and Qt tests using `.\.venv\Scripts\python.exe`. Check a
  single value, multiple DataTree branches and invalid input. In the editor, add the node
  from the Library, connect it, change its Properties, then save and reopen an isolated
  test graph. Test native geometry in an isolated Serpentine3D scene. The
  [test setup](../CONTRIBUTING.md#run-tests) covers Qt and the native runtime.
- Save any open user documents before restarting the editor. For a change to code
  shared with the bridge, reinstall the bridge and run `noodlesrefresh` in Serpentine3D.
  Restart Serpentine3D if the change adds a command. Start NoodleS from that checkout.
