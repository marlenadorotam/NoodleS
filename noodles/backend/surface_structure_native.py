"""Exact OCC topology and braced grids measured by the shared worker."""
import math
import time

from .datatree import MAX_ITEMS
from .surface_structure import (BRACED_GRID, DECONSTRUCT, MAX_DIVISIONS, MAX_MEMBERS, MAX_PANELS, MAX_SOURCES,
                                SURFACE_BOX, UV_PANELS, divisions, panel_count)


def indexed_shapes(shape, kind):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    items = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, items)
    if items.Extent() > MAX_ITEMS:
        raise ValueError('Brep topology exceeds the item limit.')
    return tuple(items.FindKey(i) for i in range(1, items.Extent() + 1))


def brep_parts(shape):
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopoDS import TopoDS

    faces = indexed_shapes(shape, TopAbs_FACE)
    if not faces:
        raise ValueError('Deconstruct Brep requires geometry with native faces.')
    edges = tuple(edge for edge in indexed_shapes(shape, TopAbs_EDGE)
                  if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(edge)))
    return faces + edges, len(faces)


def brep_vertices(shape):
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopoDS import TopoDS

    return [list(BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex)).Coord())
            for vertex in indexed_shapes(shape, TopAbs_VERTEX)]


def braced_grid(face, u, v, wanted=lambda: True):
    from .map_surface_native import FaceUV

    if u * (v + 1) + v * (u + 1) + u * v > MAX_MEMBERS:
        raise ValueError(f'Braced grid exceeds {MAX_MEMBERS} members. Reduce the divisions.')
    uv = FaceUV(face, False)
    if (uv.full[0] and u < 2) or (uv.full[1] and v < 2):
        raise ValueError('Use at least two divisions along a full periodic direction.')
    (u0, u1), (v0, v1) = uv.domains
    grid = [(u0 + (u1-u0)*i/u, v0 + (v1-v0)*j/v) for j in range(v + 1) for i in range(u + 1)]
    points = [uv.surface.Value(*p).Coord() for p in grid]
    inside = [uv.inside(p) for p in grid]
    index = lambda i, j: j * (u + 1) + i
    aliases = []
    for j in range(v + 1):
        for i in range(u + 1):
            a = 0 if uv.full[0] and i == u else i
            b = 0 if uv.full[1] and j == v else j
            if uv.pole(grid[index(i, j)][1]):
                a = 0
            aliases.append(index(a, b))

    seen = set()
    deadline = time.perf_counter() + .004

    def collect(candidates):
        nonlocal deadline
        output = []
        for a, b in candidates:
            if time.perf_counter() >= deadline:
                if not wanted():
                    raise ValueError('Braced grid was superseded.')
                time.sleep(.001)
                deadline = time.perf_counter() + .004
            pair = tuple(sorted((aliases[a], aliases[b])))
            if (pair not in seen and inside[a] and inside[b] and
                    math.dist(points[pair[0]], points[pair[1]]) > 1e-7 and
                    uv.contains_segment(grid[a], grid[b])):
                seen.add(pair)
                output.append(pair)
        return output

    primary = collect((index(i, j), index(i+1, j)) for j in range(v+1) for i in range(u))
    primary += collect((index(i, j), index(i, j+1)) for j in range(v) for i in range(u+1))
    braces = collect((index(i, j), index(i+1, j+1)) for j in range(v) for i in range(u))
    return points, primary, braces


