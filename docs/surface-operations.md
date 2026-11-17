# Extrude, Revolve, and Loft

Find these nodes in **Library → Operations**. They use OpenCascade and publish one ParametricObject per node, even when the tree contains many results. Sources remain available as separate graph values and scene objects.

| Node | Inputs | Defaults |
| --- | --- | --- |
| Extrude | G geometry, V vector, C cap | V = (0, 0, 10), Cap on |
| Revolve | C profile curve, A axis, D angle | Z axis and 360° |
| Loft | C sections, T type, Cl closed, A adjust, O options | Smooth, Closed off, Adjust on |

## Extrude

G accepts curves or surfaces. V sets the complete displacement and can include negative components. Connect a typed vector or edit XYZ in Properties. **Cap** closes a planar closed profile to create a solid. An open profile produces a surface. Capping a nonplanar closed curve can fail. A solid input is outside this operation's curve and surface contract.

## Revolve

A accepts a Line or Plane. A Line supplies its first point and direction, and a Plane supplies its origin and normal. Choose XY, XZ, or YZ in Properties when A is disconnected. D is a signed sweep in degrees with a nonzero magnitude of at most 360°. A closed profile is revolved as a curve. Cap suitable planar openings afterwards if needed. [Cap Holes](surface-construction.md)

## Loft

Each nonempty C branch supplies 2–240 ordered profiles. **Closed** cycles back to the first profile and needs at least three sections. **Adjust** lets OCC align compatible section edges. **T** selects Smooth or Ruled. Use **Loft Options.O → Loft.O** to supply a set of options. Direct wires to T, Cl, and A take precedence. Rebuild and Refit report an error when requested.

Use Flatten on C to combine section branches into one ordered loft. Repeated identical sections and mismatched option branches report errors. Loft can also expose an existing native surface or solid in [Reference mode](surface-references.md).

## Outputs and commands

All inputs support Graft and Flatten. **G** supplies deferred geometry for downstream nodes. **K** reports the OCC kind once the current native result arrives. **Count** reports the number of results. Loft also returns **SC**, the section count. The shared worker can reuse unchanged input shapes and operation results.

The native commands `extrudevector` (`extrudev`), `revolveparam`, and `loftparam` use the same factories and run while the editor is closed. [ParametricObject](parametric-object-contract.md)
