# Brep Join and Isotrim

Both nodes are in **Operations**, offer **Graft** and **Flatten** on inputs and publish each node's results as one ParametricObject.

## Brep Join

Input **B** collects faces, shells and solids per branch. Brep Join sews open parts along shared edges within the Serpentine3D tolerance. A closed enclosure becomes a solid. Disconnected parts and incoming solids remain separate output items. **B** returns geometry and **C** returns matching **Closed** flags on the same paths.

Connect **Deconstruct Brep.F → Brep Join.B** to sew the extracted faces. Use **Merge** to bring faces from **Loft**, **Planar Surface** or **Isotrim** into the same input. Apply **Flatten** to **B** when the branches should be sewn together. Send **B** to **Deconstruct Brep** or use the **C** flags to identify closed pieces for downstream solid operations.

**Join** and **Brep Join** expose **Show Parent** in Properties. It defaults to on, including in older files. Turn it off to hide the immediate source geometry, including surfaces passed through **Merge**. Earlier construction geometry retains its visibility. The output still recalculates and can be passed to **Move**. Turn the setting back on to restore visibility for sources that no other node is hiding.

## Isotrim

Connect a surface to **S**. **F** selects a face, with **0** selecting it automatically when the shape has just one face. Supply a Domain² on **D**, for instance from **Surface Domain.D**, or leave **D** disconnected and supply domains separately on **U** and **V**. **S** returns the trimmed surface.

Intervals use the input surface domain. To specify fractions such as 0–0.5, pass the surface through **Reparameterize Surface** with a 0–1 domain. For a grid of panels, connect **Divide Domain².S → Isotrim.D**. It supplies a UV rectangle for each panel.

Isotrim intersects the UV rectangle with the actual OCC face, preserving outer trims and holes and returning multiple pieces when needed. Empty or out-of-range cuts raise an error. Lists match faces and branches according to the [Surface UV](surface-uv.md) rules. The output can feed **Offset** or **Brep Join**.

The Serpentine3D commands `brepjoinparam` and `isotrimparam` use the same shape builders. The Isotrim command takes native parameter intervals.
