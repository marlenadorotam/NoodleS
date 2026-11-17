# Range

**Library → Math → Range** divides an interval into equal steps. **D** accepts a typed domain and defaults to 0–1. **N** is the number of steps and defaults to 10. Range returns both endpoints, for a total of N + 1 numbers. With D = 0–10 and N = 2, the result is 0, 5, 10. Descending intervals retain their direction. A zero-length interval reports an error. Build a domain from two endpoints with [Domain](domain.md).

| Output | Value |
| --- | --- |
| R | The generated lists in their matched tree structure |
| Flat | All values in branch order at `{0}`, with item keys retained |
| Count | Total number of values across all lists |

## Properties and matching

Use Start and End for a disconnected D and Steps for a disconnected N. The Steps editor rounds and limits values to 1–9,999. A wire must supply a whole number in that range. Fractions, Boolean values, strings, and non-finite values report an error. Connected inputs show a preview. The local Graft and Flatten buttons start off, and the graph stores their settings and the disconnected defaults.

The node matches equal paths, broadcasts a single branch, and repeats the last item within a shorter list. With one interval and step pair per branch, R keeps the original paths. If any branch contains multiple pairs, every result path gains a list index. Empty input stays empty. The node checks the 10,000-number total budget, including all endpoints, before generating the lists. [Range tests](../tests/test_range.py)
