"""Deferred spline definitions. Native fitting and measurement belong to the OCC worker."""
from dataclasses import dataclass
import hashlib
import json
import math

from .curves import CurveValue, xyz
from .datatree import MAX_ITEMS
from .arithmetic import finite_number


@dataclass(frozen=True)
class PendingGeometry:
    message: str = 'Waiting for native curve measurement'

    def __str__(self):
        return self.message


def integer(value, label, low, high):
    number = finite_number(value)
    if int(number) != number or not low <= number <= high:
        raise ValueError(f'{label} must be an integer {low}..{high}.')
    return int(number)


@dataclass(frozen=True)
class SplineValue(CurveValue):
    degree: int = 3
    periodic: bool = False
    knot_style: int = 1
    # Native snapshots contain exact poles, weights and unique knots/multiplicities.
    knots: tuple = ()
    multiplicities: tuple = ()
    weights: tuple = ()
    domain: tuple = ()
    measured_length: float | None = None

    def __post_init__(self):
        if self.kind not in ('curve', 'interpcurve'):
            raise ValueError('Invalid spline kind.')
        if not isinstance(self.key, str) or not self.key or len(self.key) > 256:
            raise ValueError('Invalid spline part key.')
        object.__setattr__(self, 'points', tuple(xyz(p) for p in self.points))
        if not 2 <= len(self.points) <= MAX_ITEMS:
            raise ValueError('Spline needs at least two points.')
        if type(self.closed) is not bool or type(self.periodic) is not bool:
            raise ValueError('Closed and Periodic must be Boolean.')
        object.__setattr__(self, 'degree', integer(self.degree, 'Degree', 1, 25))
        object.__setattr__(self, 'knot_style', integer(self.knot_style, 'Knot Style', 0, 2))
        if self.knots:
            if (len(self.knots) != len(self.multiplicities) or not 2 <= len(self.knots) <= MAX_ITEMS
                    or len(self.weights) != len(self.points) or len(self.domain) != 2):
                raise ValueError('Incomplete native NURBS definition.')
            for knot in self.knots:
                finite_number(knot)
            if any(b <= a for a, b in zip(self.knots, self.knots[1:])):
                raise ValueError('NURBS knots must increase.')
            for mult in self.multiplicities:
                integer(mult, 'Knot multiplicity', 1, self.degree+1)
            for weight in self.weights:
                if finite_number(weight) <= 0:
                    raise ValueError('NURBS weights must be positive.')
            lo, hi = map(finite_number, self.domain)
            if not self.knots[0] <= lo < hi <= self.knots[-1]:
                raise ValueError('Invalid native curve domain.')
            count = sum(self.multiplicities)
            expected = len(self.points) + self.degree + 1
            if self.periodic:
                expected = len(self.points) + self.multiplicities[0]
                if self.multiplicities[0] != self.multiplicities[-1]:
                    raise ValueError('Invalid periodic knot multiplicities.')
            if count != expected:
                raise ValueError('NURBS poles, knots and degree do not agree.')
            if self.measured_length is not None and finite_number(self.measured_length) <= 0:
                raise ValueError('Invalid native curve length.')
        elif self.multiplicities or self.weights or self.domain or self.measured_length is not None:
            raise ValueError('Incomplete native NURBS snapshot.')

    @property
    def length(self):
        return self.measured_length if self.measured_length is not None else PendingGeometry()

    def to_wire(self):
        data = {'key': self.key, 'kind': self.kind, 'points': [list(p) for p in self.points],
                'degree': self.degree, 'closed': self.closed, 'periodic': self.periodic,
                'knot_style': self.knot_style}
        if self.knots:
            data.update(knots=list(self.knots), multiplicities=list(self.multiplicities),
                        weights=list(self.weights), domain=list(self.domain), length=self.measured_length)
        return data


def spline(key, kind, points, degree=3, closed=False, periodic=False, knot_style=1):
    points = tuple(xyz(p) for p in points)
    degree = integer(degree, 'Degree', 2 if kind == 'curve' else 1, 10 if kind == 'curve' else 5)
    knot_style = integer(knot_style, 'Knot Style', 0, 2)
    if type(closed) is not bool or type(periodic) is not bool:
        raise ValueError('Closed and Periodic must be Boolean.')
    repeated = len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-9
    if repeated and (kind == 'interpcurve' or closed):
        points = points[:-1]
        closed = True
    if kind == 'interpcurve':
        if len(points) > 1200:
            raise ValueError('InterpCurve supports up to 1200 interpolation points per branch.')
        closed = closed or periodic
    if len(points) < 3 or any(math.dist(a, b) <= 1e-9 for a, b in zip(points, points[1:])):
        raise ValueError('Curve needs at least three points and distinct consecutive points.')
    if kind == 'curve':
        if len(set(points)) < 3:
            raise ValueError('Curve needs at least three distinct control points.')
        if not closed and degree >= len(points):
            raise ValueError('Open Curve needs at least Degree + 1 control points.')
        degree = min(degree, len(points)) if closed else degree
        periodic = closed
    elif (degree >= len(points) + int(closed and not periodic)
          and not (degree == 3 and knot_style == 1 and not periodic)):
        raise ValueError('InterpCurve Degree exceeds the number of interpolation points.')
    return SplineValue(key, kind, points, closed=closed, degree=degree, periodic=periodic, knot_style=knot_style)


def from_wire(data):
    args = (data.get('key'), data.get('kind'), data.get('points', ()))
    if 'knots' not in data:
        return spline(*args, data.get('degree', 3), data.get('closed', False),
                      data.get('periodic', False), data.get('knot_style', 1))
    return SplineValue(*args, closed=data.get('closed'), degree=data.get('degree'),
                       periodic=data.get('periodic'), knot_style=data.get('knot_style', 1),
                       knots=tuple(data['knots']), multiplicities=tuple(data.get('multiplicities', ())),
                       weights=tuple(data.get('weights', ())), domain=tuple(data.get('domain', ())),
                       measured_length=data.get('length'))


def signature(value):
    return hashlib.sha256(json.dumps(value.to_wire(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
