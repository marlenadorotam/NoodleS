"""OCC boundary extraction and shared native parts for Penrose P2."""
import math

from .curves import PlaneValue, add, arc, dot, scale, sub
from .datatree import finite
from .penrose import pattern
from .penrose_node import DEFAULT_DIAMETER, DEFAULT_GENERATIONS
from .tessellation import MAX_CELLS, MAX_VERTICES
from .tessellation_native import _boundary, _checkpoint, build_wires


def layout(boundary, plane, diameter, generations, matching, checkpoint):
    if boundary is None:
        frame = plane or PlaneValue()
        diameter = finite(diameter)
        if diameter <= 0:
            raise ValueError('Sun Diameter must be positive.')
        center, radius, outline = frame.origin, diameter / 2, ()
    else:
        frame, ring = _boundary(boundary)
        if plane is not None:
            if abs(dot(plane.normal, frame.normal)) < 1. - 1e-7:
                raise ValueError('Plane must be parallel to Boundary.')
            frame = PlaneValue(frame.origin, plane.axis_x, frame.normal)
        offsets = [sub(p, frame.origin) for p in ring]
        uv = [complex(dot(delta, frame.axis_x), dot(delta, frame.axis_y)) for delta in offsets]
        middle = complex((min(p.real for p in uv) + max(p.real for p in uv)) / 2,
                         (min(p.imag for p in uv) + max(p.imag for p in uv)) / 2)
        center = frame.at(middle.real, middle.imag)
        # Fit the region strictly inside the decagon, regardless of its orientation.
        radius = max(abs(p - middle) for p in uv) / (math.cos(math.pi / 10) * .999)
        if radius <= 1e-9:
            raise ValueError('Boundary has no usable extent.')
        outline = tuple((p - middle) / radius for p in uv)

    def world(point):
        return add(center, add(scale(frame.axis_x, radius * point.real),
                               scale(frame.axis_y, radius * point.imag)))

    for tile, kind, polygons, decorations in pattern(generations, outline, matching, checkpoint):
        for piece, polygon in enumerate(polygons):
            yield tile, kind, piece, tuple(map(world, polygon))
        for piece, segment in enumerate(decorations):
            points = tuple(map(world, segment))
            try:
                arc('penrose', *points)
            except ValueError:
                # A boundary almost tangent to an arc can leave a sliver below CAD tolerance.
                if outline and math.dist(points[0], points[-1]) <= 1e-6:
                    continue
                raise
            yield tile, 'arc', piece, points


def indexed(records, budget):
    vertices, index, cells = [], {}, []
    for tile, kind, piece, points in records:
        ids = []
        for point in points:
            if point not in index:
                index[point] = len(vertices)
                vertices.append(point)
                budget[1] -= 1
            ids.append(index[point])
        budget[0] -= 1
        if min(budget) < 0:
            raise ValueError('Penrose P2 exceeds the geometry budget. Reduce Generations or turn off Matching Arcs.')
        cells.append((tile, kind, piece, ids))
    return vertices, cells


def measure(plan, checkpoint):
    from .geometry import recipe_from_wire
    from .scene_curves import materialize

    rows, matching = plan.get('rows'), plan.get('matching_arcs')
    if not isinstance(rows, list) or not rows or type(matching) is not bool:
        raise ValueError('Invalid Penrose P2 layout.')
    result, boundaries = [], {}
    budget = [MAX_CELLS, MAX_VERTICES]
    for row in rows:
        checkpoint()
        boundary = None
        if row['boundary'] is not None:
            recipe = recipe_from_wire(row['boundary'])
            if recipe not in boundaries:
                boundaries[recipe] = materialize(recipe)
            boundary = boundaries[recipe]
        plane = PlaneValue(**row['plane']) if row['plane'] is not None else None
        result.append(indexed(layout(boundary, plane, row['diameter'], row['generations'], matching, checkpoint), budget))
    return result


def build_parts(curves, wanted=lambda: True):
    from serpentine3d.core import geometry as g

    checkpoint = _checkpoint(wanted)
    polygons, decorations = [], []
    for kind, points in curves:
        checkpoint()
        if kind == 'arc':
            decorations.append(g.make_arc_3pt(*points))
        else:
            polygons.append(points)
    return build_wires(polygons, wanted) + decorations


def register_commands(ctx):
    from .operation_native import native_job
    from .penrose import MAX_GENERATIONS

    req = ctx.requests()

    @ctx.command('penrosep2', mutates=False, label='Penrose P2')
    def command(c):
        mode = yield req.OptionReq('Penrose P2 region', ['Sun', 'Boundary'], 'Sun')
        sources, plane, diameter = [], None, DEFAULT_DIAMETER
        if mode == 'Boundary':
            sources = yield req.SelectReq('Select convex boundary', kinds=('curve', 'surface'), min_count=1, max_count=1)
        else:
            origin = yield req.PointReq('Sun center', default=tuple(map(float, c.cplane.origin)))
            plane = PlaneValue(tuple(map(float, origin)), tuple(map(float, c.cplane.xdir)),
                               tuple(map(float, c.cplane.normal)))
            diameter = yield req.LengthReq('Sun diameter', default=DEFAULT_DIAMETER, minimum=1e-6)
        generations = yield req.IntReq(f'Generations (0–{MAX_GENERATIONS})', default=DEFAULT_GENERATIONS, minimum=0)
        arcs = yield req.OptionReq('Matching arcs', ['On', 'Off'], 'On')

        def build(shapes):
            records = layout(shapes[0] if shapes else None, plane, diameter, generations, arcs == 'On',
                             _checkpoint(lambda: True))
            vertices, cells = indexed(records, [MAX_CELLS, MAX_VERTICES])
            return build_parts((kind, tuple(vertices[i] for i in ids)) for _, kind, _, ids in cells)

        native_job(ctx, c, sources, build, 'Penrose P2')
