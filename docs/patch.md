# Patch

**Library → Operations → Patch** fills a closed boundary with a surface. The boundary may be nonplanar.

| Port | Meaning |
| --- | --- |
| C | Boundary curves, one connected closed loop per branch |
| G | Surface geometry, one result per nonempty branch |
| K | Native result kind |
| EC | Native edge count |
| Count | Number of surface recipes |

A branch can contain one or more curves and must contribute 2–240 edges in all. A closed multi-edge Polyline is valid. A single-edge circle or closed spline is below the edge minimum. Use [Planar Surface](surface-construction.md) for a planar boundary with holes or islands. Patch expects a single loop.

Graft and Flatten act on C before the node checks the boundary. Flatten combines all input curves in one branch. Grafting individual open edges produces separate branches that cannot close on their own.

The worker joins the boundary and calls the OCC filling operation with G0 positional constraints. It validates the result and its area before publication. A connected loop supplies boundary positions. Tangency and curvature continuity would require additional support-face input. K and EC are pending until the matching native result returns.

Patch uses the common geometry worker and publishes a single ParametricObject across all branches. Input curves remain available. The `patchparam` command uses the same factory and works with NoodleS closed. [Patch tests](../tests/test_patch.py)
