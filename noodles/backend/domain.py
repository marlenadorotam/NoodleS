"""Numeric intervals, independent of Qt, geometry and the scene.

Keep the former Domain contract: ordered A/B, positive L, no zero span.
An interval is one tree item, never a two-item numeric list.
"""
from dataclasses import dataclass
import math

from .datatree import map_values, topology


def domain_number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e9:
        raise ValueError("Domain bounds must be finite numbers between -1e9 and 1e9.")
    return float(value)


@dataclass(frozen=True)
class DomainValue:
    start: float
    end: float

    def __post_init__(self):
        # Bounds must represent observed singleton intervals too. Construction
        # and consumers that require a nonzero span validate that explicitly.
        for name in ("start", "end"):
            value = getattr(self, name)
            if type(value) not in (int, float):
                raise ValueError("Domain bounds must be finite numbers.")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Domain bounds must be finite numbers.")
            object.__setattr__(self, name, value)

    @property
    def length(self):
        return abs(self.end - self.start)

    def to_wire(self):
        return {"type": "serpentine_domain", "start": self.start, "end": self.end}


def normalize_domain_state(data):
    modes = data.get("tree_modes", {})
    if not isinstance(modes, dict) or set(modes) - {"A", "B"}:
        raise ValueError("Invalid Domain input modifiers.")
    if any(mode not in ("none", "graft", "flatten") for mode in modes.values()):
        raise ValueError("Invalid Domain input modifier.")
    # Equal defaults are editable and persistable; evaluation reports the error.
    # This lets a user move both ends across one another in separate edits.
    return {"start": domain_number(data.get("start", 0.0)),
            "end": domain_number(data.get("end", 1.0)),
            "tree_modes": {key: mode for key, mode in modes.items() if mode != "none"}}


def evaluate_domain(parameters, inputs):
    state = normalize_domain_state(parameters)
    a, b = (topology(inputs.get(port, state[key]), state["tree_modes"].get(port, "none"))
            for port, key in (("A", "start"), ("B", "end")))
    def construct(start, end):
        domain = DomainValue(domain_number(start), domain_number(end))
        if domain.start == domain.end:
            raise ValueError("Domain A and B cannot be equal.")
        return domain
    domains = map_values(construct, a, b)
    return {"D": domains, "L": map_values(lambda domain: domain.length, domains)}
