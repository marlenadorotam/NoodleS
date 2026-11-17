"""Similarity transforms shared by graph evaluation and OCC."""
from dataclasses import dataclass
import math

from .arithmetic import finite_number


IDENTITY_AXES = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _determinant(axes):
    x, y, z = axes
    return x[0]*(y[1]*z[2]-y[2]*z[1]) - x[1]*(y[0]*z[2]-y[2]*z[0]) + x[2]*(y[0]*z[1]-y[1]*z[0])


@dataclass(frozen=True)
class RigidMotion:
    """Historical name for the matrix stored in existing Move metadata."""
    axes: tuple = IDENTITY_AXES
    offset: tuple = (0., 0., 0.)

    @property
    def factor(self):
        return math.hypot(*self.axes[0])

    @property
    def directions(self):
        factor = self.factor
        return tuple(tuple(v / factor for v in row) for row in self.axes)

    @property
    def reflected(self):
        return _determinant(self.directions) < 0.

    def direction(self, value):
        return tuple(_dot(row, value) for row in self.axes)

    def point(self, value):
        return tuple(x + y for x, y in zip(self.direction(value), self.offset))

    def after(self, earlier):
        if self.axes == earlier.axes == IDENTITY_AXES:
            return RigidMotion(offset=self.point(earlier.offset))
        columns = tuple(zip(*earlier.axes))
        return RigidMotion(tuple(tuple(_dot(row, col) for col in columns) for row in self.axes),
                           self.point(earlier.offset))

    def inverse(self):
        factor = self.factor
        inverse = RigidMotion(tuple(tuple(v / factor / factor for v in row)
                                    for row in zip(*self.axes)))
        return RigidMotion(inverse.axes, inverse.direction(tuple(-v for v in self.offset)))

    def to_wire(self):
        return [list((*row, t)) for row, t in zip(self.axes, self.offset)]


IDENTITY = RigidMotion()


def from_wire(data):
    if not isinstance(data, (list, tuple)) or len(data) != 3 or any(
            not isinstance(row, (list, tuple)) or len(row) != 4 for row in data):
        raise ValueError('Invalid geometry transform.')
    rows = tuple(tuple(finite_number(x) for x in row) for row in data)
    axes = tuple(row[:3] for row in rows)
    factor = math.hypot(*axes[0])
    if not math.isfinite(factor) or factor == 0.:
        raise ValueError('Transform scale must be finite and positive.')
    motion = RigidMotion(axes, tuple(row[3] for row in rows))
    directions = motion.directions
    if any(not math.isclose(_dot(a, b), float(i == j), abs_tol=1e-8)
           for i, a in enumerate(directions) for j, b in enumerate(directions)):
        raise ValueError('Transform axes must be orthogonal with a uniform scale.')
    return motion


def rotation(center, axis, degrees):
    angle = math.radians(math.remainder(finite_number(degrees), 360.))
    if angle == 0.:
        return IDENTITY
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    m = 1. - c
    linear = RigidMotion(((c+m*x*x, m*x*y-s*z, m*x*z+s*y),
                         (m*y*x+s*z, c+m*y*y, m*y*z-s*x),
                         (m*z*x-s*y, m*z*y+s*x, c+m*z*z)))
    return RigidMotion(linear.axes, tuple(a-b for a, b in zip(center, linear.direction(center))))


def uniform_scale(center, factor):
    factor = finite_number(factor)
    if factor <= 0.:
        raise ValueError('Scale Factor must be greater than zero.')
    return RigidMotion(tuple(tuple(factor * v for v in row) for row in IDENTITY_AXES),
                       tuple(finite_number((1. - factor) * v) for v in center))


def orient_frames(source, target):
    source_basis = (source.axis_x, source.axis_y, source.normal)
    target_rows = zip(target.axis_x, target.axis_y, target.normal)
    axes = tuple(tuple(_dot(row, col) for col in zip(*source_basis)) for row in target_rows)
    linear = RigidMotion(axes)
    return RigidMotion(axes, tuple(a - b for a, b in zip(target.origin, linear.direction(source.origin))))


def reflection(origin, normal):
    linear = RigidMotion(tuple(tuple(float(i == j) - 2. * a * b for j, b in enumerate(normal))
                               for i, a in enumerate(normal)))
    return RigidMotion(linear.axes, tuple(a-b for a, b in zip(origin, linear.direction(origin))))
