"""Typed colors and model-space annotation descriptions."""
from dataclasses import dataclass
import math
import re

from .arithmetic import finite_number
from .curves import CurveInput, add, dot, scale, sub, unit, xyz
from .datatree import Branch, DataTree
from .domain import DomainValue
from .surface_uv import _match


GRADIENT = 'gradient'
TEXT_TAG = 'text_tag'
DIMENSION = 'dimension'
ANNOTATIONS = (TEXT_TAG, DIMENSION)
ANNOTATION_COLOR = '#86CBB4'
GRADIENT_SPEC = {'class': 'GradientNode', 'name': 'Gradient', 'category': 'Math', 'reference': False,
                 'inputs': (CurveInput('V', 'Values', 'number'), CurveInput('D', 'Domain (Optional)', 'dimension', optional=True),
                            CurveInput('A', 'Start Color', 'color', '#3889C7'),
                            CurveInput('M', 'Middle Color', 'color', '#73D2B6'),
                            CurveInput('B', 'End Color', 'color', '#F0AC50')),
                 'primary': 'C', 'outputs': ('C', 'D')}


@dataclass(frozen=True)
class ColorValue:
    rgb: tuple

    def __post_init__(self):
        rgb = tuple(self.rgb)
        if len(rgb) != 3 or any(type(channel) is not int or not 0 <= channel <= 255 for channel in rgb):
            raise ValueError('Color needs three 8-bit RGB channels.')
        object.__setattr__(self, 'rgb', rgb)

    def __str__(self):
        return '#{:02X}{:02X}{:02X}'.format(*self.rgb)


def color_value(value):
    if isinstance(value, ColorValue):
        return value
    if isinstance(value, str) and re.fullmatch(r'#[a-fA-F0-9]{6}', value.strip()):
        digits = value.strip()[1:]
        return ColorValue(tuple(int(digits[i:i+2], 16) for i in (0, 2, 4)))
    raise ValueError('Color requires an RGB color or text such as #73D2B6.')


def label_text(value):
    if not isinstance(value, str):
        value = str(value) if type(value) is bool else f'{finite_number(value):.8g}'
    value = ' '.join(value.splitlines()).replace('\t', ' ').strip()
    if len(value) > 160:
        raise ValueError('An annotation may contain up to 160 characters.')
    return value


def _gradient_color(value, domain, colors):
    start, end = domain.start, domain.end
    if start == end:
        return colors[1]
    value = max(min(start, end), min(max(start, end), value))
    span = end - start
    fraction = ((value - start)/span if math.isfinite(span) else
                (value/2 - start/2)/(end/2 - start/2))
    if fraction <= .5:
        left, right, mix = colors[0], colors[1], fraction*2
    else:
        left, right, mix = colors[1], colors[2], fraction*2 - 1
    return ColorValue(tuple(round(a + mix*(b - a)) for a, b in zip(left.rgb, right.rgb, strict=True)))


def evaluate_gradient(trees):
    from .curves import input_tree

    values = trees['V'].values()
    domain = trees.get('D')
    if domain is None:
        fallback = DomainValue(min(values), max(values)) if values else DomainValue(0, 0)
        domain = input_tree(fallback, GRADIENT_SPEC['inputs'][1])
    colors, domains = [], []
    for path, rows in _match(trees['V'], domain, trees['A'], trees['M'], trees['B']):
        result, used, keys = [], [], []
        for (value, interval, a, middle, b), provenance in rows:
            if not isinstance(interval, DomainValue):
                raise ValueError('Gradient D requires a Domain.')
            result.append(_gradient_color(value, interval, (a, middle, b)))
            used.append(interval)
            keys.append(provenance[0])
        colors.append(Branch(path, result, keys))
        domains.append(Branch(path, used, keys))
    return {'C': DataTree(tuple(colors)), 'D': DataTree(tuple(domains))}


@dataclass(frozen=True)
class AnnotationValue:
    key: str
    kind: str
    points: tuple
    text: str
    color: ColorValue
    size: float
    visible: bool

    def __post_init__(self):
        if self.kind not in ANNOTATIONS or len(self.points) != (1 if self.kind == TEXT_TAG else 4):
            raise ValueError('Invalid annotation points.')
        object.__setattr__(self, 'points', tuple(map(xyz, self.points)))
        if not isinstance(self.text, str) or type(self.visible) is not bool:
            raise ValueError('Invalid annotation text or visibility.')
        object.__setattr__(self, 'text', label_text(self.text))
        object.__setattr__(self, 'color', color_value(self.color))
        size = finite_number(self.size)
        if not 8 <= size <= 48:
            raise ValueError('Annotation size must be between 8 and 48 pixels.')
        object.__setattr__(self, 'size', size)

    @property
    def length(self):
        return math.dist(*self.points[:2])

    def to_wire(self):
        return {'key': self.key, 'kind': self.kind, 'points': self.points, 'text': self.text,
                'color': str(self.color), 'size': self.size, 'visible': self.visible}


def annotation_from_wire(item):
    points = item.get('points')
    if not isinstance(points, (tuple, list)):
        raise ValueError('Annotation requires a list of points.')
    return AnnotationValue(item['key'], item['kind'], tuple(points), item.get('text'), item.get('color'),
                           item.get('size'), item['visible'])


def build_annotation(operation, key, items):
    if operation == TEXT_TAG:
        point, text, color, size, visible = items
        return AnnotationValue(key, operation, (point.xyz,), text, color, size, visible)
    a, b, offset, text, color, size, visible = items
    start, end, shift = a.xyz, b.xyz, offset.xyz
    direction = sub(end, start)
    if math.hypot(*direction) > 1e-12:
        axis = unit(direction)
        perpendicular = sub(shift, scale(axis, dot(shift, axis)))
        magnitude = math.hypot(*shift)
        if magnitude and math.hypot(*perpendicular) <= magnitude*1e-12:
            guide = min(((0., 0., 1.), (0., 1., 0.), (1., 0., 0.)), key=lambda v: abs(dot(v, axis)))
            perpendicular = scale(unit(sub(guide, scale(axis, dot(guide, axis)))), magnitude)
        shift = perpendicular
    return AnnotationValue(key, operation, (start, end, add(start, shift), add(end, shift)), text, color, size, visible)
