"""Per-face OCC UV bounds and samples without scene reads or writes."""
import math

from .arithmetic import finite_number
from .curves import cross, scale, xyz
from .datatree import MAX_ITEMS
from .surface_uv import MAX_UV_MEASUREMENTS, MAX_UV_SAMPLES, is_uv_geometry


def select_face(faces, index):
    if type(index) is not int or not 0 <= index <= MAX_ITEMS:
        raise ValueError('Invalid Face Index.')
    count = len(faces)
    if not count:
        raise ValueError('The geometry has no native faces.')
    if index == 0:
        if count != 1:
            raise ValueError(f'This object has {count} faces. Set Face Index to 1..{count}.')
        return faces[0]
    if index > count:
        raise ValueError(f'Face Index must be 1..{count} for this object.')
    return faces[index - 1]


def uv_bounds(face):
    from OCP.BRepTools import BRepTools
    from OCP.Precision import Precision

    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    if (not all(math.isfinite(v) and not Precision.IsInfinite_s(v) for v in (u0, u1, v0, v1))
            or not (u0 < u1 and v0 < v1)):
        raise ValueError('The selected face has no finite, nondegenerate UV bounds.')
    return u0, u1, v0, v1


def _parameter(value, native, exposed, axis):
    low, high = exposed
    span = high - low
    if not 0 < span < math.inf:
        raise ValueError(f'{axis} requires a finite increasing domain.')
    number = low + span / 2 if value is None else finite_number(value)
    tolerance = max(span*1e-12, 4*math.ulp(low), 4*math.ulp(high))
    if not low - tolerance <= number <= high + tolerance:
        raise ValueError(f'{axis} is outside the selected UV domain [{low:.8g}, {high:.8g}].')
    number = min(high, max(low, number))
    if native == exposed:
        return number, number
    start, end = native
    mapped = end if number == high else start + (end - start)*((number - low)/span)
    return mapped, number


def _exposed_bounds(bounds, row):
    normalized = row.get('normalized')
    if type(normalized) is not bool:
        raise ValueError('Normalized must be Boolean.')
    if normalized:
        return (0., 1., 0., 1.)
    if 'domain' in row:
        raw = row['domain']
        if not isinstance(raw, list) or len(raw) != 4:
            raise ValueError('Invalid surface UV view.')
        exposed = tuple(map(finite_number, raw))
        if not all(0 < high - low < math.inf for low, high in zip(exposed[::2], exposed[1::2])):
            raise ValueError('UV view requires finite increasing intervals.')
        return exposed
    return bounds


def evaluate_sample(face, adaptor, bounds, row):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT, TopAbs_REVERSED
    from OCP.gp import gp_Pnt, gp_Pnt2d, gp_Vec
    from serpentine3d.core import geometry as g

    exposed = _exposed_bounds(bounds, row)

    u, shown_u = _parameter(row.get('u'), bounds[:2], exposed[:2], 'U')
    v, shown_v = _parameter(row.get('v'), bounds[2:], exposed[2:], 'V')
    classification = BRepClass_FaceClassifier()
    classification.Perform(face, gp_Pnt2d(u, v), g.tol())
    state = classification.State()
    if state == TopAbs_OUT:
        return None
    if state not in (TopAbs_IN, TopAbs_ON):
        raise ValueError('OpenCascade could not classify the UV point on the trimmed face.')

    point, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    adaptor.D1(u, v, point, du, dv)
    p, a, b = (g.pnt_tuple(value) for value in (point, du, dv))
    if not all(math.isfinite(x) for vector in (p, a, b) for x in vector):
        raise ValueError('OpenCascade produced nonfinite surface derivatives.')
    a_len, b_len = math.hypot(*a), math.hypot(*b)
    if min(a_len, b_len) <= 1e-12:
        return None  # A singular sample cannot provide a tangent frame.
    normal = cross(scale(a, 1/a_len), scale(b, 1/b_len))
    normal_len = math.hypot(*normal)
    if normal_len <= 1e-10:
        return None
    orientation = -1 if face.Orientation() == TopAbs_REVERSED else 1
    normal = scale(normal, orientation / normal_len)
    if not row['normalized'] and 'domain' in row:
        a = scale(a, (bounds[1] - bounds[0])/(exposed[1] - exposed[0]))
        b = scale(b, (bounds[3] - bounds[2])/(exposed[3] - exposed[2]))
        if not all(math.isfinite(x) for x in (*a, *b)) or not min(math.hypot(*a), math.hypot(*b)) > 0:
            raise ValueError('UV view scaling produces invalid surface derivatives.')
    return (*p, *normal, *a, *b, shown_u, shown_v)


