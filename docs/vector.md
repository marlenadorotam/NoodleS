# Vector nodes

Find these nodes in **Library → Math**. **Vector** takes numeric **X/Y/Z** with defaults of zero and returns a typed **Vector** and its Euclidean **Length**. A zero vector is valid. Use typed vectors in arithmetic and downstream geometry inputs. A plain list of three numbers remains numeric data.

| Node | Inputs | Outputs | Behavior |
| --- | --- | --- | --- |
| Vector 2Pt | A start point, B end point, U Unitize | V vector, L length | Forms B − A. U defaults to off, and L always reports the original point-to-point distance |
| Unit Vector | V vector | U unit vector | Normalizes vectors longer than 1e-15 |
| Unit X | F factor | V vector | Returns (F, 0, 0) |
| Unit Y | F factor | V vector | Returns (0, F, 0) |
| Unit Z | F factor | V vector | Returns (0, 0, F) |
| Amplitude | V vector, A amplitude | V vector | Rescales a vector to magnitude `abs(A)` and reverses its direction when A is negative |
| Reverse Vector | V vector | V vector | Negates each component |

The axis factors and amplitude default to 1. A negative axis factor reverses its direction. A zero amplitude or zero input vector produces a zero vector in **Amplitude**. **Vector 2Pt** returns zero vector and distance for coincident points, even with Unitize selected. **Unit Vector** reports an error if its vector is zero or too short. All components and results must be finite.

## Properties and DataTree

Each input has local Graft and Flatten controls. Connected values show a preview. Disconnecting restores the stored default where one is available. Scalar inputs yield scalar results. Tree inputs retain matched paths and keys across corresponding outputs.

Vector and Vector 2Pt match branches by paths, broadcast a single branch, and use repeat-last within a branch. A plain list with as many values as there are tree slots can fill them sequentially. A row-sized list can repeat across branches, and ambiguous layouts report an error. Empty inputs propagate empty results.

These nodes calculate data. To display vectors, connect [Vector Preview](vector-preview.md). To apply a translation, use [Move or Move GH](move-implementation.md). [Typed arithmetic](arithmetic.md)
