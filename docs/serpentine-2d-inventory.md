# 2D construction in NoodleS and Serpentine3D

The following pairs list the NoodleS nodes and commonly corresponding native Serpentine3D commands. A graph can generate a curve or bind an existing compatible object and use the outputs downstream. [2D curves](curves-2d.md)

| NoodleS node | Native command | Graph construction |
| --- | --- | --- |
| Point | `point` | XYZ coordinates or a reference to selected native points |
| Line | `line` | Two endpoints |
| Polyline | `polyline` | One ordered branch of vertices, with a Closed setting |
| Circle | `circle` | Center, radius, and plane |
| Arc | `arc` | Start, through point, and end |
| Arc from Center | `arc` with its Center option | Center, radius, signed sweep angle, and plane |
| Ellipse | `ellipse` | Center and two radii along the local plane axes |
| Rectangle | `rectangle` | Two dimensions or domains, a center, and a plane |
| Curve | `curve` | NURBS from control points |
| InterpCurve | `interpcurve` | NURBS that passes through interpolation points |

Serpentine3D also offers two-point and three-point options in its circle tool, a Diameter option for ellipses, and Center and 3Point options for rectangles. These are options within the native command prompts. The table describes the graph inputs used by NoodleS.

Ellipse Reference accepts a full ellipse, including supported full rational NURBS representations. For mixed curve types or elliptical arcs, use **Curves** to reference the original geometry. Curve and InterpCurve also work in 3D. [Splines](splines.md)
