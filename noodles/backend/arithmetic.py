"""Typed Addition/Multiplication and the requested Vector subtraction.

Pure mathematical data: no native scene transforms or geometry materialization.
Raw XYZ lists stay numeric lists. Vectors require an explicit VectorValue.
"""
from dataclasses import dataclass
import hashlib
import json
import math

from .datatree import Branch, DataTree, aligned, topology
from .point import PointValue


def finite_number(value):
    if type(value) not in (int, float):
        raise ValueError("Expected a finite Number, not Boolean or other data.")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("Number is outside the finite numeric range.") from exc
    if not math.isfinite(value):
        raise ValueError("Arithmetic requires finite numbers and finite results.")
    return value


@dataclass(frozen=True)
class VectorValue:
    xyz: tuple

    def __post_init__(self):
        if not isinstance(self.xyz, (list, tuple)) or len(self.xyz) != 3:
            raise ValueError("A Vector needs three numeric coordinates.")
        object.__setattr__(self, "xyz", tuple(finite_number(v) for v in self.xyz))


def normalize_arithmetic_state(data):
    modes = data.get("tree_modes", {})
    if not isinstance(modes, dict) or set(modes) - {"A", "B"}:
        raise ValueError("Invalid arithmetic input modifiers.")
    if any(mode not in ("none", "graft", "flatten") for mode in modes.values()):
        raise ValueError("Invalid arithmetic input modifier.")
    return {"tree_modes": {key: mode for key, mode in modes.items() if mode != "none"}}


def operand_kind(value):
    if isinstance(value, VectorValue):
        return "vector"
    if isinstance(value, PointValue):
        return "point"
    finite_number(value)
    return "number"


def arithmetic_tree(value, mode="none"):
    """Validate one homogeneous Number/Vector/Point input without losing paths."""
    if not isinstance(value, DataTree):
        def legacy_number(item):
            # The former flat numeric parser also accepted numeric text.
            # Typed tree leaves still require numbers, as in that engine.
            if isinstance(item, str):
                try:
                    return finite_number(float(item))
                except (ValueError, OverflowError) as exc:
                    raise ValueError("Expected numeric text or Number/Vector/Point data.") from exc
            return item
        value = ([legacy_number(item) for item in value] if isinstance(value, (list, tuple))
                 else legacy_number(value))
    tree = topology(value, mode)
    kinds = {operand_kind(item) for branch in tree.branches for item in branch.items}
    if len(kinds) > 1:
        raise ValueError("Each arithmetic input must contain one data type: Number, Vector or Point.")
    return tree, next(iter(kinds), None)


def evaluate_arithmetic(operation, parameters, inputs):
    state = normalize_arithmetic_state(parameters)
    left, left_kind = arithmetic_tree(inputs["A"], state["tree_modes"].get("A", "none"))
    right, right_kind = arithmetic_tree(inputs["B"], state["tree_modes"].get("B", "none"))
    pair = (left_kind, right_kind)
    xyz = {"point", "vector"}
    if operation == "addition":
        valid = pair == ("number", "number") or all(kind in xyz for kind in pair)
    elif operation == "subtraction":
        if any(kind not in (None, "number", "vector") for kind in pair):
            raise ValueError("Subtraction requires Number − Number or Vector − Vector.")
        valid = pair in (("number", "number"), ("vector", "vector"))
    elif operation == "multiplication":
        valid = True  # Every Number/Vector/Point pair has an established rule.
    else:
        raise ValueError("Unknown arithmetic operation.")
    if left_kind is not None and right_kind is not None and not valid:
        if operation == "subtraction":
            raise ValueError("Subtraction requires Number − Number or Vector − Vector.")
        raise ValueError("Addition requires Number + Number or a pair of Point/Vector values.")

    def apply(a, b, keys):
        if pair == ("number", "number"):
            a, b = finite_number(a), finite_number(b)
            result = a + b if operation == "addition" else a - b if operation == "subtraction" else a * b
            return finite_number(result)
        if operation == "subtraction":
            return VectorValue(tuple(finite_number(x - y) for x, y in zip(a.xyz, b.xyz)))
        if operation == "multiplication" and all(kind in xyz for kind in pair):
            return finite_number(sum(x * y for x, y in zip(a.xyz, b.xyz)))
        if operation == "addition":
            coordinates = tuple(finite_number(x + y) for x, y in zip(a.xyz, b.xyz))
        else:
            entity, factor = (b, a) if left_kind == "number" else (a, b)
            factor = finite_number(factor)
            coordinates = tuple(finite_number(x * factor) for x in entity.xyz)
        if "point" in pair:
            identity = json.dumps((operation, keys, getattr(a, "key", None), getattr(b, "key", None)),
                                  separators=(",", ":"))
            key = "math:" + hashlib.sha256(identity.encode()).hexdigest()
            return PointValue(key, coordinates)
        return VectorValue(coordinates)

    branches = []
    for path, rows in aligned(left, right):
        branches.append(Branch(path, tuple(apply(a, b, keys) for (a, b), keys in rows),
                               tuple("|".join(keys) for _, keys in rows)))
    result = DataTree(tuple(branches))
    collection = bool(state["tree_modes"]) or any(isinstance(v, (DataTree, list, tuple)) for v in inputs.values())
    return {"R": result if collection else result.values()[0]}
