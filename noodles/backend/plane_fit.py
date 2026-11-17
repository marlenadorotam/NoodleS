"""Least-squares plane data with a deterministic local coordinate frame."""
from itertools import combinations
from math import copysign, fsum, hypot, sqrt

from .arithmetic import VectorValue
from .curves import PlaneValue, dot, scale, sub, unit
from .datatree import Branch, DataTree
from .point import PointValue


AXIS_PAIRS = tuple(combinations(range(3), 2))


def _normal(covariance):
    # Jacobi rotations diagonalize the 3x3 symmetric covariance matrix.
    # Accumulating the rotations gives its principal axes as columns.
    axes = [[float(i == j) for j in range(3)] for i in range(3)]
    for _ in range(32):
        p, q = max(AXIS_PAIRS, key=lambda pair: abs(covariance[pair[0]][pair[1]]))
        off = covariance[p][q]
        if abs(off) <= 1e-15:
            break
        delta = (covariance[q][q] - covariance[p][p]) / (2 * off)
        tangent = copysign(1., delta) / (abs(delta) + hypot(1., delta))
        cosine = 1 / hypot(1., tangent)
        sine = tangent * cosine
        covariance[p][p] -= tangent * off
        covariance[q][q] += tangent * off
        covariance[p][q] = covariance[q][p] = 0.
        r = 3 - p - q
        a, b = covariance[r][p], covariance[r][q]
        covariance[r][p] = covariance[p][r] = cosine*a - sine*b
        covariance[r][q] = covariance[q][r] = sine*a + cosine*b
        for row in axes:
            a, b = row[p], row[q]
            row[p], row[q] = cosine*a - sine*b, sine*a + cosine*b
    smallest, middle, largest = sorted(range(3), key=lambda i: covariance[i][i])
    low, mid, high = (covariance[i][i] for i in (smallest, middle, largest))
    if mid <= high * 1e-12:
        raise ValueError('Plane Fit needs noncollinear points.')
    if mid - low <= high * 1e-12:
        raise ValueError('Plane Fit has no unique best-fit normal for these points.')
    normal = tuple(row[smallest] for row in axes)
    major = max(range(3), key=lambda i: abs(normal[i]))
    return scale(normal, -1.) if normal[major] < 0 else normal


def fit_plane(points):
    if len(points) < 3:
        raise ValueError('Plane Fit needs at least three points in a branch.')
    origin = tuple(fsum(p.xyz[i] for p in points) / len(points) for i in range(3))
    offsets = [sub(p.xyz, origin) for p in points]
    size = max(hypot(*offset) for offset in offsets)
    if size == 0:
        raise ValueError('Plane Fit needs noncollinear points.')
    normalized = [tuple(value / size for value in offset) for offset in offsets]
    covariance = [[fsum(p[i]*p[j] for p in normalized) / len(points) for j in range(3)] for i in range(3)]
    normal = _normal(covariance)
    guide = (1., 0., 0.) if abs(normal[0]) < .95 else (0., 1., 0.)
    frame = PlaneValue(origin, unit(sub(guide, scale(normal, dot(guide, normal)))), normal)
    residuals = [dot(p, frame.normal) for p in offsets]
    return frame, max(map(abs, residuals)), hypot(*residuals) / sqrt(len(points))


def evaluate_planes(operation, tree):
    ports = ('O', 'X', 'Y', 'Z') if operation == 'deconstruct_plane' else ('P', 'D', 'R')
    output = {port: [] for port in ports}
    for branch in tree.branches:
        if operation == 'deconstruct_plane':
            rows = tuple((PointValue(key, frame.origin), VectorValue(frame.axis_x),
                          VectorValue(frame.axis_y), VectorValue(frame.normal))
                         for key, frame in zip(branch.keys, branch.items, strict=True))
            keys = branch.keys
        else:
            keys = (':'.join(map(str, branch.path)) + ':fit',) if branch.items else ()
            try:
                rows = (fit_plane(branch.items),) if branch.items else ()
            except ValueError as exc:
                path = ';'.join(map(str, branch.path))
                raise ValueError(f'Branch {{{path}}}: {exc}') from exc
        for index, port in enumerate(ports):
            output[port].append(Branch(branch.path, tuple(row[index] for row in rows), keys))
    return {port: DataTree(tuple(branches)) for port, branches in output.items()}
