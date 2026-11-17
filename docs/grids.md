# Grids

**Library → Geometry** includes **Grid Rectangle**, **Grid Triangle**, **Grid Hexagon**, and **Grid Radial**. Generate publishes one native ParametricObject per node even when the input tree specifies several grids. Points, cells, and edges are available independently as graph data. [Reference mode](grid-reference-and-next-steps.md#grid-reference)

| Node | Size and count inputs | Defaults |
| --- | --- | --- |
| Grid Rectangle | Sx and Sy spacing, Ex and Ey cell counts | 10, 10, 4, 3 |
| Grid Triangle | S side length, Ex and Ey cell counts | 10, 4, 3 |
| Grid Hexagon | S side length, Ex and Ey cell counts | 10, 4, 3 |
| Grid Radial | S ring spacing, Er rings, Ep sectors | 10, 4, 8 |

Each grid also takes **P** (Plane or Normal, default XY) and **O** (Origin). A connected point specifies the absolute origin. The disconnected XYZ fields give an offset from the plane origin. The counts are integers. Ex, Ey, and Er must be at least one, and Ep must be at least three. The grids use local plane coordinates. Triangle cells are equilateral, Hexagon cells are flat-topped, and Radial cells use exact circular arcs.

## Outputs and Point Grouping

| Output | Value |
| --- | --- |
| G | Grid geometry recipe for the whole grid |
| C | Closed cell outlines |
| P | Rectangle and Radial points, or Triangle and Hexagon cell centers |
| V | Unique vertices on Triangle and Hexagon |
| E | Unique edges |
| R / A | Radial lines and circular arcs on Grid Radial |
| NC | Number of cells |
| NP | Number of published points, including cell centers and unique vertices where applicable |
| Count | Number of grids |

Set **Point Grouping** in Properties to change P in either mode.

| Setting | Rectangle, Triangle, Hexagon | Radial |
| --- | --- | --- |
| Flat | One branch per grid, in row order | One branch per grid, center first |
| Rows (default) | One branch per row | Center branch, then one branch per ring |
| Columns | One branch per column | Center branch, then one branch per spoke from inside to outside |

With several grids, each grid has its own path prefix. Point Grouping retains point identity and leaves the other outputs and published geometry unchanged. Connecting **Grid Rectangle.P → InterpCurve.P** produces one curve per row or column with the corresponding grouping. Graft and Flatten are applied locally to each input before matching. Parameters pair by compatible paths and lengths, with singleton broadcasting.

## Native commands and capacity

NoodleSBridge registers `gridrectangle` (`rectgrid`), `gridtriangle` (`trigrid`), `gridhexagon` (`hexgrid`), and `gridradial` (`radgrid`). The commands ask for the name, origin, dimensions, and counts, use the active CPlane, and create a CAD undo checkpoint at commit. They share the same OCC grid factory as the nodes and are available while the editor is closed.

The per-output limit is 10,000 items across all grid slots. The graph and geometry workers prepare data, OCC topology, display data, and selection indices off the GUI thread. A single scene transaction installs the finished result. Newer evaluations supersede obsolete queued work.

| Grid | Benchmark extent | Cells | Points | Edges | OCC, display preparation, and commit |
| --- | --- | ---: | ---: | ---: | ---: |
| Rectangle | 70×70 | 4,900 | 5,041 | 9,940 | 334 ms |
| Triangle | 57×57 | 6,498 | 9,862 | 9,861 | 407 ms |
| Hexagon | 57×57 | 3,249 | 9,975 | 9,974 | 424 ms |
| Radial | Er 50, Ep 100 | 5,000 | 5,001 | 10,000 | 485 ms |

These isolated Serpentine3D 0.12.2 measurements cover the native stage. The graph and transport took roughly another 0.10–0.17 s for the large cases. A separate test kept ten 50×50 rectangular grids in the same scene and published another grid in about 0.17–0.18 s. These measurements describe the tested scenes, hardware, and version. [Viewport diagnostics](../CONTRIBUTING.md#viewport-diagnostics)
