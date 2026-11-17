# Bounding Box and Surface Morph

Both nodes are in **Library → Operations**. Inputs support DataTree, Graft, and Flatten. Each node publishes one ParametricObject.

## Bounding Box

Connect geometry to **C**. **P** sets the axes for calculating the bounds and defaults to XY. **Per Object** creates a box for each object. **Union** creates one box per branch using a common plane. Use Flatten on C to enclose the entire input in one box.

**B** supplies the reference frame for Surface Morph. **G** supplies the box geometry. Planar geometry can produce a planar box, an axial line can produce a segment, and a point can produce a point result.

## Surface Morph

Connect the source to **G**, its reference box to **R**, and the target face to **S**. The source box's X and Y axes map to the surface's native **U** and **V** intervals. Omit either interval to use the corresponding full native range. **W** controls offset along the oriented surface normal in model units. With W disconnected, the box height is preserved from zero. A descending domain reverses its corresponding direction. The output **G** is the morphed geometry.

The target must be a face with a rectangular UV trim and no holes. Supported sources include points, planar curves parallel to the box's XY plane, planar-faced panels, and straight extrusions along the box's Z direction. Source profiles can include holes. Use a span shorter than a full period when wrapping a relief on a periodic surface. The worker constructs native curves and faces and checks the resulting topology.

### Place alternating panels on a cylinder

1. Connect a panel to **Duplicate Data**, then to **Dispatch**. Route A to **Weave.0** and B through **Mirror** to **Weave.1**. Connect an **XY Plane** to **Mirror.M** to reflect directly across that plane.
2. Connect **Weave.W** to **Surface Morph.G** and **Bounding Box.C**. Set Bounding Box to **Union** and connect **Bounding Box.B → Surface Morph.R**.
3. Set the **Cylinder** to **Shell** and connect **Cylinder.G** to **Surface Morph.S** and **Divide Domain².I**. Set the U and V subdivision counts. Create enough panel copies for the grid.
4. Connect **Divide Domain².S → Deconstruct Domain².I** and route U/V to the matching Surface Morph inputs. Use **Domain.D** for Surface Morph.W.

The Serpentine3D commands `boundingboxparam` and `surfacemorphparam` share the node factories and run with the editor closed. They use the active CPlane. The morph command computes a common source box for the selection. [UV tools](surface-uv.md)
