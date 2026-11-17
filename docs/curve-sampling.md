# Curve sampling

These nodes are under **Operations**. **C** accepts generated or referenced curves. Inputs expose **Graft** and **Flatten**.

| Node | Main inputs | Result |
| --- | --- | --- |
| **Curve Domain** | **C** | **D** is the native OCC parameter interval, including trims. **L** is the interval length. Both retain input paths and keys. |
| **Divide Curve** | **C**, **N** (10 by default, 1–500), **K** (Kinks, off by default) | Equal arc-length divisions. An open curve produces N+1 samples and a closed curve produces N. **K** adds wire junctions. |
| **Divide by Length** | **C**, **L** (segment length), **R** (Include Remainder, on by default) | Samples at fixed arc-length intervals from the start. **R** adds the end of an open curve when a shorter segment remains. The seam of a closed curve is included once. |
| **Frame** | **C**, **t** (0 by default), **G** (world Z), **N** (Normalized, on) | A plane at each parameter. The normalized range 0–1 maps to each curve's native domain. |
| **Perp Frames** | **C**, **N** (10 by default, 1–500), **A** (Align, on), **G** (world Z) | Frames at equal arc-length intervals. Open curves produce N+1 frames and closed curves produce N. |

The sampling nodes return **P** (points), **T** (unit tangents), **t** (native parameters) and **Count**. The frame nodes also return **F** (planes), which can feed [Plane Preview](vector-preview.md). Each plane is perpendicular to the tangent, with **Guide** projected onto it as the X axis. If the guide is parallel to the tangent, NoodleS picks a world axis deterministically. With **Align** off, Perp Frames tries the perpendicular curvature direction first.

A single parameter branch is shared by all curves. A multi-branch tree is matched by curve path or parent path when the output splits curves into separate branches. Outputs append a curve index to the path when several curves share a branch. The division nodes allow 5,000 samples per node. **Frame** allows 512 parameters per curve, and the frame outputs allow up to 3,500 planes per node.

Turn off **Normalized** when feeding native parameters from **Divide Curve.t** or **Curve Domain.D → Range.R** into **Frame.t**. OCC uses an edge adaptor for single edges and a composite adaptor for wires, with knots positioned by edge length. The measurement worker does not publish any scene objects.

## Curvature and containment

**Curve Curvature** takes **C**, **t** and **N** (Normalized, on by default) and returns sampled points **P** and curvature vectors **K**. Their lengths are 1/r on a circle and zero on a line. Undefined derivatives raise an error.

**Point In Curve** takes points **P** and a valid closed planar curve **C**. **R** is 0 outside, 1 on the boundary and 2 inside. **I** is true only inside. Points off the plane are outside.

For a curve offset guided by containment, sample a closed curve with **Divide Curve** and send its native parameters to **Curve Curvature**. Normalize the nonzero vectors with **Unit Vector**, add them to the sample points and use **Point In Curve** to classify the trial points. With **I** as the pattern, use **Dispatch**, **Reverse Vector** and **Weave** to reverse the vectors whose trial points are inside. Add the resulting vectors to the original sample points and build a closed **InterpCurve**. You can use **Equality** to compare **R** to 2 and obtain the same pattern.

## Preparing profiles

- **Shatter** sorts the supplied **t** values, skips duplicates and domain endpoints and preserves the existing seam. Supply up to 512 parameters per curve. Turn off **N** for native values. **C** returns exact fragments, and **D** returns their source intervals. With several curves in one branch, the index splits the output paths.
- **Flip Curve** reverses **C** or matches it to optional guide **G**. Both curves must agree on whether they are closed. Open curves are compared by their endpoints. Closed curves are compared by ordered samples with seam alignment. **F** tells whether a reversal occurred.
- **Move Seam** moves the start of a closed curve to **t**. With **N** on, 0 and 1 describe the same seam. With it off, **t** uses the OCC parameter. **C** returns the edited curve and **P** returns the seam position. A fully periodic edge stays a single edge. A wire may split an edge at the new seam.

The profile edits publish as ParametricObjects. **Shatter** and **Move Seam** also have Serpentine3D commands `shatterparam` and `moveseamparam`.
