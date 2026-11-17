# Graph Mapper

**Library → Math → Graph Mapper** maps values through an editable function. Connect numbers or a DataTree of numbers to **V**. **I** sets the input domain and **O** sets the output domain. Both default to 0–1. Connected domains must be typed Domain values. Descending domains are valid, and zero-length domains are rejected.

The node normalizes and clamps each input to 0–1, applies **Flip X** if selected, evaluates the function, applies **Flip Y** if selected, and scales the result to O. **R** preserves the matched structure, **Flat** returns the results in one branch, and **Count** reports their number. Each input supports Graft and Flatten. Empty inputs keep empty results. Matching is subject to the 10,000-item DataTree limit.

| Function | Behavior on the normalized interval |
| --- | --- |
| Linear | Interpolates between adjustable start and end heights |
| Cubic Bezier | Uses two control points and solves for the parameter at the given X |
| Quadratic Bezier | Uses one control point and solves for the parameter at the given X |
| Power | Raises X to a power from 0.1 to 10 |
| Parabola | Joins two quadratic sections at a shared peak with a horizontal tangent |
| Smoothstep | Shapes the eased transition between Start and End |
| Sigmoid | Uses a logistic transition normalized to the endpoints |
| Square Root | Uses a power from 0.1 to 1, with 0.5 as the default |
| Exponential | Uses a normalized exponential with a signed rate and a linear limit at zero |
| Sine | Uses a cosine-based oscillation with adjustable frequency and amplitude |
| Sine Summation | Combines a base oscillation and its second harmonic |
| Gaussian | Uses a bell curve with adjustable center and width |

## Editing

Drag the handles on the node or in Properties. Right-click the plot to choose a function, flip an axis, or reset. Double-clicking the plot resets the current function. Use the numerical controls in Properties for exact parameters. Reset retains the other functions' settings, the axis flips, domains, and input modes. The node remembers parameters when you switch between functions.

The plot and graph runtime share the same calculations. One drag creates one undo step. The graph file stores the editable configuration in `graph_config`. Existing configurations using `Bezier` load as Cubic Bezier, and `reverse` represents Flip Y. [Graph Mapper tests](../tests/test_graph_mapper.py)
