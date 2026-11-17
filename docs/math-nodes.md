# Numeric math nodes

These nodes are in **Library → Math**. See [Arithmetic](arithmetic.md) for typed arithmetic and [Vectors](vector.md) for vector construction.

| Node | Inputs → outputs | Behavior |
| --- | --- | --- |
| Subtraction | A, B → R | Subtracts numbers or subtracts two vectors component by component |
| Division | A, B → R | Divides A by B and reports an error if any matched divisor is zero |
| Minimum | A, B → R | Returns the smaller value in each matched pair |
| Sine | X → Y | Evaluates the sine of X in radians |
| Square | X → Y | Returns X² |
| Series | S, N, C → S, Count | Generates C values starting at S and advancing by step N |
| Bounds | N → I | Returns one interval spanning the global minimum and maximum |
| Remap Numbers | V, S, T → R, C, Flat R, Flat C | Maps values from source domain S to target domain T |

## Matching

Graft and Flatten apply locally before matching. The usual rules match paths, broadcast a single branch, and repeat the last value in shorter lists within a branch. Two multi-branch trees with incompatible paths report an error. Numeric results must be finite.

Minimum can distribute an unmodified plain list across a tree when its length equals the total number of slots. A shorter plain list can match within branches. Ambiguous lengths report an error. An explicit DataTree retains its supplied paths.

Series defaults to start 0, step 1, and count 10. Step can be negative or zero. Count must be a whole number from 1 to 10,000. Input lists per branch must have equal lengths or be singletons. Each matched set generates a list. If any branch contains multiple sets, list indices extend every path to keep the lists separate. Count reports the total number of numbers, and the total result is subject to the 10,000-item limit.

Bounds reads all branches. If every value is 3, it returns the valid typed interval [3, 3]. An empty collection has no bounds. Nodes that require a nonzero span report an error for such an interval. [Domain](domain.md), [Range](range.md)

Remap Numbers defaults both domains to 0–1. Both can descend and must have nonzero length. **R** can extrapolate outside the target interval, while **C** clamps to it. The two flat outputs collect their corresponding results in branch order. Domains can be provided as DataTrees and matched to V.

Properties shows connected data in a preview and provides controls for available defaults. Disconnecting a port restores its saved default where one is available. [Numeric tests](../tests/test_math_nodes.py)