def _face_solution(face, search, index):
    from OCP.BRep import BRep_Tool
    from OCP.BRepExtrema import BRepExtrema_IsInFace, BRepExtrema_IsOnEdge
    from OCP.TopoDS import TopoDS

    kind = search.SupportTypeShape2(index)
    if kind == BRepExtrema_IsInFace:
        return search.ParOnFaceS2(index)
    support = search.SupportOnShape2(index)
    if kind == BRepExtrema_IsOnEdge:
        edge = TopoDS.Edge_s(support)
        low, high = BRep_Tool.Range_s(edge, face)
        curve = BRep_Tool.CurveOnSurface_s(edge, face, low, high)
        if curve is None:
            return None
        parameter, = search.ParOnEdgeS2(index)
        return curve.Value(parameter).Coord()
    return BRep_Tool.Parameters_s(TopoDS.Vertex_s(support), face).Coord()


def _on_face_parameters(face, adaptor, bounds, uv, point, tolerance):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt2d
    from serpentine3d.core import geometry as g

    if uv is None or not all(math.isfinite(x) for x in uv):
        return None
    periods = (adaptor.UPeriod() if adaptor.IsUPeriodic() else 0.,
               adaptor.VPeriod() if adaptor.IsVPeriodic() else 0.)
    parameters = []
    for value, low, high, period in zip(uv, bounds[::2], bounds[1::2], periods):
        epsilon = max((high - low) * 1e-12, 4 * math.ulp(low), 4 * math.ulp(high))
        if period and not low - epsilon <= value <= high + epsilon:
            value = low + (value - low) % period
        if not low - epsilon <= value <= high + epsilon:
            return None
        parameters.append(min(high, max(low, value)))
    classifier = BRepClass_FaceClassifier(face, gp_Pnt2d(*parameters), g.tol())
    if classifier.State() in (TopAbs_IN, TopAbs_ON) and adaptor.Value(*parameters).Distance(point) <= tolerance:
        return tuple(parameters)
    return None


def closest_sample(face, adaptor, bounds, search, row):
    from OCP.BRep import BRep_Tool
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from serpentine3d.core import geometry as g

    exposed = _exposed_bounds(bounds, row)
    query = xyz(row.get('point'))
    search.LoadS1(g.make_point(query))
    if not search.Perform() or not search.NbSolution():
        raise ValueError('OpenCascade could not find a closest point on the trimmed face.')
    tolerance = max(g.tol(), BRep_Tool.Tolerance_s(face)) * 4
    best = None
    for index in range(1, search.NbSolution() + 1):
        point = search.PointOnShape2(index)
        uv = _on_face_parameters(face, adaptor, bounds, _face_solution(face, search, index), point, tolerance)
        if uv is None:
            # Recover UV when a boundary edge's 3D and 2D parameterizations differ.
            projection = GeomAPI_ProjectPointOnSurf(point, BRep_Tool.Surface_s(face))
            for candidate in range(1, projection.NbPoints() + 1):
                uv = _on_face_parameters(face, adaptor, bounds, projection.Parameters(candidate), point, tolerance)
                if uv is not None:
                    break
        if uv is None:
            continue
        position = adaptor.Value(*uv).Coord()
        candidate = math.dist(query, position), uv, position
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError('OpenCascade could not recover UV on the trimmed face.')
    distance, uv, point = best
    u, _ = _parameter(uv[0], exposed[:2], bounds[:2], 'U')
    v, _ = _parameter(uv[1], exposed[2:], bounds[2:], 'V')
    return (*point, u, v, distance)


def measure(plan, wanted, *, closest=False):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from serpentine3d.core import geometry as g
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    sources, rows = plan.get('sources'), plan.get('rows')
    evaluate = plan.get('evaluate', False)
    limit = MAX_UV_SAMPLES if evaluate or closest else MAX_UV_MEASUREMENTS
    if (type(evaluate) is not bool or not isinstance(sources, list) or not isinstance(rows, list)
            or (evaluate and closest) or not 1 <= len(sources) <= len(rows) <= limit):
        raise ValueError('Invalid surface UV measurement batch.')
    geometry, selections, results = {}, {}, []
    budget = [MAX_ITEMS]
    for row in rows:
        if not wanted():
            return []
        source, index = row.get('source'), row.get('face')
        if type(source) is not int or not 0 <= source < len(sources):
            raise ValueError('Invalid surface UV source index.')
        if source not in geometry:
            value = geometry_from_wire(sources[source], budget=budget)
            if not is_uv_geometry(value):
                raise ValueError('Surface UV requires geometry with native faces.')
            geometry[source] = g.faces_of(materialize(value))
        if type(index) is not int:
            raise ValueError('Invalid Face Index.')
        key = source, index
        if key not in selections:
            face = select_face(geometry[source], index)
            adaptor = BRepAdaptor_Surface(face, True) if evaluate or closest else None
            search = BRepExtrema_DistShapeShape() if closest else None
            if search is not None:
                search.LoadS2(face)
            selections[key] = face, adaptor, uv_bounds(face), search
        face, adaptor, bounds, search = selections[key]
        if closest:
            results.append(closest_sample(face, adaptor, bounds, search, row))
        else:
            results.append(evaluate_sample(face, adaptor, bounds, row) if evaluate else bounds)
    return results
