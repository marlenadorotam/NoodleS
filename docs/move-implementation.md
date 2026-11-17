# Move and Move GH

Both nodes are in **Library → Operations**.

| Node | Inputs | Outputs |
| --- | --- | --- |
| Move | G geometry, X/Y/Z translation, W world coordinates, optional T translation vector | G moved geometry, X/Y/Z world translation, Count |
| Move GH | G geometry, T translation vector | G moved geometry, X translation transform, Count |

**Move** translates the source scene object in place. If the source has no scene owner, Move publishes the result. **Move GH** publishes copies as its own ParametricObject. Both provide transformed geometry to downstream nodes.

Move uses world coordinates by default. Turn W off to use the source's local axes when available. A connected T overrides X/Y/Z, including their wires. Disconnecting T restores their saved values and connections.

## Moving grid parts

| Connect to G | Result |
| --- | --- |
| Grid G | Moves the complete grid |
| Grid P | Moves points, including cell centers on Triangle and Hexagon |
| Grid V | Moves the unique Triangle or Hexagon vertices |
| Grid C | Moves cell outline curves |
| Grid E | Moves individual edges |
| Grid Radial R or A | Moves only radial lines or only arcs |

This part-level in-place behavior applies to generated grids. For a referenced grid, Move takes the whole G of a single grid. Use Move GH to copy its parts. Shared edges have one identity, so conflicting in-place translations on neighboring outlines raise an error. Parallel translations of a whole grid and one of its parts can likewise conflict. Consecutive Move nodes compose in graph order.

Each input supports Graft and Flatten. One translation can apply to a whole collection. Matched branches and values can move individual elements by different amounts. A flat list with one value per tree slot can fill those slots in branch order.

## Scene updates

Updating generated geometry retains its owner and scene attributes. Disabling, disconnecting, or deleting Move restores the source's position as defined by the rest of the graph. Deleting Move GH removes its own copies. For references, persistent markers resolve the source after reopen. The bridge stores the applied offset and applies the difference when the graph changes so CAD edits are carried forward. [Transform composition](rotate.md), [Move tests](../tests/test_moves.py)
