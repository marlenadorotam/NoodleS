# DataTree input controls

A **DataTree** groups values into ordered branches with paths such as `{0;2}`. In Properties, **Graft** and **Flatten** apply to the individual input beside them. Both start off. Click an active button to turn it off or click the other button to switch modes. One switch is one undo step. The graph file stores the selected mode.

| Mode | Result at this input |
| --- | --- |
| Neither button active | Passes through the original input structure |
| Graft | Gives each item its own branch by appending its index to the original path |
| Flatten | Collects the items into one branch in tree order |

A point still counts as one item after either operation. Numbers, vectors, curves, and geometry references retain their values and identity. Other consumers of the same output continue to receive the original tree.

## Matching after an input operation

The node first applies each port's selected operation. It then matches branches and items according to its input contract. An input can consume individual items, whole branch lists, or a complete tree. For instance, Box can use the items in a branch as separate positions, while InterpCurve uses the branch as one list of points for a single curve.

Nodes that broadcast a single branch can pair that branch with each branch of the other input. Grafting three points while leaving three heights in a single branch can therefore produce nine combinations. Grafting both sides can preserve a one-to-one match when their paths agree. Check the processed input preview in Properties for its branch and item counts. Hover over the preview to inspect the full tree.

Limits in the shared DataTree implementation cover branches, items, and the expanded result of matching. Individual geometry nodes can impose lower limits on their operation. Input transformations change the layout passed to evaluation while keeping the source data intact. [DataTree implementation](../noodles/backend/datatree.py)
