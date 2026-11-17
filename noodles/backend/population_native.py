"""Deterministic OCC point sampling by rectangle, length, area or volume."""
from bisect import bisect_right
from itertools import accumulate
import math
import random

from .curves import POPULATION_COUNT_LIMITS, add, cross, dot, scale, sub, xyz
from .population import POPULATION_LIMITS, POPULATION_SPECS, seed_for
from .splines import integer


def rectangle_frame(shape):
    from OCP.TopAbs import TopAbs_WIRE, TopAbs_FACE
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    shape = g.unwrap_compound(shape)
    if shape.ShapeType() == TopAbs_FACE:
        face = TopoDS.Face_s(shape)
        wires = TopExp_Explorer(face, TopAbs_WIRE)
        wires.Next()
        if BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane or wires.More():
            raise ValueError('Populate 2D needs one planar rectangle without holes.')
        shape = BRepTools.OuterWire_s(face)
    if shape.ShapeType() != TopAbs_WIRE or any(
            BRepAdaptor_Curve(e).GetType() != GeomAbs_Line for e in g.edges_of(shape)):
        raise ValueError('Populate 2D needs a closed rectangle with straight edges.')
    points, closed = g._wire_points(shape)
    if not closed or len(points) != 4:
        raise ValueError('Populate 2D needs a closed rectangle with four corners.')
    a, b, c, d = points
    x, y = sub(b, a), sub(d, a)
    lx, ly = math.hypot(*x), math.hypot(*y)
    if (min(lx, ly) <= 1e-10 or abs(dot(x, y)) > 1e-7*lx*ly
            or math.dist(c, add(b, y)) > 1e-7*max(lx, ly)):
        raise ValueError('Populate 2D needs a rectangular region.')
    return a, x, y


def sample_rectangle(frame, count, seed, prior=()):
    a, x, y = frame
    xx, yy = dot(x, x), dot(y, y)
    tolerance = 1e-7 * max(1., math.sqrt(xx), math.sqrt(yy))
    for point in prior:
        delta = sub(point, a)
        u, v = dot(delta, x)/xx, dot(delta, y)/yy
        if (not -1e-7 <= u <= 1.+1e-7 or not -1e-7 <= v <= 1.+1e-7
                or math.dist(delta, add(scale(x, u), scale(y, v))) > tolerance):
            raise ValueError('An Existing Point lies outside the rectangle.')
    rng = random.Random(seed)
    return [add(a, add(scale(x, rng.random()), scale(y, rng.random()))) for _ in range(count)]


def _weighted(items, rng):
    if not items:
        raise ValueError('Populate Geometry found no usable native geometry of the requested dimension.')
    limits = tuple(accumulate(item[0] for item in items))
    if not math.isfinite(limits[-1]) or limits[-1] <= 0:
        raise ValueError('Populate Geometry needs a finite positive geometric measure.')
    return lambda: items[min(len(items)-1, bisect_right(limits, rng.random()*limits[-1]))][1:]


def _curve_sampler(shape, rng):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint
    from serpentine3d.core import geometry as g

    items = []
    for edge in g.edges_of(shape):
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        if math.isfinite(first) and math.isfinite(last) and first < last:
            length = GCPnts_AbscissaPoint.Length_s(curve, first, last)
            if math.isfinite(length) and length > 1e-10:
                items.append((length, length, curve, first))
    choose = _weighted(items, rng)

    def sample():
        length, curve, start = choose()
        abscissa = GCPnts_AbscissaPoint(curve, rng.random()*length, start, 1e-7)
        if not abscissa.IsDone():
            raise ValueError('Populate Geometry could not evaluate a curve by arc length.')
        return g.pnt_tuple(curve.Value(abscissa.Parameter()))
    return sample


def _face_sampler(shape, rng):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.TopLoc import TopLoc_Location
    from OCP.gp import gp_Pnt2d
    from serpentine3d.core import geometry as g

    shape = g.copy_shape(shape)
    diagonal = math.dist(*g.bbox(shape))
    mesher = BRepMesh_IncrementalMesh(shape, max(1e-6, diagonal*.003), False, .3, False)
    if not mesher.IsDone():
        raise ValueError('Populate Geometry could not triangulate the surface.')
    triangles = []
    for face in g.faces_of(shape):
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None or not mesh.HasUVNodes():
            continue
        surface = BRepAdaptor_Surface(face, True)
        classify = BRepClass_FaceClassifier()
        for index in range(1, mesh.NbTriangles()+1):
            nodes = mesh.Triangle(index).Get()
            a, b, c = [g.pnt_tuple(mesh.Node(i)) for i in nodes]
            area = .5*math.hypot(*cross(sub(b, a), sub(c, a)))
            if area > 1e-15 and math.isfinite(area):
                uv = tuple((mesh.UVNode(i).X(), mesh.UVNode(i).Y()) for i in nodes)
                triangles.append((area, uv, surface, face, classify))
    choose = _weighted(triangles, rng)

    def sample():
        for _ in range(200):
            uv, surface, face, classify = choose()
            a, b = math.sqrt(rng.random()), rng.random()
            weights = (1.-a, a*(1.-b), a*b)
            u, v = (dot(weights, axis) for axis in zip(*uv))
            classify.Perform(face, gp_Pnt2d(u, v), g.tol())
            if classify.State() in (TopAbs_IN, TopAbs_ON):
                return g.pnt_tuple(surface.Value(u, v))
        raise ValueError('Populate Geometry could not find a point inside the trimmed face.')
    return sample


