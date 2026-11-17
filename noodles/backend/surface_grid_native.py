"""Build trimmed UV preview polylines on the existing OCC worker."""
import math

from .datatree import MAX_ITEMS
from .previews import MAX_UV_GRID_DIVISIONS, MAX_UV_GRID_VERTICES, MAX_UV_GRIDS
from .surface_uv_native import select_face, uv_bounds


def trim_curves(face):
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
    from OCP.Geom2d import Geom2d_TrimmedCurve
    from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    result = []
    # Keep edge occurrences, including both sides of a periodic seam.
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = BRepAdaptor_Curve2d(TopoDS.Edge_s(explorer.Current()), face)
        first, last = edge.FirstParameter(), edge.LastParameter()
        if first < last:
            result.append(Geom2dAdaptor_Curve(Geom2d_TrimmedCurve(edge.Curve(), first, last, True, False)))
        explorer.Next()
    return result


def clipped_intervals(curves, classify, axis, value, start, end):
    from OCP.Geom2d import Geom2d_Line, Geom2d_TrimmedCurve
    from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
    from OCP.Geom2dInt import Geom2dInt_GInter
    from OCP.gp import gp_Dir2d, gp_Pnt2d

    point = gp_Pnt2d(value, 0.) if axis == 0 else gp_Pnt2d(0., value)
    direction = gp_Dir2d(0., 1.) if axis == 0 else gp_Dir2d(1., 0.)
    iso = Geom2d_TrimmedCurve(Geom2d_Line(point, direction), start, end)
    adaptor = Geom2dAdaptor_Curve(iso)
    cuts = [start, end]
    for curve in curves:
        intersector = Geom2dInt_GInter(adaptor, curve, 1e-9, 1e-9)
        if not intersector.IsDone():
            raise ValueError('OpenCascade could not clip a UV line to the face.')
        cuts.extend(intersector.Point(i).ParamOnFirst() for i in range(1, intersector.NbPoints() + 1))
        for index in range(1, intersector.NbSegments() + 1):
            segment = intersector.Segment(index)
            if segment.HasFirstPoint():
                cuts.append(segment.FirstPoint().ParamOnFirst())
            if segment.HasLastPoint():
                cuts.append(segment.LastPoint().ParamOnFirst())
    epsilon = max((end - start) * 1e-10, 1e-12)
    previous = start
    for cut in sorted(cuts):
        current = min(end, max(start, cut))
        if current - previous <= epsilon:
            continue
        if classify(iso.Value(previous + (current - previous) / 2)):
            yield previous, current
        previous = current


def polyline(at, start, end, tolerance):
    def subdivide(a, p, b, q, depth):
        mid = a + (b-a)/2
        m = at(mid)
        if depth and math.dist(m, tuple(x + (y-x)/2 for x, y in zip(p, q))) > tolerance:
            yield from subdivide(a, p, mid, m, depth-1)
            yield from subdivide(mid, m, b, q, depth-1)
        elif math.dist(p, q) > 1e-12:
            yield q

    # Seed intervals keep a full period or symmetric inflection from being
    # mistaken for a single straight chord.
    a, p = start, at(start)
    result = [p]
    for i in range(1, 5):
        b = end if i == 4 else start + (end-start) * i / 4
        q = at(b)
        result.extend(subdivide(a, p, b, q, 5))
        a, p = b, q
    return result if len(result) >= 2 else []


def grid_lines(face, u_divisions, v_divisions, wanted, remaining):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from serpentine3d.core import geometry as g
    from .curves import xyz

    adaptor = BRepAdaptor_Surface(face, True)
    bounds = uv_bounds(face)
    curves = trim_curves(face)
    classifier = BRepTopAdaptor_FClass2d(face, 1e-9)
    tolerance = max(math.dist(*g.bbox(face)) * .0007, 1e-7)

    def classify(point):
        return classifier.Perform(point) in (TopAbs_IN, TopAbs_ON)

    output = ([], [])
    for axis, divisions in enumerate((u_divisions, v_divisions)):
        low, high = bounds[2*axis:2*axis+2]
        start, end = bounds[2*(1-axis):2*(1-axis)+2]
        for i in range(1, divisions):
            if not wanted():
                return None, remaining
            fixed = low + (high-low) * i / divisions

            def at(t):
                return xyz(g.pnt_tuple(adaptor.Value(fixed, t) if axis == 0 else adaptor.Value(t, fixed)))

            for a, b in clipped_intervals(curves, classify, axis, fixed, start, end):
                line = polyline(at, a, b, tolerance)
                if line:
                    remaining -= len(line)
                    if remaining < 0:
                        raise ValueError('Surface Preview is too dense. Reduce the divisions or number of surfaces.')
                    output[axis].append(line)
    return output, remaining


def measure(plan, wanted):
    from serpentine3d.core import geometry as g
    from .moves import geometry_from_wire
    from .scene_curves import materialize
    from .surface_uv import is_uv_geometry

    sources, rows = plan.get('sources'), plan.get('rows')
    if not isinstance(sources, list) or not isinstance(rows, list) or not 1 <= len(sources) <= len(rows) <= MAX_UV_GRIDS:
        raise ValueError('Invalid surface preview plan.')
    geometry, results, grids = {}, [], {}
    budget, remaining = [MAX_ITEMS], MAX_UV_GRID_VERTICES
    for row in rows:
        if not wanted():
            return []
        source, face, u, v = (row.get(key) for key in ('source', 'face', 'u', 'v'))
        if (type(source) is not int or not 0 <= source < len(sources)
                or any(type(n) is not int or not 1 <= n <= MAX_UV_GRID_DIVISIONS for n in (u, v))):
            raise ValueError('Invalid surface preview selection or divisions.')
        if source not in geometry:
            value = geometry_from_wire(sources[source], budget=budget)
            if not is_uv_geometry(value):
                raise ValueError('Surface Preview requires geometry with native faces.')
            geometry[source] = g.faces_of(materialize(value))
        key = (source, face, u, v)
        if key in grids:
            grid, size = grids[key]
            remaining -= size
            if remaining < 0:
                raise ValueError('Surface Preview is too dense. Reduce the divisions or number of surfaces.')
        else:
            before = remaining
            grid, remaining = grid_lines(select_face(geometry[source], face), u, v, wanted, remaining)
            if grid is None:
                return []
            grids[key] = (grid, before - remaining)
        results.append(grid)
    return results
