# 2D curves

**Library → Geometry** contains Circle, Ellipse, Rectangle, Line, Polyline, Arc, and Arc from Center. [Curve and InterpCurve](splines.md) build spatial splines with the same publishing and reference infrastructure.

| Node | Inputs | Outputs |
| --- | --- | --- |
| Circle | R radius, C center, P plane or normal | C curve, O center, R radius, N normal, P plane, L length, Count |
| Ellipse | A radius along local X, B radius along local Y, C center, P plane or normal | C curve, O center, A and B radii, N normal, P plane, L perimeter, Count |
| Rectangle | X width or domain, Y height or domain, C center, P plane or normal | C curve, O center, X width, Y height, P plane, N normal, V corners, L perimeter, Count |
| Line | A start, B end | C curve, A start, B end, L length, D direction from A to B, Count |
| Polyline | P vertices, C closed | C curve, V vertices, L length, Closed, Count |
| Arc | A start, M through point, B end | C curve, O center, R radius, P plane, N normal, A/M/B points, L length, S sweep in degrees, Count |
| Arc from Center | C center, R radius, A signed angle in degrees, P plane or normal | Same as Arc |

## Generate

Circle and Arc from Center default to radius 10. Arc from Center defaults to a 90° sweep. Ellipse defaults to radii 10 and 5. The radii follow the input plane axes even when B exceeds A. Both must exceed 1e-9. Equal radii are valid. The perimeter uses the complete elliptic integral. [NIST DLMF 19.8.1–6](https://dlmf.nist.gov/19.8.E6)

A connected center is an absolute point. The local XYZ fields specify a world-coordinate offset from the origin of P. P accepts a plane or an explicit normal vector. With P disconnected, select XY, XZ, or YZ. Rectangle defaults to width and height 10, centered on C. A domain supplies the positive side length and shifts the center by its midpoint along the corresponding local axis. Descending intervals are valid if their length is nonzero.

Polyline builds one curve per input branch. The Closed setting applies to the entire branch. Use at least two distinct consecutive vertices for an open polyline or three for a closed one. A duplicate closing vertex is removed automatically. Corner and vertex outputs preserve stable element keys.

Each input has its own Graft and Flatten controls. Matching can broadcast a singleton to multiple branches or distribute a full flat list across slots. A single branch uses repeat-last where supported. Ambiguous layouts produce an error. An evaluated node publishes one compound whether it produces one curve or hundreds. The worker can reuse unchanged OCC parts. [ParametricObject](parametric-object-contract.md)

## Reference

Select compatible whole curves in Serpentine3D and click **Set reference** in Properties. References follow source geometry when it moves, rotates, or changes size. Connected inputs can edit supported parameters of the sources. Disconnected inputs use current scene values.

Type checks use geometry. Circle requires a full circle, Arc requires a circular arc, Rectangle requires a rectangle, and Polyline requires straight segments. Ellipse accepts full ellipses and circles. It recognizes complete rational NURBS ellipses after non-uniform scaling, including supported curves wrapped in wires. Elliptical arcs and unrelated splines produce a type error. Native Ellipse references normally report the principal radius as A and the minor radius as B. An axis stored by a driven edit can preserve the input axis assignment.

Curve references use persistent markers in the scene. Invalid or duplicate markers produce an error. Reopening updates runtime IDs from those markers. A duplicated node starts with a fresh identity. A Reference node can be deleted while keeping the source objects and their scene attributes. [Reference editing](reference-editing.md)

The native canvas tests cover geometry and attributes across edits, save and reopen, and binding failures. [Curve tests](../tests/test_curves.py), [native tests](../tests/test_curve_native.py)
