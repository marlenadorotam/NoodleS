# Hexagon Tiling

**Operations → Hexagon Tiling** fills a planar, straight-sided boundary with hexagonal cells. **B** accepts a closed polygon or a single planar face without holes. **S** is the distance between opposite sides of a cell and defaults to 5. **Pl** optionally sets the pattern axes. The node clips cells to the boundary and preserves DataTree branches. Inputs support Graft and Flatten.

- **C** returns every closed contour, including clipped cells.
- **H** returns complete hexagons, with their corresponding centers on **P**.
- **Count** reports the number of contours in C.

The result publishes native OCC curves as one ParametricObject. The shared budget is 4,096 contours and 8,192 vertices per result. Serpentine3D's `hexagontiling` command runs the same geometry factory with the editor closed.

## Periodic U

Enable **Periodic U** in Properties and use a rectangle aligned to the pattern axes. The cell spacing scales uniformly to fit a whole number of columns, so the two U borders share the same V positions along the seam. A seam-crossing cell contributes two closed fragments to C.

Connect C to **Map Surface.C**, the original rectangle's planar surface to **S**, and a cylindrical shell or sphere to **T**. A 2πR × H rectangle preserves proportions on the unrolled cylinder. On a sphere the proportions vary toward the poles.

## Honeycomb example

The graph constructs a cutting cell with three rhombi at its base using **Expression**, **Planar Surface**, and **Brep Join**. **Objects on Points** places cells at the tiling centers. A second set is inverted and shifted to the corners of the first lattice. The parametric Boolean Difference cuts both sets into the wax block, leaving shared walls and a central partition.

Defaults are 5.3 mm for Cell Size, 0.45 mm for Wall Thickness, and 18 mm for Comb Depth. Keep the CSV with the graph and open the paired scene to inspect the Honeycomb, Reverse Side, and Cut Edge views. [Honeycomb graph, scene, and CSV](../examples/honeycomb/), [Cell-base geometry](https://journals.iucr.org/a/issues/2025/02/00/uv5034/)
