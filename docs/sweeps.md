# Sweep 1 Rail, Sweep 2 Rails, and BiRail Sweep

These **Operations** nodes generate native OCC geometry. Supply typed curves from the graph or capture CAD sources with a curve node in Reference mode. Each matched set uses one profile. A list of profiles makes independent results, all published as one ParametricObject.

| Node | Inputs | Outputs |
| --- | --- | --- |
| Sweep 1 Rail | R rail curve, P profile curve | G geometry, K native kind, Count |
| Sweep 2 Rails | R1 main spine, R2 orientation guide, P profile curve | G, K, Count |
| BiRail Sweep | R1 and R2 boundaries, P profile, Rs rail samples, Ps profile samples | G, K, Count |

Graft and Flatten act locally before matching. Each branch needs compatible lengths or singleton values. Native kind K is pending until the matching OCC result is available.

## Sweep 1 Rail

The native OCC MakePipe operation transports P along R. Position and orient the profile before connecting it. The node uses that placement. An open profile yields a surface and a closed profile yields an uncapped shell. A rail can be open or closed if the kernel can build a valid result.

## Sweep 2 Rails

R1 is the path along which the native sweep transports the profile. R2 sets the orientation along that path using the auxiliary spine. The result does not necessarily touch R2 or follow its width. Use the intended source direction and placement for the profile and both rails.

## BiRail Sweep

Use BiRail Sweep when both rails should serve as boundaries. Provide two open rails and an open profile. Each profile endpoint must meet a rail endpoint within 1e-6 model units. The node can match rail order and direction automatically. Coincident stations and degenerate samples report an error.

The algorithm samples by arc length and transports the profile using frames on both rails. It blends the transported points from one boundary to the other. An OCC surface interpolates this grid. The rails and starting profile are matched at the sample positions. The shape between samples is an approximation. Increase Rs for curved rails or Ps for a detailed profile. Both accept integers from 4–129, defaulting to 33 and 25 respectively, with Rs × Ps at most 10,000 per result.

## Commands and publication

The `sweep1param`, `sweep2param`, and `birailsweep` commands use the same factories in Serpentine3D while the editor is closed. The worker builds and validates native shapes and prepares native display data. The scene applies the complete result together and leaves the sources available. [ParametricObject](parametric-object-contract.md), [Sweep tests](../tests/test_sweeps.py), [Native sweep tests](../tests/test_sweep_native.py)
