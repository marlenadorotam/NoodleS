# Surface UV domains and evaluation

These surface nodes are in **Library → Operations**, except the overlay in Visual Helpers. Inputs support DataTree, Graft, and Flatten.

## Domains

| Node | Inputs | Outputs and behavior |
| --- | --- | --- |
| Surface Domain | S surface, F face index | U and V domains and the combined Domain² on D |
| Deconstruct Domain² | I Domain² or surface, F face index for a surface | U and V as separate domains |
| Divide Domain² | I Domain² or surface, U and V division counts, F face index for a surface | S contains U × V subdomains, with U varying fastest. Both counts default to 10 |
| Reparameterize Surface | S surface, optional U and V domains, F face index | A UV view of the same face, preserving its geometry and trim |

Divide Domain² supports up to 10,000 subdomains. Its division takes place in parameter space. Use **S → Isotrim.D** to apply the subdomains to a surface. You can connect individual intervals to Range or pass U/V to Surface Morph. [Isotrim](brep-join-isotrim.md), [Surface Morph](surface-morph.md)

Reparameterize Surface defaults to 0–1 in both directions when U and V are disconnected. To change an axis, supply an increasing domain. If only one axis is connected, the other keeps the input's range. Follow with Surface Domain or Deconstruct Domain² to read the new intervals. Linear reparameterization changes parameter values while keeping equal subdivisions in the same positions on the face.

## Surface Evaluate and Surface Closest Point

**Surface Evaluate** accepts **S**, **U**, **V**, **N** (Normalized, off by default), and **F**. With Normalized on, the input coordinates use 0–1. Otherwise they use native parameters or the incoming UV view. A disconnected axis samples the midpoint of its active interval.

The outputs are **P** (points), **N** (oriented unit normals), **U/V** (derivatives), **F** (tangent frames, with X along U), **Count**, **u/v** (input coordinates in the active system), and **Skipped**. Derivatives use the UV view's scale when that view is active and Normalized is off. Otherwise they use native OCC parameters. Flat lists pair with repeat-last. Graft one axis to sample rows when the other axis supplies a common list. Skipped sample positions are omitted from every parallel output.

**Surface Closest Point** accepts **P** query points, **S**, **N**, and **F**. It returns the nearest point **P**, parameters **U/V**, and distance **D** on the trimmed face. To use the returned parameters in Surface Evaluate, keep S, F, and Normalized consistent between the two nodes.

## Face selection and trims

Face Index **0 (Auto)** selects the only face or uses the face already stored in a UV view. For multi-face shapes, specify a 1-based face index. The index follows the current OCC face order, so check it after topology changes. A conflicting index on an existing UV view reports an error.

The native worker uses the trimmed face's UV bounds. These rectangular parameter bounds can include holes or regions outside the actual trim. Surface Evaluate accepts samples on valid boundaries and skips points in holes, outside the trim, or at singularities with no defined tangent plane. Parameters outside the selected interval report an error. The ends of a periodic seam may return the same point. The batch limits are 5,000 domain measurements and 2,500 Evaluate or Closest Point queries per node.

## UV Panels

Connect the surface to **S**, set **U/V** to the subdivision counts, and select a face with **F** where needed. Both counts default to 10. Each nonempty trimmed cell produces one **S** item in U-fastest order and may contain multiple disjoint face fragments. **Count** reports cells. The worker respects holes and the source outline. There may be up to 1,024 attempted cells, including empty ones. The node publishes one ParametricObject. The `uvpanels` command uses the same factory.

## Surface Isocurves

Connect a surface or UV view to **S** and select its face with **F**. **u** fixes U, so the curve runs along V. **v** fixes V, so the curve runs along U. Both default to 0.5 in Normalized mode. Turn off **N** to use the native or view intervals. **D** selects both directions or one.

The U/V outputs contain native analytic or spline edges clipped to the face. A hole may split one isocurve into several edges. The worker skips spans that collapse to a point. **Count** reports the resulting fragments. Up to 1,024 sample locations or 2,500 fragments can appear in one node result. All curves publish as one ParametricObject. Serpentine3D provides the matching `surfaceisocurves` command.

## Reparameterize Surface Preview

In **Library → Visual Helpers**, connect a surface or UV view to **S** and select the face with **F**. **U/V** set 1–32 equal intervals per direction, defaulting to 8 each. The overlay draws interior lines with constant U in turquoise and constant V in amber. **E** controls visibility. **Count** reports surfaces with active subdivisions.

The worker clips UV lines to the trim before sampling them for display. The depth-tested overlay does not affect CAD history. It is limited to 16 faces and 6,000 vertices per node, with an additional shared overlay frame budget. [Preview lifecycle](vector-preview.md)
