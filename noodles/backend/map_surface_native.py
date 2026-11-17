"""Build native OCC p-curves in the target face's UV coordinates."""
from functools import lru_cache
from itertools import product
import math

from .surface_uv_native import select_face, uv_bounds


UV_TOLERANCE = 1e-8


class FaceUV:
    def __init__(self, shape, allow_sphere):
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Sphere
        from serpentine3d.core import geometry as g

        kind = g.shape_kind(g.unwrap_compound(shape))
        faces = g.faces_of(shape)
        if kind != 'surface' and not (allow_sphere and kind == 'solid' and len(faces) == 1
                                     and BRepAdaptor_Surface(faces[0]).GetType() == GeomAbs_Sphere):
            raise ValueError('Map Surface needs a single surface face at S and T.')
        self.face = select_face(faces, 0)
        self.surface = BRep_Tool.Surface_s(self.face)
        bounds = uv_bounds(self.face)
        self.domains = bounds[:2], bounds[2:]
        geometry_type = BRepAdaptor_Surface(self.face).GetType()
        self.planar = geometry_type == GeomAbs_Plane
        self.spherical = geometry_type == GeomAbs_Sphere
        periods = (self.surface.UPeriod() if self.surface.IsUPeriodic() else 0.,
                   self.surface.VPeriod() if self.surface.IsVPeriodic() else 0.)
        self.periods = periods
        self.full = tuple(p if p and math.isclose(hi-lo, p, rel_tol=1e-7) else 0.
                          for (lo, hi), p in zip(self.domains, periods))
        self.boundaries = self._boundaries()

    def _boundaries(self):
        from OCP.BRep import BRep_Tool
        from OCP.Geom2d import Geom2d_TrimmedCurve
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.gp import gp_Vec2d

        result = []
        explorer = TopExp_Explorer(self.face, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge_s(explorer.Current())
            low, high = BRep_Tool.Range_s(edge, self.face)
            curve = BRep_Tool.CurveOnSurface_s(edge, self.face, low, high)
            if curve is not None and low < high:
                trimmed = Geom2d_TrimmedCurve(curve, low, high, True, False)
                for du, dv in product(*[(-p, 0., p) if p else (0.,) for p in self.full]):
                    result.append(trimmed.Translated(gp_Vec2d(du, dv)) if du or dv else trimmed)
            explorer.Next()
        if not result:
            raise ValueError('Map Surface could not read the face trimming boundaries.')
        return result

    def inside(self, uv):
        from OCP.BRepClass import BRepClass_FaceClassifier
        from OCP.TopAbs import TopAbs_IN, TopAbs_ON
        from OCP.gp import gp_Pnt2d

        point = tuple(lo + (value-lo) % period if period and not lo <= value <= hi else value
                      for value, (lo, hi), period in zip(uv, self.domains, self.full))
        return BRepClass_FaceClassifier(self.face, gp_Pnt2d(*point), UV_TOLERANCE).State() in (TopAbs_IN, TopAbs_ON)

    def project(self, point, previous):
        candidates = self._projected(point.X(), point.Y(), point.Z())
        if previous is None:
            return min(candidates)[1]
        unwrapped = ((distance, tuple(x + period*round((old-x)/period) if period else x
                                     for x, old, period in zip(uv, previous, self.full)))
                     for distance, uv in candidates)
        return min(unwrapped, key=lambda row: (math.dist(row[1], previous), row[0]))[1]

    @lru_cache(maxsize=8192)
    def _projected(self, x, y, z):
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        from OCP.gp import gp_Pnt

        projection = GeomAPI_ProjectPointOnSurf(gp_Pnt(x, y, z), self.surface)
        if not projection.IsDone():
            raise ValueError('Map Surface could not project the curve onto Source Surface.')
        candidates = []
        for i in range(1, projection.NbPoints()+1):
            distance = projection.Distance(i)
            if distance > 1e-5:
                continue
            u, v = projection.Parameters(i)
            axes = []
            for value, (lo, hi), period in zip((u, v), self.domains, self.periods):
                if period:
                    shift = round(((lo+hi)*.5 - value)/period)
                    options = (value+period*k for k in range(shift-1, shift+2))
                else:
                    options = (value,)
                axes.append(tuple(min(hi, max(lo, x)) for x in options
                                  if lo-UV_TOLERANCE <= x <= hi+UV_TOLERANCE))
            for uv in product(*axes):
                if self.inside(uv):
                    candidates.append((distance, uv))
        if not candidates:
            raise ValueError('A curve point is outside or off the trimmed Source Surface.')
        return tuple(candidates)

    @lru_cache(maxsize=16384)
    def contains_segment(self, a, b):
        from OCP.Geom2dAPI import Geom2dAPI_InterCurveCurve
        from OCP.Geom2d import Geom2d_TrimmedCurve

        shifts = tuple(p*math.floor(((x+y)*.5-lo)/p) if p else 0.
                       for x, y, (lo, _), p in zip(a, b, self.domains, self.full))
        a, b = tuple(x-s for x, s in zip(a, shifts)), tuple(x-s for x, s in zip(b, shifts))
        line, length = _uv_line(a, b)
        delta = b[0]-a[0], b[1]-a[1]
        cuts = [0., length]
        segment = Geom2d_TrimmedCurve(line, 0., length)
        for boundary in self.boundaries:
            intersection = Geom2dAPI_InterCurveCurve(segment, boundary, UV_TOLERANCE)
            for i in range(1, intersection.NbPoints()+1):
                p = intersection.Point(i)
                along = ((p.X()-a[0])*delta[0] + (p.Y()-a[1])*delta[1])/length
                if UV_TOLERANCE < along < length-UV_TOLERANCE:
                    cuts.append(along)
        cuts.sort()
        for t in [0., length, *((x+y)*.5 for x, y in zip(cuts, cuts[1:]))]:
            p = line.Value(t)
            if not self.inside((p.X(), p.Y())):
                return False
        return True

    def check_segment(self, a, b, label):
        if not self.contains_segment(a, b):
            raise ValueError(f'Mapped curve crosses outside the trimmed {label} Surface.')

    def pole(self, v):
        return self.spherical and abs(abs(v)-math.pi/2) <= UV_TOLERANCE

    def canonical(self, uv):
        u, v = (lo+(x-lo)%p if p and not lo <= x < hi-1e-12 else x
                for x,(lo,hi),p in zip(uv,self.domains,self.full))
        if self.full[0] and abs(u-self.domains[0][1]) <= 1e-12:
            u = self.domains[0][0]
        if self.pole(v):
            u, v = self.domains[0][0], math.copysign(math.pi/2,v)
        return u, v

    @lru_cache(maxsize=8192)
    def vertex(self, uv):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex

        return BRepBuilderAPI_MakeVertex(self.surface.Value(*uv)).Vertex()

    @lru_cache(maxsize=8192)
    def segment(self, a, b):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.BRepLib import BRepLib

        self.check_segment(a,b,'Target')
        if self.pole(a[1]) and abs(a[1]-b[1]) <= UV_TOLERANCE:
            return None
        line, length = _uv_line(a,b)
        builder = BRepBuilderAPI_MakeEdge(line,self.surface,self.vertex(self.canonical(a)),
                                          self.vertex(self.canonical(b)),0.,length)
        if not builder.IsDone():
            raise ValueError('OpenCascade could not construct a mapped p-curve.')
        edge = builder.Edge()
        if not BRepLib.BuildCurves3d_s(edge,1e-8):
            raise ValueError('OpenCascade could not reconstruct a mapped 3D curve.')
        return edge


def _uv_line(a, b):
    from OCP.Geom2d import Geom2d_Line
    from OCP.gp import gp_Ax2d, gp_Dir2d, gp_Pnt2d

    du, dv = b[0]-a[0], b[1]-a[1]
    return Geom2d_Line(gp_Ax2d(gp_Pnt2d(*a), gp_Dir2d(du, dv))), math.hypot(du, dv)


@lru_cache(maxsize=24)
def _face(shape, allow_sphere=False):
    return FaceUV(shape, allow_sphere)


def _remap(uv, source, target):
    return tuple(lo+(value-a)/(b-a)*(hi-lo)
                 for value,(a,b),(lo,hi) in zip(uv,source.domains,target.domains))


def map_polygon(points, source_shape, target_shape):
    from OCP.BRep import BRep_Builder
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Wire
    from OCP.gp import gp_Pnt
    from serpentine3d.core import geometry as g

    source, target = _face(source_shape), _face(target_shape, allow_sphere=True)
    if not source.planar:
        return map_shape(g.make_polyline(points,closed=True),source_shape,target_shape)
    uv = tuple(source.project(gp_Pnt(*point),None) for point in points)
    wire = TopoDS_Wire()
    builder = BRep_Builder()
    builder.MakeWire(wire)
    count = 0
    for a,b in zip(uv,(*uv[1:],uv[0])):
        source.check_segment(*sorted((a,b)), 'Source')
        a,b = _remap(a,source,target), _remap(b,source,target)
        lo,hi = (a,b) if a<b else (b,a)
        edge = target.segment(lo,hi)
        if edge is not None:
            builder.Add(wire,edge if a==lo else edge.Reversed())
            count += 1
    wire.Closed(True)
    if count < 2 or not BRepCheck_Analyzer(wire).IsValid():
        raise ValueError('OpenCascade returned an invalid mapped contour.')
    return wire


def map_shape(curve, source, target):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepLib import BRepLib
    from OCP.GeomAbs import GeomAbs_Line
    from serpentine3d.core import geometry as g

    source_shape, target_shape = source,target
    source, target = _face(source), _face(target, allow_sphere=True)
    curve = g.unwrap_compound(curve)
    edges = g.edges_of(curve)
    if g.shape_kind(curve) != 'curve' or not 1 <= len(edges) <= 1000:
        raise ValueError('Map Surface requires a curve with 1–1000 edges.')
    if (source.planar and len(edges) >= 3 and g.is_closed_curve(curve)
            and all(BRepAdaptor_Curve(e).GetType() == GeomAbs_Line for e in edges)):
        points, closed = g._wire_points(curve)
        if closed:
            return map_polygon(tuple(points),source_shape,target_shape)

    mapped = []
    for edge in edges:
        adaptor = BRepAdaptor_Curve(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        if not math.isfinite(first) or not math.isfinite(last) or not first < last:
            raise ValueError('Map Surface needs finite curve parameters.')
        steps = 1 if source.planar and adaptor.GetType() == GeomAbs_Line else 32
        previous = None
        for i in range(steps+1):
            uv = source.project(adaptor.Value(first + (last-first)*i/steps), previous)
            if previous is not None and math.dist(previous, uv) > 1e-10:
                source.check_segment(previous, uv, 'Source')
                a, b = _remap(previous,source,target), _remap(uv,source,target)
                if math.dist(a, b) > 1e-10:
                    target.check_segment(a, b, 'Target')
                    if target.pole(a[1]) and abs(a[1]-b[1]) <= UV_TOLERANCE:
                        previous = uv
                        continue  # The full pole edge is one native point.
                    line, length = _uv_line(a, b)
                    builder = BRepBuilderAPI_MakeEdge(line, target.surface, 0., length)
                    if not builder.IsDone():
                        raise ValueError('OpenCascade could not construct a mapped p-curve.')
                    mapped.append(builder.Edge())
                    if len(mapped) > 6000:
                        raise ValueError('Map Surface exceeds 6000 mapped segments.')
            previous = uv
    if not mapped:
        raise ValueError('Map Surface produced no nondegenerate edges.')
    for edge in mapped:
        if not BRepLib.BuildCurves3d_s(edge, 1e-8):
            raise ValueError('OpenCascade could not reconstruct a mapped 3D curve.')
    result = g.join_curves(mapped)
    if not BRepCheck_Analyzer(result).IsValid():
        raise ValueError('OpenCascade returned an invalid mapped curve.')
    return result


def register_commands(ctx):
    from .operation_native import native_job

    req = ctx.requests()

    @ctx.command('mapsurface', mutates=False, label='Map Surface')
    def map_surface(c):
        curves = yield req.SelectReq('Select curves to map', kinds=('curve',), max_count=1500)
        source = yield req.SelectReq('Select source surface', kinds=('surface',), max_count=1)
        target = yield req.SelectReq('Select target surface or sphere', kinds=('surface','solid'), max_count=1)
        native_job(ctx, c, [*curves, *source, *target],
                   lambda shapes: [map_shape(shape, *shapes[-2:]) for shape in shapes[:-2]], 'Map Surface')