def _solid_sampler(solids, rng):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    from serpentine3d.core import geometry as g

    items = []
    for solid in solids:
        volume = abs(g.volume(solid))
        if math.isfinite(volume) and volume > 1e-12:
            bounds = g.bbox(solid)
            if all(math.isfinite(v) for p in bounds for v in p):
                items.append((volume, BRepClass3d_SolidClassifier(solid), bounds))
    choose = _weighted(items, rng)

    def sample():
        classifier, (low, high) = choose()
        for _ in range(1000):
            point = tuple(rng.uniform(a, b) for a, b in zip(low, high))
            classifier.Perform(gp_Pnt(*point), 1e-7)
            if classifier.State() in (TopAbs_IN, TopAbs_ON):
                return point
        raise ValueError('Populate Geometry could not sample inside this thin or complex solid.')
    return sample


def sample_geometry(shape, count, seed, wanted=lambda: True):
    from OCP.BRep import BRep_Tool
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    if not count:
        return []
    shape = g.unwrap_compound(shape)
    rng = random.Random(seed)
    solids = list(_shapes(shape, TopAbs_SOLID))
    if solids:
        sample = _solid_sampler([TopoDS.Solid_s(s) for s in solids], rng)
    elif g.faces_of(shape):
        sample = _face_sampler(shape, rng)
    elif g.edges_of(shape):
        face = None
        if shape.ShapeType() in (TopAbs_EDGE, TopAbs_WIRE) and g.is_closed_curve(shape):
            try:
                candidate = g.planar_face(shape)
                if BRepCheck_Analyzer(candidate).IsValid() and g.surface_area(candidate) > 1e-10:
                    face = candidate
            except (g.GeometryError, ValueError):
                pass  # Non-planar closed curves are sampled by length.
        sample = _face_sampler(face, rng) if face is not None else _curve_sampler(shape, rng)
    else:
        points = [g.pnt_tuple(BRep_Tool.Pnt_s(TopoDS.Vertex_s(v))) for v in _shapes(shape, TopAbs_VERTEX)]
        if not points:
            raise ValueError('Populate Geometry found no native points, curves, surfaces or solids.')
        sample = lambda: rng.choice(points)
    results = []
    for _ in range(count):
        if not wanted():
            return []
        results.append(sample())
    return results


def _shapes(shape, kind):
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def measure(plan, wanted):
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    operation = plan.get('operation')
    if operation not in POPULATION_LIMITS:
        raise ValueError('Unknown population operation.')
    regions, points = POPULATION_LIMITS[operation]
    count_limit = POPULATION_COUNT_LIMITS[POPULATION_SPECS[operation]['inputs'][1].kind]
    rows, sources = plan.get('rows'), plan.get('sources')
    if not isinstance(rows, list) or not isinstance(sources, list) or not 1 <= len(sources) <= len(rows) <= regions:
        raise ValueError('Invalid population layout.')
    budget, total = [10000], 0
    prepared, result = {}, []
    for row in rows:
        if not wanted():
            return []
        index = row['source']
        count = integer(row['count'], 'New Point Count', 0, count_limit)
        prior = row['prior']
        if not isinstance(prior, list):
            raise ValueError('Invalid Existing Points.')
        total += count + len(prior)
        if total > points:
            raise ValueError('Population exceeds the point budget.')
        if index is None and not count:
            result.append([])
            continue
        seed = row['seed']
        if type(index) is not int or not 0 <= index < len(sources) or not isinstance(seed, str) or not seed.isdigit() or len(seed) > 39:
            raise ValueError('Invalid population source or seed.')
        if index not in prepared:
            shape = materialize(geometry_from_wire(sources[index], budget=budget))
            prepared[index] = rectangle_frame(shape) if operation == 'populate_2d' else shape
        if operation == 'populate_2d':
            result.append(sample_rectangle(prepared[index], count, int(seed), tuple(xyz(p) for p in prior)))
        else:
            result.append(sample_geometry(prepared[index], count, int(seed), wanted))
    return result


def register_commands(ctx):
    from .operation_native import native_job

    req = ctx.requests()
    def run(c, operation, label, kinds):
        from serpentine3d.core import geometry as g

        source = yield req.SelectReq('Select region to populate', kinds=kinds, max_count=1)
        limit = POPULATION_COUNT_LIMITS[POPULATION_SPECS[operation]['inputs'][1].kind]
        count = integer((yield req.NumberReq('Point count', default=100)), 'Point count', 1, limit)
        seed = integer((yield req.NumberReq('Random seed', default=0)), 'Seed', -2147483648, 2147483647)
        seed = seed_for(operation, seed, (0,))
        def build(shapes):
            shape = shapes[0]
            points = (sample_rectangle(rectangle_frame(shape), count, seed) if operation == 'populate_2d'
                      else sample_geometry(shape, count, seed))
            return [g.make_point(point) for point in points]
        native_job(ctx, c, source, build, label)

    @ctx.command('populate2d', mutates=False, label='Populate 2D')
    def populate_2d(c):
        yield from run(c, 'populate_2d', 'Populate 2D', ('curve', 'surface'))

    @ctx.command('populategeometry', mutates=False, label='Populate Geometry')
    def populate_geometry(c):
        yield from run(c, 'populate_geometry', 'Populate Geometry', ('point', 'curve', 'surface', 'solid', 'compound'))
