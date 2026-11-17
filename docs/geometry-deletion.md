# Deleting geometry and using Undo or Redo

Deleting a **Generate** node removes the ParametricObject it owns, including all parts. Deleting a **Reference** node removes the node and its binding from the graph while leaving the source objects in Serpentine3D. Closing NoodleS or opening another graph leaves the CAD scene intact.

Use **Ctrl+Z** to restore the node and its published object, including the object ID, exact BREP, display mesh, layer, name, color, ByLayer settings, visibility, lock, material and metadata. **Ctrl+Y** or **Ctrl+Shift+Z** deletes it again. If you change its scene attributes after Undo, the next Undo restores the latest attributes captured by Redo.

## Scene restoration

[The deleted geometry store](../noodles/backend/deleted_geometry.py) keeps one record per project, node and output within a native scene. It keeps references to the geometry and display mesh and copies mutable attributes. Undo reuses the shape and mesh if the recipe is unchanged. Otherwise the worker prepares a new shape under the same identity and attributes. It also prepares missing display meshes away from the GUI thread.

Restoration applies only to the deleted object. Changes to other objects and layers remain in place. Missing parent layers are recreated from their original IDs without overwriting existing layers or switching the active layer. A duplicate binding or occupied object ID triggers rollback. The NoodleS and Serpentine3D histories are separate. The deleted-object store is scoped to the current native document session and is retained across reconnection or bridge refresh within that session. The files do not carry that undo history into a new session.

## Busy or disconnected sessions

The service records the latest Delete, Undo or Redo intent and rejects results from superseded requests. A busy CAD command postpones deletion. Undo can cancel a queued deletion. Requests for the current graph retry after reconnection, and a repeat after a lost response preserves the original restoration record. Deletion errors appear in the status bar even after the node leaves the canvas.

The native checks in `tests/test_geometry_delete_native.py` exercise delete, restore, redo, layers, attributes, busy or disconnected sessions and rollback.
