# Delaunay

**Operations → Delaunay** triangulates each nonempty branch of **P** (Points) independently. Use at least three points per branch. **Pl** optionally sets the plane, and **B** optionally bounds the result. Provide one shared plane or boundary, or match them to the point branches. **C** returns closed contours and **Count** reports their number. Inputs support Graft and Flatten.

With no boundary, the result covers the convex hull of the points projected onto the working plane. With a boundary, the node uses its actual corners and adds edge samples at a spacing based on the input points. B accepts a closed straight-sided outline or a corresponding planar face. The outline may be concave. Curved boundaries and holes are outside this contract. Thin triangles are possible at sharp corners.

## Periodic U

Connect a Rectangle to **Populate 2D.R**, connect its points to **Delaunay.P**, and build a Planar Surface from the same rectangle. Connect that surface to **Delaunay.B** and **Map Surface.S**, and connect **Delaunay.C** to **Map Surface.C**. Enable **Periodic U** in Delaunay Properties. The two U borders share the same sampling at the seam. Rectangles aligned with the working plane are required for this mode.

Use a Cylinder in **Shell** mode as **Map Surface.T**. A rectangle with width 2πR and height H preserves proportions on the unrolled cylinder. For a full Sphere, the two V borders map to the poles. Scale distortion increases toward the poles.

## Delaunay Mesh

**Operations → Delaunay Mesh** returns indexed mesh data through **M**. In planar mode **P/Pl** determine connectivity, and the mesh retains the original XYZ coordinates of its vertices. With **Periodic U** enabled, connect **Rectangle.C → B** and place the input points in that rectangle's plane. The node returns normalized **U/V** in vertex index order. Triangles crossing the seam remain intact and share vertex indices. The sampler adds vertices on both V rims.

To build a faceted cylinder, connect U/V to **Surface Evaluate** in Normalized mode, use **Cylinder.G** in Shell mode as **S**, and supply its **P** output to **Construct Mesh.V**. Connect **Delaunay Mesh.M → Deconstruct Mesh.M**, then **Deconstruct Mesh.F → Construct Mesh.F**. Keep vertex order and branch structure when applying any offset based on the evaluated normals. Construct Mesh publishes one native mesh. The two cylinder rims remain open.

## Publication and budgets

Delaunay stores indexed contours and DataTree paths, then builds native OCC wires with shared edges on the worker. It publishes them together as one [ParametricObject](parametric-object-contract.md). The `delaunayparam` command in Serpentine3D uses the same calculation and runs with the editor closed. The evaluated result has a budget of 1,700 input points and 4,096 contours. Invalid input, including a seam that cannot be matched or near-coincident points, reports a problem while preserving the previous published result.

Mapping the contours to a curved surface adds work. In an isolated Serpentine3D viewport benchmark, publishing the planar periodic result for 800 points took 116 ms. Publishing the mapped result took 2.83 s for a sphere and 3.19 s for a cylinder. These measurements include display mesh preparation and depend on the scene and hardware. [Related indexed tessellation](voronoi.md)
