"""Regular hexagon cells clipped to a planar boundary, optionally periodic in U."""
import math

from .delaunay import EPS, _constrained, area2, polygon_area
from .tessellation import MAX_CELLS, MAX_VERTICES
from .voronoi import _intersection, _merge_fragments


DEFAULT_CELL_SIZE = 5.


def layout(outline, size, period, checkpoint):
    """Return indexed faces, lattice IDs and the centers of complete cells.

    Coordinates start at the bounds minimum. Size is the distance between
    opposite vertical sides of a hexagon. A horizontal translation by one
    column preserves both even and odd rows.
    """
    area = polygon_area(outline)
    if area < 0.:
        outline, area = outline[::-1], -area
    if area <= EPS or size <= EPS or not math.isfinite(size):
        raise ValueError('Hexagon Tiling needs a positive Cell Size and a usable Boundary.')
    width, height = map(max, zip(*outline))
    columns = 0
    if period:
        if period / size > MAX_CELLS + .5:
            raise ValueError('Hexagon Tiling exceeds the indexed geometry budget. Increase Cell Size.')
        columns = max(1, math.floor(period / size + .5))
        size = period / columns
    half = size / 2
    radius = size / math.sqrt(3)
    step = 1.5 * radius
    rows = math.ceil((height + radius) / step)
    last_column = math.ceil(width / size + .5)
    if (rows + 1) * (last_column + 2) > 4 * MAX_CELLS:
        raise ValueError('Hexagon Tiling exceeds the indexed geometry budget. Increase Cell Size.')
    offsets = ((half, radius / 2), (0., radius), (-half, radius / 2),
               (-half, -radius / 2), (0., -radius), (half, -radius / 2))
    convex = all(area2(outline[i-2], outline[i-1], outline[i]) >= -EPS for i in range(len(outline)))
    clips = (outline,) if convex else tuple(tuple(outline[i] for i in ids) for ids in
                                           _constrained(outline, range(len(outline)), checkpoint))
    vertices, index, cells, owners = [], {}, [], []
    full_area = 3 * half * radius
    for row in range(rows + 1):
        cy = row * step
        for column in range(-1, last_column + 1):
            checkpoint()
            cx = (column + .5 * (row % 2)) * size
            hexagon = [(cx + x, cy + y) for x, y in offsets]
            fragments = _merge_fragments([_intersection(hexagon, clip) for clip in clips])
            for piece, polygon in enumerate(fragments):
                complete = math.isclose(polygon_area(polygon), full_area, rel_tol=1e-8, abs_tol=EPS)
                ids = []
                for point in polygon:
                    idx = index.get(point)
                    if idx is None:
                        idx = index[point] = len(vertices)
                        vertices.append(point)
                    ids.append(idx)
                cells.append(ids)
                tile, position = divmod(column, columns) if columns else (0, column)
                owners.append((row, position, tile, piece, (cx, cy) if complete else None))
                if len(cells) > MAX_CELLS or len(vertices) > MAX_VERTICES:
                    raise ValueError('Hexagon Tiling exceeds the indexed geometry budget. Increase Cell Size.')
    covered = sum(polygon_area([vertices[i] for i in cell]) for cell in cells)
    if not math.isclose(covered, area, rel_tol=2e-7, abs_tol=5e-10):
        raise ValueError('Hexagon Tiling could not cover the whole Boundary at this Cell Size.')
    if columns:
        left = sorted(y for x, y in vertices if x == 0.)
        right = sorted(y for x, y in vertices if x == round(period, 11))
        if len(left) != len(right) or any(abs(a - b) > 5e-10 for a, b in zip(left, right)):
            raise ValueError('Hexagon Tiling could not reconcile the two U seam borders.')
    return vertices, cells, owners
