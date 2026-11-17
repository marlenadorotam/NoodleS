# Visual helpers in the Serpentine3D viewport

## Vector Preview

**Library → Visual Helpers → Vector Preview** draws a yellow arrow in the model viewport. The arrow starts at O and ends at O + V. Its displayed length represents the vector in model units, with a screen-sized arrowhead capped for short vectors.

| Input | Value | Disconnected setting |
| --- | --- | --- |
| O | Typed origin point | XYZ in Properties, default (0, 0, 0) |
| V | Typed vector | Connect Vector, Unit X, or another vector-producing node |
| S | Visibility | Visible, on by default |

Outputs **V**, **L**, and **Count** report the vector, its length, and the result count. Turning off Visible keeps the data outputs. Each input supports Graft and Flatten. Invalid vectors, including zero-length and non-finite values, report an error and retain the last valid overlay. Empty data clears the arrows. The limits are 256 arrows per node and 1,024 per client frame.

The arrows are session overlays in supported model viewport modes. They leave the CPlane, selection, scene history, and revision alone, and are excluded from CAD export. Serpentine3D's `vectorpreview` command accepts an origin and two points defining a vector. `vectorpreviewclear` clears the command's arrows in the current scene. Both commands work without an open editor.

## Hide

**Library → Visual Helpers → Hide** takes published or referenced geometry through **G**. It resolves scene bindings to whole native objects. Connecting grid points, for example, targets the grid's complete compound. Hide changes visibility in place and keeps the original layer, shape, and graph data.

Disconnect, disable, or delete Hide to release its claim. When several Hide or Show Parent controls hide the same source, the last one to release it restores the prior visibility. The bridge also retains the prior visibility if the scene is reopened from a save taken while the object was hidden.

## Other overlays

**Plane Preview** draws the plane's local grid and axes. **Reparameterize Surface Preview** draws surface subdivisions. **Text Tag** and **Dimension** draw screen-space annotations and use the scene's model units for dimension formatting. Text and dimensions support up to 256 items per node. [Plane Preview](grid-reference-and-next-steps.md), [UV preview](surface-uv.md#reparameterize-surface-preview)

## Session lifecycle

One preview service sends complete, revisioned frames using `previews.sync`. The bridge keeps them separate by scene and client. Newer frames supersede older ones. Closing the editor releases its overlays and Hide requests. If the process or connection disappears, its lease expires after about ten seconds. A reconnect restores previews from the current graph state. The .noodles file stores the node settings and wires. Overlay graphics themselves exist only in the active session. [Viewport diagnostics](../CONTRIBUTING.md#viewport-diagnostics)
