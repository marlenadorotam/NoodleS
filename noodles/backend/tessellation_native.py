"""Native boundary extraction, indexed contour materialization and CAD command."""
import math
import time

from . import delaunay, honeycomb, voronoi
from .curves import PlaneValue, add, dot, scale, sub, xyz
from .delaunay_node import DELAUNAY, HEXAGON_TILING, SITE_LIMITS, TESSELLATION_SPECS, VORONOI
from .tessellation import MAX_CELLS, MAX_CONTOUR_VERTICES, MAX_VERTICES, contours


def _boundary(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from serpentine3d.core import geometry as g

    shape = g.unwrap_compound(shape)
    faces = g.faces_of(shape)
    if len(faces) > 1:
        raise ValueError('Boundary needs one planar face or a closed polygon.')
    if not faces and g.shape_kind(shape) != 'curve':
        raise ValueError('Boundary needs a closed polygon or planar face.')
    face = faces[0] if faces else g.planar_face(shape)
    surface = BRepAdaptor_Surface(face, True)
    if surface.GetType() != GeomAbs_Plane or not BRepCheck_Analyzer(face).IsValid():
        raise ValueError('Boundary needs one valid planar region.')
    wires = TopExp_Explorer(face, TopAbs_WIRE)
    wires.Next()
    if wires.More():
        raise ValueError('Boundary requires one outline without holes.')
    wire = BRepTools.OuterWire_s(face)
    if any(BRepAdaptor_Curve(edge).GetType() != GeomAbs_Line for edge in g.edges_of(wire)):
        raise ValueError('Boundary needs straight polygon sides.')
    ring, closed = g._wire_points(wire)
    if not closed or not 3 <= len(ring) <= 256:
        raise ValueError('Boundary needs a closed polygon with 3–256 corners.')
    plane = surface.Plane()
    return PlaneValue(g.pnt_tuple(plane.Location()), g.pnt_tuple(plane.XAxis().Direction()),
                      g.pnt_tuple(plane.Axis().Direction())), ring


def triangulate_sites(sites, boundary, plane, periodic, checkpoint, algorithm=DELAUNAY):
    name = TESSELLATION_SPECS[algorithm]['name']
    frame, ring = _boundary(boundary) if boundary is not None else (plane or delaunay.site_frame(sites, algorithm == VORONOI), ())
    if plane is not None and ring and abs(dot(plane.normal, frame.normal)) < 1.-1e-7:
        raise ValueError('Plane must be parallel to Boundary.')
    xaxis, yaxis = frame.axis_x, frame.axis_y
    def project(p):
        delta = sub(p, frame.origin)
        return dot(delta, xaxis), dot(delta, yaxis)

    uv = [project(p) for p in sites]
    border = [project(p) for p in ring]
    extent = border or uv
    u0, v0 = (min(v) for v in zip(*extent))
    u1, v1 = (max(v) for v in zip(*extent))
    width, height = u1-u0, v1-v0
    span = max(width, height)
    if span <= 1e-9:
        raise ValueError(f'{name} has no usable planar extent. Connect a Boundary for a single site.')
    if any(abs(dot(sub(p, frame.origin), frame.normal)) > max(1e-7, span*1e-8) for p in sites):
        raise ValueError(f'{name} points must lie in the same plane as Boundary or Plane.')
    def normalized(values):
        return [((u-u0)/span, (v-v0)/span) for u, v in values]

    points = normalized(uv)
    if len({(round(u,11),round(v,11)) for u,v in points}) != len(points):
        raise ValueError(f'{name} has duplicate or coincident points.')
    if periodic:
        _check_periodic_rectangle(border, u0, u1, v0, v1, span*1e-8)
    owners = None
    if algorithm == VORONOI:
        w, h = width/span, height/span
        outline = normalized(border) if border else [(-.05, -.05), (w+.05, -.05), (w+.05, h+.05), (-.05, h+.05)]
        points, faces, owners = voronoi.cells(points, outline, w if periodic else 0., checkpoint)
    elif periodic:
        points, faces = delaunay.periodic_u(points, width/span, height/span, checkpoint)
    elif border:
        points, faces = delaunay.bounded(points, normalized(border), checkpoint)
    else:
        faces = delaunay.triangulate(points, checkpoint)
    if (len(points) > MAX_VERTICES or len(faces) > MAX_CELLS
            or any(len(face) > MAX_CONTOUR_VERTICES for face in faces)):
        raise ValueError(f'{name} exceeds the indexed geometry budget.')
    origin = add(frame.origin, add(scale(xaxis,u0),scale(yaxis,v0)))
    world = [add(origin, add(scale(xaxis,u*span), scale(yaxis,v*span))) for u,v in points]
    result = world, [list(face) for face in faces]
    return (*result, owners) if owners is not None else result


def _check_periodic_rectangle(border, u0, u1, v0, v1, tolerance):
    corners = {(min((u0, u1), key=lambda x: abs(x-u)), min((v0, v1), key=lambda y: abs(y-v)))
               for u, v in border}
    if (len(border) != 4 or len(corners) != 4 or any(
            min(math.dist(point, corner) for corner in corners) > tolerance for point in border)):
        raise ValueError('Periodic U needs a rectangle aligned with the Boundary UV axes.')


def hexagon_tiling(boundary, plane, size, periodic, checkpoint):
    from .arithmetic import finite_number

    if boundary is None:
        raise ValueError('Hexagon Tiling requires a Boundary.')
    frame, ring = _boundary(boundary)
    if plane is not None:
        if abs(dot(plane.normal, frame.normal)) < 1. - 1e-7:
            raise ValueError('Plane must be parallel to Boundary.')
        frame = PlaneValue(frame.origin, plane.axis_x, plane.normal)
    offsets = [sub(point, frame.origin) for point in ring]
    border = [(dot(delta, frame.axis_x), dot(delta, frame.axis_y)) for delta in offsets]
    (u0, u1), (v0, v1) = ((min(axis), max(axis)) for axis in zip(*border))
    width, span = u1-u0, max(u1-u0, v1-v0)
    if span <= 1e-8:
        raise ValueError('Hexagon Tiling has no usable planar extent.')
    if periodic:
        _check_periodic_rectangle(border, u0, u1, v0, v1, span*1e-8)
    outline = [((u-u0)/span, (v-v0)/span) for u, v in border]
    points, cells, records = honeycomb.layout(outline, finite_number(size)/span, width/span if periodic else 0., checkpoint)

    def world(point):
        return frame.at(u0 + point[0]*span, v0 + point[1]*span)

    return ([world(point) for point in points], cells,
            [(*record[:4], world(record[4]) if record[4] is not None else None) for record in records])


def _checkpoint(wanted):
    deadline = time.perf_counter()+.004
    def check():
        nonlocal deadline
        if not wanted():
            raise ValueError('Tessellation superseded.')
        if time.perf_counter() >= deadline:
            time.sleep(.001)
            deadline = time.perf_counter()+.004
    return check


def measure(plan, wanted):
    from .geometry import recipe_from_wire
    from .scene_curves import materialize

    rows, periodic = plan.get('rows'), plan.get('periodic_u')
    algorithm = plan.get('algorithm', DELAUNAY)
    if algorithm == 'penrose_p2':
        from .penrose_native import measure as measure_penrose
        return measure_penrose(plan, _checkpoint(wanted))
    if not isinstance(algorithm, str) or algorithm not in TESSELLATION_SPECS:
        raise ValueError('Invalid tessellation algorithm.')
    name = TESSELLATION_SPECS[algorithm]['name']
    hexagons = algorithm == HEXAGON_TILING
    limit = MAX_CELLS if hexagons else SITE_LIMITS[algorithm]
    minimum = 3 if algorithm == DELAUNAY else 1
    if not isinstance(rows, list) or not 1 <= len(rows) <= limit//minimum or type(periodic) is not bool:
        raise ValueError(f'Invalid {name} layout.')
    total_sites = total_faces = total_vertices = 0
    result, boundaries = [], {}
    checkpoint = _checkpoint(wanted)
    for row in rows:
        checkpoint()
        boundary = None
        if row['boundary'] is not None:
            recipe = recipe_from_wire(row['boundary'])
            if recipe not in boundaries:
                boundaries[recipe] = materialize(recipe)
            boundary = boundaries[recipe]
        if periodic and boundary is None:
            raise ValueError('Periodic U requires a rectangular Boundary.')
        plane = PlaneValue(**row['plane']) if row['plane'] is not None else None
        if hexagons:
            layout = hexagon_tiling(boundary, plane, row['size'], periodic, checkpoint)
        else:
            points = row['sites']
            if not isinstance(points, list) or len(points) < minimum:
                raise ValueError(f'{name} needs at least {minimum} point(s) per branch.')
            total_sites += len(points)
            if total_sites > limit:
                raise ValueError(f'{name} exceeds the point budget.')
            layout = triangulate_sites(tuple(xyz(p) for p in points), boundary, plane, periodic, checkpoint, algorithm)
        total_faces += len(layout[1])
        total_vertices += len(layout[0])
        if total_faces > MAX_CELLS or total_vertices > MAX_VERTICES:
            raise ValueError(f'{name} exceeds the indexed geometry budget.')
        result.append(layout)
    return result


def build_wires(polygons, wanted=lambda: True):
    """Create native closed wires with one OCC edge per undirected segment."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeVertex
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Wire
    from OCP.gp import gp_Pnt

    checkpoint = _checkpoint(wanted)
    vertices, edges, wires = {}, {}, []
    builder = BRep_Builder()
    for ring in polygons:
        checkpoint()
        wire = TopoDS_Wire()
        builder.MakeWire(wire)
        for a,b in zip(ring, (*ring[1:],ring[0])):
            lo,hi = (a,b) if a<b else (b,a)
            key = lo,hi
            if key not in edges:
                for point in key:
                    if point not in vertices:
                        vertices[point] = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
                edges[key] = BRepBuilderAPI_MakeEdge(vertices[lo],vertices[hi]).Edge()
            edge = edges[key]
            builder.Add(wire, edge if a==lo else edge.Reversed())
        wire.Closed(True)
        wires.append(wire)
    return wires


def register_commands(ctx):
    from .operation_native import native_job

    req = ctx.requests()

    def command(c, algorithm, default, modes):
        from serpentine3d.core import geometry as g

        name = TESSELLATION_SPECS[algorithm]['name']
        mode = yield req.OptionReq(f'{name} mode', modes, default)
        minimum = 1 if algorithm == VORONOI and mode != default else 3 if algorithm == DELAUNAY else 2
        points = yield req.SelectReq(f'Select {name} points', kinds=('point',), min_count=minimum, max_count=SITE_LIMITS[algorithm])
        boundary = [] if mode == default else (
            yield req.SelectReq('Select boundary', kinds=('curve','surface'), min_count=1, max_count=1))

        def build(shapes):
            region = shapes[-1] if boundary else None
            sources = shapes[:-1] if boundary else shapes
            vertices, cells, *_ = triangulate_sites(tuple(g.point_coords(p) for p in sources),
                                                     region, None, mode == 'Periodic U',
                                                     _checkpoint(lambda: True), algorithm)
            return build_wires(contours(vertices,cells))

        native_job(ctx, c, [*points, *boundary], build, name)

    @ctx.command('delaunayparam', mutates=False, label='Delaunay')
    def delaunay_command(c):
        yield from command(c, DELAUNAY, 'Unbounded', ['Unbounded', 'Boundary', 'Periodic U'])

    @ctx.command('voronoiparam', mutates=False, label='Voronoi')
    def voronoi_command(c):
        yield from command(c, VORONOI, 'Auto Boundary', ['Auto Boundary', 'Boundary', 'Periodic U'])

    @ctx.command('hexagontiling', mutates=False, label='Hexagon Tiling')
    def hexagons_command(c):
        mode = yield req.OptionReq('Hexagon Tiling mode', ['Planar', 'Periodic U'], 'Planar')
        boundary = yield req.SelectReq('Select boundary', kinds=('curve', 'surface'), min_count=1, max_count=1)
        size = yield req.LengthReq('Cell size across flats', default=honeycomb.DEFAULT_CELL_SIZE, minimum=1e-6)

        def build(shapes):
            vertices, cells, _ = hexagon_tiling(shapes[0], None, size, mode == 'Periodic U', _checkpoint(lambda: True))
            return build_wires(contours(vertices, cells))

        native_job(ctx, c, boundary, build, 'Hexagon Tiling')
