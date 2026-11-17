"""Shared scalar input validation and integer rounding."""
import math

NUMBER_LIMIT = 1_000_000_000


def finite_number(value):
    if type(value) not in (int, float):
        raise ValueError("Value must be a finite number.")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("Value must be a finite number.") from exc
    if not math.isfinite(value):
        raise ValueError("Value must be a finite number.")
    return value


def round_integer(value):
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def normalize_number_state(data):
    mode = data.get("mode", "double")
    if mode not in ("double", "integer"):
        raise ValueError("Number mode must be Double or Integer.")
    value = max(-NUMBER_LIMIT, min(NUMBER_LIMIT, finite_number(data.get("value", 0))))
    value = round_integer(value) if mode == "integer" else round(float(value), 4)
    return {"mode": mode, "value": value}
