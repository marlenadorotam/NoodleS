"""Planar nearest-site cells, with clipping and cylindrical U periodicity."""
from collections import defaultdict
import math

from .delaunay import EPS, _constrained, _inside, area2, polygon_area


def _edges(ring):
    return zip(ring, (*ring[1:], ring[0]))


def _clip(ring, nx, ny, ox, oy):
    """Clip a convex polygon to one oriented half-plane."""
    result = []
    if not ring:
        return result
    for a, b in _edges(ring):
        da = nx * (a[0] - ox) + ny * (a[1] - oy)
        db = nx * (b[0] - ox) + ny * (b[1] - oy)
        if da <= 0.:
            result.append(a)
        if (da < 0. < db) or (db < 0. < da):
            t = da / (da-db)
            result.append((a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t))
    return result


def _clean(ring):
    # Quantize shared intersections so adjacent contours use the same edge.
    points = []
    for x, y in ring:
        p = round(x, 11), round(y, 11)
        if not points or points[-1] != p:
            points.append(p)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _intersection(cell, triangle):
    for a, b in _edges(triangle):
        cell = _clip(cell, b[1]-a[1], a[0]-b[0], *a)
    return _clean(cell)


def _merge_fragments(fragments):
    """Cancel triangle cuts and trace the actual (possibly disconnected) rings."""
    fragments = [ring for ring in fragments if len(ring) >= 3 and polygon_area(ring) > EPS]
    if len(fragments) <= 1:
        return fragments
    edges = set()
    for ring in fragments:
        for a, b in _edges(ring):
            if (b, a) in edges:
                edges.remove((b, a))
            else:
                edges.add((a, b))
    outgoing = defaultdict(set)
    for a, b in edges:
        outgoing[a].add(b)
    rings = []
    while outgoing:
        start = a = min(outgoing)
        previous = None
        ring = []
        while True:
            ring.append(a)
            options = outgoing.get(a)
            if not options:
                raise ValueError('Voronoi could not join the clipped boundary fragments.')
            if previous is None or len(options) == 1:
                b = min(options)
            else:
                back = math.atan2(previous[1]-a[1], previous[0]-a[0])
                b = min(options, key=lambda p: (back-math.atan2(p[1]-a[1], p[0]-a[0])) % math.tau)
            options.remove(b)
            if not options:
                del outgoing[a]
            if b == start:
                break
            previous, a = a, b
        if len(ring) >= 3 and polygon_area(ring) > EPS:
            rings.append(ring)
    return rings


def _nearest_cell(seed, polygon, ordered, index, checkpoint):
    sx, sy = seed
    reach = 4*max((x-sx)**2 + (y-sy)**2 for x, y in polygon)
    left, right = index-1, index+1
    while left >= 0 or right < len(ordered):
        dx_left = sx-ordered[left][0] if left >= 0 else math.inf
        dx_right = ordered[right][0]-sx if right < len(ordered) else math.inf
        if min(dx_left, dx_right)**2 > reach + EPS:
            break
        if dx_left <= dx_right:
            tx, ty = ordered[left][:2]
            left -= 1
        else:
            tx, ty = ordered[right][:2]
            right += 1
        dx, dy = tx-sx, ty-sy
        if dx*dx + dy*dy > reach + EPS:
            continue
        checkpoint()
        polygon = _clip(polygon, dx, dy, (sx+tx)*.5, (sy+ty)*.5)
        if not polygon:
            return []
        reach = 4*max((x-sx)**2 + (y-sy)**2 for x, y in polygon)
    return polygon


def cells(sites, ring, period, checkpoint):
    """Return shared vertices, cell index rings and their generating-site indices."""
    if polygon_area(ring) < 0.:
        ring = ring[::-1]
    area = polygon_area(ring)
    if area <= EPS or not all(_inside(p, ring) for p in sites):
        raise ValueError('Voronoi sites must lie in a boundary with positive area.')
    if period:
        sites = [(0. if abs(x-period) <= EPS or abs(x) <= EPS else x, y) for x, y in sites]
    if len(set(_clean(sites))) != len(sites):
        raise ValueError('Voronoi has coincident sites, including across the U seam.')

    min_x, min_y = (min(axis) for axis in zip(*ring))
    max_x, max_y = (max(axis) for axis in zip(*ring))
    def rectangle(x0, x1):
        return [(x0, min_y), (x1, min_y), (x1, max_y), (x0, max_y)]

    triangles = []
    if not period and any(area2(ring[i-2], ring[i-1], ring[i]) < -EPS for i in range(len(ring))):
        triangles = [[ring[i] for i in tri] for tri in _constrained(ring, range(len(ring)), checkpoint)]
    copies = (-1, 0, 1) if period else (0,)
    ordered = sorted((x + tile*period, y, i, tile) for tile in copies for i, (x, y) in enumerate(sites))
    center_indices = {i: index for index, (_, _, i, tile) in enumerate(ordered) if tile == 0}
    vertices, indices, faces, owners = [], {}, [], []
    for i, seed in enumerate(sites):
        checkpoint()
        x = seed[0]
        initial = rectangle(x-period/2, x+period/2) if period else rectangle(min_x, max_x) if triangles else ring
        cell = _nearest_cell(seed, initial, ordered, center_indices[i], checkpoint)
        if period:
            fragments = []
            for tile in copies:
                moved = [(x+tile*period, y) for x, y in cell]
                cut = _clip(_clip(moved, -1., 0., 0., 0.), 1., 0., period, 0.)
                fragments.append(_clean(cut))
            pieces = enumerate(_merge_fragments(fragments))
        elif triangles:
            pieces = list(enumerate(_merge_fragments([_intersection(cell, triangle) for triangle in triangles])))
        else:
            pieces = [(0, cell)]
        for piece, polygon in pieces:
            polygon = _clean(polygon)
            if len(polygon) < 3 or polygon_area(polygon) <= EPS:
                continue
            face = []
            for p in polygon:
                if p not in indices:
                    indices[p] = len(vertices)
                    vertices.append(p)
                face.append(indices[p])
            faces.append(face)
            owners.append([i, piece])
    covered = sum(polygon_area([vertices[i] for i in face]) for face in faces)
    if not math.isclose(covered, area, rel_tol=2e-7, abs_tol=5e-10):
        raise ValueError('Voronoi did not cover the whole boundary.')
    if period:
        left = sorted(y for x, y in vertices if x == 0.)
        right = sorted(y for x, y in vertices if x == round(period, 11))
        if len(left) != len(right) or any(abs(a-b) > 5e-10 for a, b in zip(left, right)):
            raise ValueError('Voronoi could not reconcile the two U seam borders.')
    return vertices, faces, owners
