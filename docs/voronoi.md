# Voronoi

**Operations → Voronoi** builds Voronoi cells for each branch of seed points on **P**. **Pl** optionally sets the working plane and **B** bounds the tessellation. Plane and boundary can be shared or matched by DataTree paths. Graft and Flatten are available at the inputs. **C** returns closed contours and **Count** reports their number.

Use a closed straight-sided outline or a single planar face without holes as B. Cells cover the boundary, including concave corners. With B disconnected, Voronoi uses a rectangle around the seeds with a margin equal to 5% of the largest planar extent on each side. A single seed requires an explicit B. The node accepts up to 1,800 seeds and returns at most 4,096 contours. **Populate 2D** has its own 10,000-point DataTree budget, including existing points.

## Periodic U

Set **Periodic U** in Properties and use a rectangle aligned to the UV axes. Neighboring copies of seed points influence the cells along the seam. Both U margins have matching V divisions. A seam-crossing cell produces two closed contour fragments, so Count can exceed the number of seeds.

1. Connect **Rectangle.C → Populate 2D.R** and connect the same rectangle to **Planar Surface.C**.
2. Connect **Populate 2D.P → Voronoi.P** and **Planar Surface.G → Voronoi.B** and **Map Surface.S**.
3. Connect **Voronoi.C → Map Surface.C** and set **Map Surface.T** to a **Cylinder** in Shell mode or a **Sphere**.

A 2πR × H rectangle preserves scale on the developed cylinder. A sphere compresses proportions near the poles. Contour-closing segments on the periodic seam remain visible when mapped.

## Publication and performance

The algorithm intersects half-planes to build the cells and checks coverage. Voronoi shares the indexed contour representation and native geometry worker used by [Delaunay](delaunay.md). The bridge publishes all resulting OCC contour wires as one ParametricObject. The `voronoiparam` command uses the same factory with the editor closed.

A local two-process benchmark measured from confirming the Populate 2D Count to the updated frame in Serpentine3D. At 1,800 seeds, the tested cylinder graphs took 3.72–3.78 s and the sphere graphs took 3.67–3.73 s. That was the highest count under the four-second target across all sampled cases. Rendering and rebuild time vary with geometry, density, and hardware.
