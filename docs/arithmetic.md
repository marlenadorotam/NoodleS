# Addition and Multiplication

Find both nodes under **Library → Math**. Connect both **A** and **B** to produce **R (Result)**.

| Operands | Addition | Multiplication |
| --- | --- | --- |
| Two numbers | Sum | Product |
| Two vectors | Vector sum | Dot product |
| Two points | Point with componentwise sum | XYZ dot product |
| Point and vector in either order | Point translated by the vector | XYZ dot product |
| Number and vector in either order | Input error | Scaled vector |
| Number and point in either order | Input error | Point scaled about the origin |

The dot product is `ax*bx + ay*by + az*bz`. A vector is a typed `VectorValue(xyz)`, and a point is a `PointValue(key, xyz)`. Use [Vector](vector.md) or [Point](point.md) to produce these values. A plain list or tuple of three numbers is treated as a numeric sequence. Point results receive stable keys derived from the operation and the source keys. These operations produce graph data and leave existing scene geometry and reference bindings intact.

## DataTree and Properties

- Scalar inputs produce a scalar. Lists, tuples, trees and active tree modifiers produce a DataTree. Each input must contain one supported type.
- The nodes match branches by path, broadcast a single branch and repeat the last value of a shorter branch. Incompatible multiple branches raise an error. Empty inputs produce no items.
- Properties previews the connected values and offers **Graft** and **Flatten** per input. These start off and can be toggled off by clicking again. Edit connected values in their source nodes.
- Numeric strings are accepted in scalars and flat sequences. Typed tree leaves require numbers. Booleans, domains, scene objects, untyped nested XYZ data and non-finite values are invalid.
- The tree limit is 10,000 items. Point results must stay within ±1e9. Numbers and vector coordinates must be finite. An invalid pair clears the result so downstream nodes cannot use stale data.

When opening an older graph, NoodleS migrates the **Number** output on these nodes to **R**. Input modifiers are saved in `tree_modes` and support undo and redo. Tests in `tests/test_arithmetic.py` cover type combinations, tree matching, properties and saved graphs.
