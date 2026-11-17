# Grid Reference and related nodes

## Grid Reference

To reference a rectangular, triangular, hexagonal, or radial grid, set a node of the same type to **Reference**, select the existing grid in Serpentine3D, and click **Set reference**. The source must be a regular compound created by the matching NoodleS node or grid command. If a compound contains several grids, the node retains their stored paths and slot keys. Multiple owners get distinct path prefixes.

Downstream outputs reflect supported CAD edits, including movement, rotation, and uniform scaling. Rectangular grids also support unequal spacing changes along perpendicular axes. A connected size, cell count, plane, or origin can drive the existing object. The bridge validates the current topology before rebuilding it with the same scene identity and attributes. Reopening the scene resolves the owner from its persistent marker and each grid from its slot key.

**Move** can translate a single referenced grid in place through **G**. For selected parts, connect **P**, **C**, or **E** to **Move GH** to publish translated copies. Removing the Reference node leaves the source grid in the scene. [Grid outputs and grouping](grids.md), [Move settings](move-implementation.md)

## Plane Normal and Plane Preview

**Plane Normal** in Math uses origin O and normal Z to return a plane P. The defaults produce XY, and a zero normal raises an error. **Plane Preview** in Visual Helpers draws the plane around its origin and shows the X/Y axes in the Serpentine3D viewport. Properties controls Width, Height, Spacing, and Visible. The overlay leaves the scene history and construction plane unchanged. Its budget is 200 intervals per axis and 20,000 segments per client frame. [Preview lifecycle](vector-preview.md)

## Pipe

**Pipe** in Operations takes C (rail), R (radius), and S (Cap Ends, on by default). It uses the native Serpentine3D pipe factory and publishes one ParametricObject for the whole evaluation. **K** reports the resulting OCC shape type. Capping depends on the native operation and the shape.

## Loft Options

Connect **Loft Options.O → Loft.O** to set Smooth or Ruled, Closed, and Adjust. Direct connections to Loft.T, Cl, or A take precedence over the corresponding option. The Rebuild and Refit options report an error when enabled. [Loft](surface-operations.md)

## Expression

**Expression** in Math evaluates a formula over X, Y, and Z. Enter the formula in Properties, for example `x^2 - y^2`. The node can display this as x² − y² and stores the original editable formula. The supported syntax includes arithmetic, powers, real literals, constants such as pi and e, and approved functions such as sin, cos, sqrt, abs, and log. The inputs support Graft and Flatten. **R** returns the result.
