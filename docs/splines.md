# Curve and InterpCurve

Both nodes are in **Library → Geometry**. **Curve** builds a NURBS from control points. **InterpCurve** fits a NURBS through interpolation points. Supply typed points on **P**, for example from a Point node. A plain XYZ list is numeric data. Each nonempty point branch produces one spline, and the node publishes all of them as one ParametricObject.

## Generate

**Curve** takes **D** (Degree, 2–10, default 3) and **C** (Closed, off by default). An open curve needs at least D + 1 control points. A closed curve needs at least three distinct points. The native builder caps the periodic degree at the level supported by those points. A repeated starting point at the end of a closed list is removed.

Curve outputs **C** (Curve), **V** (Control Point Branches), **D** (actual degree), **Cl** (Closed), **Per** (Periodic), **L** (Length), and **Count**.

**InterpCurve** takes **D** (Degree, 1–5, default 3), **C** (Closed), **T** (Periodic), and **K** (Knot Style). Closed and Periodic default to off. Knot styles are 0 Uniform, 1 Chord (default), and 2 Square Root Chord. Periodic requires a closed result. A repeated first point at the end of the list is removed and implies closure.

Supply at least three distinct interpolation points with distinct neighbors. The general degree must be lower than the number of interpolation sites. The default degree-3, Chord configuration uses the native interpolator, which also accepts three points and produces a periodic spline for closed input. Other fits use OCC spline bases. The per-branch limit is 1,200 points. Without NumPy the custom fit supports up to 128 sites.

InterpCurve outputs **C**, **V** (Interpolation Point Branches in Generate), **CP** (native control poles), **D**, **Cl**, **Per**, **L**, and **Count**.

## DataTree and measurements

Each input supports Graft and Flatten. Flatten on P combines point lists into one spline. Graft on P can leave too few points in each branch. Keep each option constant within a point branch, or supply one option per branch with compatible paths. Empty branches stay empty.

L and native control poles are computed on the OCC worker. Outputs remain pending until a measurement matches the current recipe. During disconnection, the graph can retain the recipe while waiting for native measurements.

## Reference

Select existing native spline or Bézier geometry and click **Set reference**. The bridge preserves the exact native curve, including weights, orientation, and trim. A Bézier reference can be represented in an exact NURBS basis. An InterpCurve reference provides native poles on CP. Its original interpolation sites are unavailable, so V is empty. Supply new points on P to refit with different parameters. [Reference editing](reference-editing.md), [Curve sampling](curve-sampling.md)
