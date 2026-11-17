# Planar Surface, Edge Surface, Surface from Points, and Cap Holes

These nodes are in **Library → Operations**. Each publishes one ParametricObject. The entries below describe Generate. Planar Surface and Edge Surface can also read a native result in [Reference mode](surface-references.md).

| Node | Inputs | Outputs |
| --- | --- | --- |
| Planar Surface | C closed boundaries | G geometry, K native kind, N normal, EC edge count, Count |
| Edge Surface | C boundary curves | G, K, EC, Count |
| Surface from Points | P ordered points, U points per row | G, K, U, V row count, Count |
| Cap Holes | B open BREP surfaces or shells | B capped geometry, K native kind |

## Planar Surface

Supply 1–240 closed coplanar loops per branch. Nesting defines regions by parity. The outside loop bounds the face, the next loop makes a hole, and a loop inside that hole makes an island. Disjoint regions can share a branch. Place contours on different planes in separate branches. Open, nonplanar, intersecting, duplicate, and partly overlapping loops report errors. N reports the orientation of the first resulting face.

## Edge Surface

Supply 2–4 single-edge curves per branch. OCC fills the area using a Coons construction. With two curves it builds the remaining sides. With three or four curves the supplied edges must form a closed boundary. Multi-edge wires are unsuitable as an individual side. Use [Patch](patch.md) for a supported closed loop with more sides.

## Surface from Points

Supply 4–2,500 typed points per branch, with at least two rows and two columns. List the U samples of the first row in order, then those of the second row, and so on. The list length must equal U × V. Supply a common U or one U per matching branch. A connection to U overrides the local setting.

**Auto** can infer U from at least two equally sized consecutive row branches under a common parent when **Flatten** is active on P. It reads row widths before flattening. For an already flat list or ambiguous structure, set U explicitly. Use separate branches for independent input surfaces.

**Periodic U** closes the surface along each row. Use at least four samples per row, with a consistent starting position and direction across rows. Include the starting sample once. The V ends stay open. OCC interpolates the ordered grid and the worker checks for collapsed neighboring samples, invalid topology, and zero area.

## Cap Holes

Cap Holes processes each BREP separately. It closes planar openings and converts the result to a solid when the shell closes. Nonplanar openings remain open. If the input has no cappable opening, the node reports an error. Its own output preserves the input branch structure and the original geometry remains in the scene.

## Publication

Graft and Flatten act at the input. Empty branches remain empty. Count reports surface recipes, and native metadata such as K and EC arrives from the OCC worker. The bridge validates and publishes the finished result in one scene update.

The Serpentine3D commands `planarsurfaceparam`, `edgesurfaceparam`, `surfacefrompoints`, and `surfacefrompointsperiodic` use the same factories with the editor closed. [ParametricObject](parametric-object-contract.md)
