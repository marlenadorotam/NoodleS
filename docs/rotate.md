# Rotate, Scale, and Mirror

Find these nodes in **Library → Operations**. Their in-place modes preserve source scene identity and attributes when the input has an owner. Copy modes publish a separate ParametricObject. The ports support Graft and Flatten, so different values can apply to matched items in a DataTree.

## Rotate

Rotate turns geometry around the normal of **P** through center **C**. C defaults to the origin and P defaults to XY. P accepts a plane or normal vector. **A** is the angle in degrees and defaults to zero. If **To** is connected, Rotate measures the angle from the plane's X axis to the projected direction from C to To. A connected A takes precedence. **Cp** (Copy) defaults to off. **G** returns the rotated geometry, **A** the angle used, and **Count** the item count.

Generated grids support rotation of the whole grid or selected parts. Conflicting rotations for a shared part report an error. To rotate a referenced grid in place, supply the whole G of one grid. Choose Copy to rotate selected parts independently.

## Scale

**G** accepts geometry, **C** sets the center, and **F** sets the uniform positive scale factor. They default to the origin for C and 1 for F. When F is disconnected, a connected **To** sets the factor from the distance to C. Zero distance or a nonpositive factor reports an error. Toggle **Cp** to keep the source and publish copies. Outputs are G, F, and Count.

## Mirror

Supply geometry on **G**. **S** and **E** define a line in the working orientation **P**. The reflection plane contains the line and is perpendicular to P. To reflect across a plane directly, connect it to **M** (Mirror Plane). The defaults use the X axis as the line and XY as P. Coincident endpoints or a line parallel to the normal of P are invalid. Use **K** (Keep Original) to retain the source and publish copies. Outputs are G and Count.

## Composition

Move, Rotate, Scale, and Mirror compose in graph order. For a generated owner the transforms apply to its recipe. For supported references, the bridge tracks the applied transform in metadata and applies a relative change, including after reopen. Reference driving while Rotate is active updates parameters in the base frame and reapplies the rotation. [Move and Move GH](move-implementation.md), [Reference editing](reference-editing.md)
