"""Bounded numeric ranges. N segments produce N+1 inclusive values."""
import json
import math

from .datatree import Branch, DataTree, MAX_ITEMS, MAX_BRANCHES, aligned, topology
from .domain import DomainValue, domain_number


def range_steps(value):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not 1 <= value <= MAX_ITEMS - 1 or int(value) != value):
        raise ValueError(f"Range Steps must be an integer between 1 and {MAX_ITEMS - 1:,}.")
    return int(value)


def normalize_range_state(data):
    modes = data.get("tree_modes", {})
    if not isinstance(modes, dict) or set(modes) - {"D", "N"}:
        raise ValueError("Invalid Range input modifiers.")
    if any(mode not in ("none", "graft", "flatten") for mode in modes.values()):
        raise ValueError("Invalid Range input modifier.")
    return {"start": domain_number(data.get("start", 0)),
            "end": domain_number(data.get("end", 1)),
            "steps": range_steps(data.get("steps", 10)),
            "tree_modes": {key: mode for key, mode in modes.items() if mode != "none"}}


def evaluate_range(parameters, inputs):
    state = normalize_range_state(parameters)
    # A connected empty tree stays empty; it must never silently use defaults.
    domain = inputs["D"] if "D" in inputs else DomainValue(state["start"], state["end"])
    domains = topology(domain, state["tree_modes"].get("D", "none"))
    counts = topology(inputs.get("N", state["steps"]), state["tree_modes"].get("N", "none"))
    matches = tuple(aligned(domains, counts))
    # Preflight the entire output before allocating lists, even across branches.
    total, branch_count = 0, 0
    split = any(len(rows) > 1 for _, rows in matches)
    for _, rows in matches:
        branch_count += max(1, len(rows))
        if branch_count > MAX_BRANCHES:
            raise ValueError(f"Range exceeds the {MAX_BRANCHES:,} branch limit.")
        for (value, steps), _ in rows:
            if not isinstance(value, DomainValue):
                raise ValueError("Range D requires a Domain. Connect the D output of a Domain node.")
            if value.start == value.end:
                raise ValueError("Range Domain must have nonzero length.")
            total += range_steps(steps) + 1
            if total > MAX_ITEMS:
                raise ValueError(f"Range exceeds the {MAX_ITEMS:,} output value limit. Reduce Steps or the number of domains.")
    branches = []
    for path, rows in matches:
        if not rows:
            branches.append(Branch(path + (0,) if split else path, ()))
        for index, ((value, steps), keys) in enumerate(rows):
            steps = range_steps(steps)
            # Assign endpoints explicitly; floating point arithmetic must not
            # move the last sample beyond its domain or leave it just short.
            values = ((value.start,) + tuple(value.start + (value.end - value.start) * (i / steps)
                      for i in range(1, steps)) + (value.end,))
            identity = json.dumps(keys, separators=(",", ":"))
            item_keys = tuple(identity + ":" + str(i) for i in range(steps + 1))
            branches.append(Branch(path + (index,) if split else path, values, item_keys))
    result = DataTree(tuple(branches))
    return {"R": result, "Flat": topology(result, "flatten"), "Count": total}
