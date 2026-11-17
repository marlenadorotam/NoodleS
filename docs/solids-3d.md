# 3D primitives

Find these nodes in **Library → Geometry**. Each Generate node publishes one ParametricObject containing all its results. Dimensions are finite and normally positive. Cone, Truncated Cone, and Pyramid also accept a negative height. Through P, provide a typed plane or a normal vector. The default plane is XY. A connected O is an absolute point. The disconnected XYZ settings give an offset from the plane origin.

| Node | Inputs besides P | Outputs |
| --- | --- | --- |
| Box | X width, Y depth, Z height, O base corner | G, O, X/Y/Z, P, C center, V volume, Count |
| Box from Center | X width, Y depth, Z height, O base center | G, O, X/Y/Z, P, C center, V volume, Count |
| Pyramid | X width, Y depth, H height, O base center, S geometry type | G, O, X/Y/H, P, Tip, V, S, Count |
| Sphere | R radius, O center | G, O, R, D diameter, P, V, Count |
| Ellipsoid | X/Y/Z radii, O center, S geometry type | G, O, X/Y/Z, P, V, S, Count |
| Torus | R major radius, r minor radius, O center | G, O, R/r, Out outer radius, In inner radius, P, N axis, V, Count |
| Cylinder | R radius, H height, O base center, S geometry type | G, O, R/H, P, D diameter, Top, C center, N axis, V, S, Count |
| Cone | R radius, H height, O base center, S geometry type | G, O, R/H, P, D diameter, Tip, N axis, V, S, Count |
| Truncated Cone | R base radius, r top radius, H height, O base center, S geometry type | G, O, R/r/H, P, Top, N axis, V, S, Count |
| Paraboloid | R rim radius, H height, O vertex | G surface, O, R/H, P, D diameter, Top rim center, N axis, Count |

## Dimensions and geometry types

Box defaults to 10 on each axis and grows from its base corner. Box from Center places X and Y symmetrically around the base center and grows Z from the base plane. Sphere defaults to radius 10. Torus defaults to major radius 20 and minor radius 5, and requires r < R. Cylinder, Cone, and Paraboloid default to radius 10 and height 20.

Cylinder, Cone, Truncated Cone, Pyramid, and Ellipsoid offer **Geometry Type** in Properties. A connected **S** uses True or 1 for Solid and False or 0 for Shell. Cylinder, Cone, and Truncated Cone in Shell mode publish their uncapped lateral face. Pyramid publishes four connected triangular sides. Ellipsoid produces a closed surface shell. These Shell results report zero volume.

Truncated Cone defaults to R = 10, r = 5, and H = 20. Both radii must be positive and different. Negative H flips the direction from the base plane while retaining the base and top radii. Pyramid places its apex a signed height H along the normal of P and defaults to H = 20. Ellipsoid defaults to X/Y/Z = 10/7/5 and scales a native OCC spherical surface along the plane axes. Paraboloid is an open surface of revolution with radial coordinate R × t and height H × t².

Each input supports Graft and Flatten. Within branches, lists must have equal lengths or length one. A flat list can distribute values across all tree slots if its length matches the total. A list sized for one row can repeat across rows. The worker prepares native BREP and display data and keeps the previous result visible while a valid replacement is prepared.

## Reference mode

Select a compatible complete native object and click **Set reference**. Connected inputs drive its supported parameters and disconnected inputs use scene values. The bridge validates the actual BREP before accepting a reference and preserves the source's identity during edits. [Reference editing](reference-editing.md)

Box and Box from Center read six orthogonal faces, including rotated boxes. Sphere and Torus require complete solids. Cylinder and Cone accept a complete solid or one complete lateral face. Truncated Cone recognizes the lateral face alone or both complete caps with it. Pyramid recognizes four connected triangular sides and an optional rectangular base. Paraboloid requires the complete quadratic profile. Ellipsoid accepts complete spheres and supported full ellipsoids, including verified non-uniformly scaled spheres. The bridge reads the center and principal axes from the shape.

For signed heights, the NoodleS commands and driven edits retain the sign using scene metadata. Where the sign is absent for a Truncated Cone reference, the native axis determines the direction and H is positive.

## Serpentine3D commands

| Command | Construction |
| --- | --- |
| `cylinderparam` or `cylinderex` | Cylinder with Solid or Shell |
| `coneparam` or `coneex` | Cone with signed height and Solid or Shell |
| `truncatedcone` | Two radii, signed height, Solid or Shell |
| `pyramid` | Rectangular base, signed height, Solid or Shell |
| `ellipsoideparam` | Three axial radii, Solid or Shell |
| `paraboloid` | Exact open paraboloid from vertex, radius, and height |

These commands use the same native shape factories and work with the NoodleS editor closed. [Shared publication](parametric-object-contract.md)
