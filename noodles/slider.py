"""Canonical Slider parameters shared by the widget, runtime and file reader."""
from .numeric import finite_number, round_integer

SLIDER_PROPERTIES = ("mode", "minimum", "maximum", "value")
SLIDER_LIMIT = 1_000_000_000


def slider_round(value, mode):
    if mode == "integer":
        return round_integer(value)
    return round(value, 2)


def clamp_slider_value(value, minimum, maximum, mode):
    value = max(minimum, min(maximum, finite_number(value)))
    return max(minimum, min(maximum, slider_round(value, mode)))


def normalize_slider_state(data, *, changed=None):
    mode = data.get("mode", "double")
    if mode not in ("double", "integer"):
        raise ValueError("Slider mode must be Double or Integer.")
    bounds = []
    for key, default in (("minimum", 0), ("maximum", 100)):
        value = max(-SLIDER_LIMIT, min(SLIDER_LIMIT, finite_number(data.get(key, default))))
        bounds.append(slider_round(value, mode))
    minimum, maximum = bounds
    if minimum > maximum:
        if changed == "minimum":
            maximum = minimum
        elif changed == "maximum":
            minimum = maximum
        else:
            raise ValueError("Slider Min must not exceed Max.")
    value = clamp_slider_value(data.get("value", 0), minimum, maximum, mode)
    return {"mode": mode, "minimum": minimum, "maximum": maximum, "value": value}
