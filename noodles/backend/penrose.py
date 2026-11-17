"""Planar Penrose P2 subdivision, independent of Qt and OCC.

The half-tile substitution follows Simon Tatham's P2 diagrams:
https://www.chiark.greenend.org.uk/~sgtatham/quasiblog/aperiodic-tilings/
"""
import cmath
from dataclasses import dataclass
import math


INV_PHI = (math.sqrt(5) - 1) / 2
MAX_GENERATIONS = 6
KITE = 'kite'
DART = 'dart'


@dataclass(frozen=True)
class Tile:
    kind: str
    points: tuple[tuple[float, float], ...]
    complete: bool
    axis: tuple[complex, complex]


def _subdivide(kind, a, b, c):
    # a–c is the symmetry edge. The vertex order carries the reflection.
    if kind == DART:
        split = a + INV_PHI * (b - a)
        return (DART, b, c, split), (KITE, c, split, a)
    split = c + INV_PHI * (a - c)
    edge_split = b + INV_PHI * (c - b)
    return (DART, c, split, edge_split), (KITE, split, a, b), (KITE, split, edge_split, b)


def sun(generations, checkpoint=lambda: None):
    """Subdivide a unit-radius five-kite sun; retain partial tiles at its border."""
    if type(generations) is not int or not 0 <= generations <= MAX_GENERATIONS:
        raise ValueError(f'Penrose P2 generations must be an integer between 0 and {MAX_GENERATIONS}.')
    ring = [cmath.rect(1, i * math.tau / 10) for i in range(10)]
    halves = [(KITE, ring[i], ring[(i + side) % 10], 0j)
              for i in range(0, 10, 2) for side in (-1, 1)]
    for _ in range(generations):
        refined = []
        for half in halves:
            checkpoint()
            refined.extend(_subdivide(*half))
        halves = refined

    vertices, groups = {}, {}
    for kind, a, b, c in halves:
        checkpoint()
        a, b, c = (vertices.setdefault((round(z.real, 11), round(z.imag, 11)), z)
                   for z in (a, b, c))
        # Pair only halves of the same type with the same directed symmetry edge.
        groups.setdefault((kind, a, c), []).append(b)

    tiles = []
    for (kind, a, c), sides in groups.items():
        if len(sides) == 1:
            polygon = (a, sides[0], c)
        else:
            if len(sides) != 2 or ((sides[0] - a) / (c - a)).imag * ((sides[1] - a) / (c - a)).imag >= 0:
                raise ValueError('Invalid Penrose half-tile pairing.')
            polygon = (a, sides[0], c, sides[1])
        if ((polygon[1] - a).conjugate() * (c - a)).imag < 0:
            polygon = polygon[:1] + polygon[:0:-1]
        tiles.append(Tile(kind, tuple((z.real, z.imag) for z in polygon), len(sides) == 2, (a, c)))
    return tuple(tiles)


EPSILON = 1e-10


def _cross(a, b):
    return (a.conjugate() * b).imag


def _ring(points):
    return tuple(zip(points, (*points[1:], points[0]))) if points else ()


def _canonical(point):
    return complex(round(point.real, 11), round(point.imag, 11))


def _convex_sides(outline):
    if not outline:
        return ()
    area = sum(_cross(a, b) for a, b in _ring(outline))
    if abs(area) <= EPSILON:
        raise ValueError('Penrose P2 needs a boundary with positive area.')
    if area < 0:
        outline = outline[::-1]
    sides = tuple((a, (b - a) / abs(b - a)) for a, b in _ring(outline) if abs(b - a) > EPSILON)
    if any(_cross(direction, p - a) < -EPSILON for a, direction in sides for p in outline):
        raise ValueError('Penrose P2 Boundary must be a convex polygon.')
    return sides


def _inside(point, sides):
    return all(_cross(direction, point - a) >= -EPSILON for a, direction in sides)


def _clip_polygon(points, sides):
    for origin, direction in sides:
        clipped = []
        for a, b in _ring(points):
            sa, sb = (_cross(direction, p - origin) for p in (a, b))
            if (sa >= -EPSILON) != (sb >= -EPSILON):
                t = max(0., min(1., sa / (sa - sb)))
                clipped.append(a + t * (b - a))
            if sb >= -EPSILON:
                clipped.append(b)
        points = tuple(clipped)
    points = tuple(dict.fromkeys(map(_canonical, points)))
    if len(points) >= 3 and sum(_cross(a, b) for a, b in _ring(points)) > EPSILON:
        return points
    return ()


def _clip_tile(points, sides):
    if all(_inside(p, sides) for p in points):
        return (tuple(map(_canonical, points)),)
    if any(all(_cross(direction, p - a) < -EPSILON for p in points) for a, direction in sides):
        return ()
    if len(points) == 3:
        return tuple(filter(None, (_clip_polygon(points, sides),)))
    a, b, c, d = points
    halves = tuple(filter(None, (_clip_polygon((a, b, c), sides), _clip_polygon((a, c, d), sides))))
    if len(halves) < 2:
        return halves
    first, second = map(_ring, halves)
    shared = {(a, b) for a, b in first if (b, a) in second}
    if not shared:
        return halves  # A convex window can hit both arms of a Dart independently.
    successors = {a: b for a, b in (*first, *second) if (a, b) not in shared and (b, a) not in shared}
    point = next(iter(successors))
    result = []
    while successors:
        result.append(point)
        point = successors.pop(point)
    return (tuple(result),)


def _arcs(tile, points):
    a, c = tile.axis
    b = next(p for p in points if p not in tile.axis)
    if tile.kind == KITE:
        short = abs(b - a)
        radii = INV_PHI**2 * short, short
    else:
        short = abs(b - c)
        radii = (INV_PHI * short,) * 2
    for center, radius in zip(tile.axis, radii):
        i = points.index(center)
        start = cmath.phase(points[(i + 1) % len(points)] - center)
        sweep = (cmath.phase(points[i - 1] - center) - start) % math.tau
        yield center, radius, start, sweep


def _clip_arc(center, radius, start, sweep, sides):
    breaks = [0., sweep]
    for a, direction in sides:
        distance = -_cross(direction, center - a) / radius
        if -1. < distance < 1.:
            angle = math.asin(distance)
            for root in (angle, math.pi - angle):
                offset = (root + cmath.phase(direction) - start) % math.tau
                if EPSILON < offset < sweep - EPSILON:
                    breaks.append(offset)
    breaks.sort()
    for lo, hi in zip(breaks, breaks[1:]):
        mid = (lo + hi) / 2
        if hi - lo > EPSILON and _inside(center + cmath.rect(radius, start + mid), sides):
            yield tuple(_canonical(center + cmath.rect(radius, start + t)) for t in (lo, mid, hi))


def pattern(generations, outline=(), matching_arcs=True, checkpoint=lambda: None):
    """Return tile outlines and exact circular arcs in normalized coordinates."""
    sides = _convex_sides(outline)
    for index, tile in enumerate(sun(generations, checkpoint)):
        checkpoint()
        points = tuple(complex(*p) for p in tile.points)
        rings = _clip_tile(points, sides)
        if rings:
            decorations = (tuple(piece for arc in _arcs(tile, points) for piece in _clip_arc(*arc, sides))
                           if matching_arcs else ())
            yield index, tile.kind, rings, decorations
