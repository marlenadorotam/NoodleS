# Domain

**Domain** is in **Library → Math**. It creates a numeric interval for use in nodes such as [Range](range.md).

| Port | Default | Meaning |
| --- | ---: | --- |
| **A** (Start) | 0 | First endpoint |
| **B** (End) | 1 | Second endpoint |
| **D** (Domain) | | An interval containing the two endpoints in input order |
| **L** (Length) | | The distance between the endpoints, `abs(B - A)` |

For example, **A = 5** and **B = 2** give a descending domain from 5 to 2 and a length of 3. Equal endpoints cause an evaluation error and clear both outputs and dependent results. You can still save those values and edit either endpoint later. Domain accepts finite numeric endpoints within ±1e9. Booleans, text, points and other domains are invalid. **Bounds** can produce a zero-length domain, which consumers such as **Range** and **Remap Numbers** validate separately.

## Properties and DataTree

Edit the default endpoints in **Properties → Inputs**. A connected input shows its current value. Disconnect it to restore the saved default. **Graft** and **Flatten** apply to each input independently and start off. Click an active modifier to clear it. Changes support undo and redo.

Both outputs are DataTrees with matching paths and item keys. Each endpoint pair creates one typed interval and one numeric length. The node matches branch paths, shares a single branch across matching inputs and repeats the last item in a shorter branch. Empty inputs produce no items, and incompatible branch paths raise an error. Domain produces graph data without creating scene geometry.

The implementation is in [domain.py](../noodles/backend/domain.py). The stored interval uses the `serpentine_domain` representation.
