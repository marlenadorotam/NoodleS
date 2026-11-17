# Editing geometry in Reference mode

In NoodleS, Reference binds existing Serpentine3D objects. Choose **Reference**, select compatible geometry in Serpentine3D, and click **Set reference** in Properties. Point uses **Set reference points**. Reference sources remain editable in CAD. Removing the graph node leaves the sources in the scene.

## Driving native source parameters

Connect an input to drive the corresponding parameter. A disconnected input keeps the current scene value. Outputs come from the scene and update after a CAD edit. The stored Generate defaults apply when you switch back to Generate. Reference refreshes in the same session leave already acknowledged values alone. Reopening a graph can apply its connected values again.

| Node | Supported driving inputs |
| --- | --- |
| Point | X/Y/Z |
| Circle | R/C/P |
| Ellipse | A/B/C/P |
| Rectangle | X/Y/C/P |
| Line | A/B |
| Polyline | P/C |
| Arc | A/M/B |
| Arc from Center | C/R/A/P |
| Curve | P/D/C |
| InterpCurve | P/D/C/T/K |
| Primitives such as Box, Sphere, Cylinder, Cone, and Pyramid | See each primitive's parameters |
| Grid Rectangle, Triangle, Hexagon, and Radial | Plane, spacing, extents, and origin |

Some nodes, including **Curves**, **Planar Surface**, **Edge Surface**, and **Loft**, use Reference to expose the existing native result for downstream operations. [3D primitives](solids-3d.md), [Surface references](surface-references.md), [Grid Reference](grid-reference-and-next-steps.md#grid-reference)

Use Graft and Flatten for input structure. A Polyline, Curve, or InterpCurve definition uses one list of points per branch. For separate definitions on multiple references, group them by object and match paths. Ambiguous assignments and incompatible types report errors. An explicit point input takes precedence over the origin supplied by a connected plane.

When editing the same number of control poles on a Curve without changing its other settings, the bridge preserves the NURBS knots, weights, and trimmed range. InterpCurve exposes its native poles on CP. Supply P with interpolation points to rebuild it using new fit options. When K is disconnected, that rebuild uses Chord.

## Native updates and persistence

The bridge reads current BREP and prepares replacements on the OCC worker. The scene transaction replaces the shape while keeping its ID, attributes, and persistent markers. A missing source, duplicate marker, or type change is reported as a reference error. After reopening the saved scene, markers resolve the sources using the new runtime IDs. [Point](point.md), [2D curves](curves-2d.md), [Splines](splines.md)
