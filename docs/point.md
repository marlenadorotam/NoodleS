# Point

**Library → Geometry → Point** has X, Y, and Z inputs and P, X, Y, and Z outputs. The coordinate outputs follow the same order and paths as P.

## Generate

Connect numbers or DataTrees to the coordinate inputs. Each disconnected coordinate defaults to 0 and is editable in Properties. A connected coordinate shows the incoming value as a read-only preview. Edit that value at its source.

The graph describes each point as data. The shared geometry worker builds vertices and display data and publishes them as one ParametricObject, even for a single point. Updating an existing result keeps its scene ID, name, layer, and color. A structure-only change can update the manifest while reusing the same shapes. Empty data produces an empty result.

## Reference

1. Select **Reference** in Properties.
2. Select one or more native point objects in Serpentine3D.
3. Click **Set reference points**.

References follow the captured selection order. Sources remain separate native points and editable in Serpentine3D. Vertices selected as subobjects of curves or solids and points inside a generated compound are outside this contract. An invalid capture leaves the previous selection binding intact.

Move a referenced point in Serpentine3D to update the node outputs. Connecting X, Y, or Z drives that coordinate of the source. Each disconnected axis retains its current scene value. One coordinate can drive a collection, or matching DataTree values can target individual points. Conflicting coordinates for the same source report an error before a scene change.

Outputs reflect the confirmed scene coordinates. A CAD edit updates those outputs without repeating an already acknowledged graph edit. A later change at a connected input applies the new coordinate. The source node's numeric setting stays as entered.

## DataTree and persistence

X, Y, and Z have independent Graft and Flatten controls. The captured **Points** collection has its own controls in Reference. Matching uses compatible paths, single-branch broadcasting, and repeat-last within branches. Empty input can produce empty results. Incompatible paths require correcting the input structure.

The graph saves its configured defaults, mode, and references. The scene saves generated geometry and manifest or the reference markers. Persisted markers let the bridge resolve sources after runtime IDs change. Missing or duplicate markers report a reference error.

Deleting a Reference node leaves native source points in place. Disabling, deleting, or changing a generating node to Reference detaches its own generated result from the scene. Closing the editor or replacing the open graph leaves scene geometry intact. The two apps maintain their own undo histories. [Reference editing](reference-editing.md), [Geometry deletion](geometry-deletion.md)