def measure(plan, wanted, cache):
    from serpentine3d.core import geometry as g
    from .moves import geometry_from_wire
    from .scene_curves import materialize
    from .surface_uv_native import select_face

    operation, rows = plan.get('operation'), plan.get('rows')
    panels_or_boxes = operation in (UV_PANELS, SURFACE_BOX)
    if (operation not in (DECONSTRUCT, BRACED_GRID) and not panels_or_boxes or not isinstance(rows, list)
            or len(rows) > MAX_SOURCES):
        raise ValueError('Invalid surface structure request.')
    shapes, budget, results = {}, [MAX_ITEMS], []
    sources, decoded = plan.get('sources'), {}
    if panels_or_boxes and (not isinstance(sources, list) or not 1 <= len(sources) <= len(rows)):
        raise ValueError('Invalid UV Panels sources.')

    def resolve(value):
        if value not in shapes:
            shapes[value] = materialize(value, resolve=resolve, topology_cache=cache)
        return shapes[value]

    members = vertex_count = panel_cells = 0
    for row in rows:
        if not wanted():
            return []
        if panels_or_boxes:
            index = row['source']
            if type(index) is not int or not 0 <= index < len(sources):
                raise ValueError('Invalid UV Panels source index.')
            if index not in decoded:
                decoded[index] = geometry_from_wire(sources[index], budget=budget)
            value = decoded[index]
        else:
            value = geometry_from_wire(row['shape'], budget=budget)
        shape = resolve(value)
        if operation == DECONSTRUCT:
            parts, faces = brep_parts(shape)
            points = brep_vertices(shape)
            members += len(parts) + len(points)
            result = faces, len(parts) - faces, points
        elif panels_or_boxes:
            from .splines import integer

            face = row['face']
            u = integer(row['u'], 'U Count', 1, MAX_PANELS)
            v = integer(row['v'], 'V Count', 1, MAX_PANELS)
            panel_cells = panel_count(u, v, panel_cells, 'Surface Box' if operation == SURFACE_BOX else 'UV Panels')
            if operation == SURFACE_BOX:
                from .box_morph_native import build_surface_boxes
                result = list(build_surface_boxes(shape, face, u, v, row['height'], wanted))
            else:
                from .isotrim_native import build_uv_panels
                panels = tuple(build_uv_panels(shape, face, u, v, wanted))
                result = [(i, j, bounds) for i, j, bounds, _ in panels]
                if cache is not None and wanted():
                    key = UV_PANELS, value, face
                    cache.setdefault(key, {}).update((bounds, part) for _, _, bounds, part in panels)
                    cache.move_to_end(key)
                    while len(cache) > 128 or sum(map(len, cache.values())) > MAX_ITEMS:
                        cache.popitem(last=False)
        else:
            face = select_face(g.faces_of(shape), row['face'])
            u = divisions(row['u'], 'U Divisions')
            points, primary, braces = braced_grid(face, u, divisions(row['v'], 'V Divisions'), wanted)
            used = sorted({i for pair in (*primary, *braces) for i in pair})
            # Keep the integer UV grid slot stable when the row width changes.
            slots = {i: i // (u+1) * (MAX_DIVISIONS+1) + i % (u+1) for i in used}
            result = ([(slots[i], points[i]) for i in used],
                      [(slots[a], slots[b]) for a, b in primary],
                      [(slots[a], slots[b]) for a, b in braces])
            members += len(primary) + len(braces)
            vertex_count += len(used)
        if members > (MAX_MEMBERS if operation == BRACED_GRID else MAX_ITEMS) or vertex_count > MAX_ITEMS:
            raise ValueError('Surface structure exceeds the total item budget.')
        results.append(result)
    return results


def register_commands(ctx):
    from .operation_native import native_job
    req = ctx.requests()

    @ctx.command('bracedgrid1d', mutates=False, label='Braced Grid 1-D Structure')
    def command(c):
        from serpentine3d.core import geometry as g
        from .surface_uv_native import select_face

        sources = yield req.SelectReq('Select a single-face surface', kinds=('surface',), min_count=1, max_count=1)
        u = divisions((yield req.NumberReq('U Divisions', default=10, minimum=1)), 'U Divisions')
        v = divisions((yield req.NumberReq('V Divisions', default=10, minimum=1)), 'V Divisions')

        def build(shapes):
            points, a, b = braced_grid(select_face(g.faces_of(shapes[0]), 0), u, v)
            if not a and not b:
                raise ValueError('No braced grid members fit the trimmed surface.')
            return [g.make_compound([g.make_line(points[i], points[j]) for i, j in (*a, *b)])]

        native_job(ctx, c, sources, build, 'Braced Grid 1-D Structure')
