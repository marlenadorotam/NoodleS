"""OCC factories for eight-corner surface cages and their mapped modules."""
import math
from functools import lru_cache
from itertools import product

from .curves import add, cross, dot, scale, sub
from .morph import cage_corners


# Base and top use the same winding: 00, 10, 11, 01.
BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7))


def _mix(a, b, t):
    return add(a, scale(sub(b, a), t))


def _quad(a, b, c, d, u, v):
    return _mix(_mix(a, b, u), _mix(d, c, u), v)


def _map_box(corners, u, v, w):
    return _mix(_quad(*corners[:4], u, v), _quad(*corners[4:], u, v), w)


def _regular(corners):
    a, b, c, d, e, f, g, h = corners
    if any(math.dist(corners[i], corners[j]) <= 1e-7 for i, j in BOX_EDGES):
        return False
    sign = None
    for u, v, w in product((0., .5, 1.), repeat=3):
        du = _mix(_mix(sub(b, a), sub(c, d), v), _mix(sub(f, e), sub(g, h), v), w)
        dv = _mix(_mix(sub(d, a), sub(c, b), u), _mix(sub(h, e), sub(g, f), u), w)
        dw = _quad(sub(e, a), sub(f, b), sub(g, c), sub(h, d), u, v)
        det = dot(cross(du, dv), dw)
        if abs(det) <= 1e-9 * math.prod(math.hypot(*axis) for axis in (du, dv, dw)):
            return False
        if sign is None:
            sign = det > 0
        elif sign != (det > 0):
            return False
    return True


def build_surface_boxes(shape, index, u_count, v_count, height, wanted=lambda: True):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.gp import gp_Pnt, gp_Vec
    from serpentine3d.core import geometry as g
    from .domain import DomainValue
    from .isotrim_native import isotrim_face
    from .morph_native import _target
    from .surface_uv import Domain2Value, uv_cells
    from .surface_uv_native import select_face, uv_bounds

    if not math.isfinite(height) or abs(height) <= 1e-7:
        raise ValueError('Surface Box requires a finite nonzero height.')
    face = select_face(g.faces_of(shape), index)
    bounds = uv_bounds(face)
    domain = Domain2Value(DomainValue(*bounds[:2]), DomainValue(*bounds[2:]))
    adaptor = BRepAdaptor_Surface(face)
    sign = -1 if face.Orientation() == TopAbs_REVERSED else 1
    try:
        _target(face, (None, None, None))
        rectangular = True
    except ValueError:
        rectangular = False
    surface = BRep_Tool.Surface_s(face) if not rectangular else None

    @lru_cache(maxsize=None)
    def corner(u, v):
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        adaptor.D1(u, v, p, du, dv)
        normal = du.Crossed(dv)
        if normal.Magnitude() <= 1e-12:
            return None
        normal.Normalize()
        return g.pnt_tuple(p), g.pnt_tuple(p.Translated(normal.Multiplied(sign * height)))

    for i, j, cell in uv_cells(domain, u_count, v_count):
        if not wanted():
            return
        a, b, c, d = cell.u.start, cell.u.end, cell.v.start, cell.v.end
        # Canonicalize the wrap endpoints only for a complete period.
        end_u = (bounds[0] if b == bounds[1] and adaptor.IsUPeriodic()
                 and math.isclose(b - bounds[0], adaptor.UPeriod(), abs_tol=1e-9) else b)
        end_v = (bounds[2] if d == bounds[3] and adaptor.IsVPeriodic()
                 and math.isclose(d - bounds[2], adaptor.VPeriod(), abs_tol=1e-9) else d)
        pairs = (corner(a, c), corner(end_u, c), corner(end_u, end_v), corner(a, end_v))
        if None in pairs:
            continue
        base, top = zip(*pairs)
        corners = base + top
        if not _regular(corners):
            continue
        if not rectangular:
            trim = a, b, c, d
            clipped = isotrim_face(face, trim, bounds, allow_empty=True)
            if clipped is None:
                continue
            full = BRepBuilderAPI_MakeFace(surface, *trim, 1e-7)
            if not full.IsDone():
                raise ValueError('OpenCascade could not build the Surface Box UV rectangle.')
            if not math.isclose(g.surface_area(full.Face()), g.surface_area(clipped), rel_tol=1e-7, abs_tol=1e-12):
                continue
        yield i, j, corners


def cage_shape(corners):
    from serpentine3d.core import geometry as g

    return g.make_compound([g.make_line(corners[i], corners[j]) for i, j in BOX_EDGES])


def _mapped_edge(edge, mapped_point):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.TColStd import TColStd_HArray1OfReal
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    curve = BRepAdaptor_Curve(edge)
    first, last = curve.FirstParameter(), curve.LastParameter()
    def at(t):
        return mapped_point(g.pnt_tuple(curve.Value(first + (last - first) * t)))

    start, end = at(0.), at(1.)
    periodic = start.Distance(end) <= 1e-8
    tolerance = 2e-6
    for steps in (8, 16, 32, 64, 128, 256, 512):
        size = steps if periodic else steps + 1
        points = TColgp_HArray1OfPnt(1, size)
        params = TColStd_HArray1OfReal(1, steps + 1)
        for i in range(steps + 1):
            params.SetValue(i + 1, i / steps)
            if i < size:
                points.SetValue(i + 1, at(i / steps))
        fit = GeomAPI_Interpolate(points, params, periodic, 1e-9)
        fit.Perform()
        if fit.IsDone() and all(fit.Curve().Value((i + t) / steps).Distance(at((i + t) / steps)) <= tolerance
                                for i in range(steps) for t in (.25, .5, .75)):
            result = BRepBuilderAPI_MakeEdge(fit.Curve(), 0., 1.)
            if result.IsDone():
                return TopoDS.Edge_s(result.Edge().Oriented(edge.Orientation()))
    raise ValueError('Box Morph could not fit a curve within 0.000002 model units.')


def _cubic_poles(points):
    """Convert samples at 0, 1/3, 2/3, 1 to Bernstein control points."""
    start, first, second, end = points
    a = sub(scale(sub(first, start), 27), sub(end, start))
    b = sub(scale(sub(second, start), 27), scale(sub(end, start), 8))
    return start, add(start, scale(sub(scale(a, 2), b), 1/18)), add(
        start, scale(sub(scale(b, 2), a), 1/18)), end


def _mapped_face(face, mapped_point):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.Geom import Geom_BezierSurface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    from serpentine3d.core import geometry as g
    from .morph_native import _cap, _mapped_wire, _wires
    from .operation_native import checked
    from .surface_uv_native import uv_bounds

    profile, outlines = _wires(face)
    adaptor = BRepAdaptor_Surface(profile)
    if adaptor.GetType() != GeomAbs_Plane:
        raise ValueError('Box Morph needs planar source faces for a non-affine target box.')
    u0, u1, v0, v1 = uv_bounds(profile)
    du, dv = u1-u0, v1-v0
    # On a plane the trilinear map is a polynomial of degree at most three
    # in each surface parameter. Transfer the original trims to that support.
    rows = [_cubic_poles(tuple(g.pnt_tuple(mapped_point(g.pnt_tuple(
        adaptor.Value(u0+du*i/3, v0+dv*j/3)))) for i in range(4))) for j in range(4)]
    poles = TColgp_Array2OfPnt(1, 4, 1, 4)
    for i, column in enumerate(zip(*rows), 1):
        for j, point in enumerate(_cubic_poles(column), 1):
            poles.SetValue(i, j, gp_Pnt(*point))
    support = Geom_BezierSurface(poles)

    def uv(u, v):
        return (u-u0)/du, (v-v0)/dv

    rings = tuple(_mapped_wire(wire, profile, adaptor.Plane(), support, uv) for wire in outlines)
    return TopoDS.Face_s(checked(_cap(support, rings, False)).Oriented(face.Orientation()))


def box_morph_shape(shape, box, frame, corners):
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepLib import BRepLib
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_EDGE, TopAbs_SHELL
    from OCP.TopoDS import TopoDS, TopoDS_Iterator
    from OCP.gp import gp_GTrsf, gp_Mat, gp_Pnt, gp_XYZ
    from serpentine3d.core import geometry as g
    from .morph_native import _bounds, _world
    from .operation_native import checked

    corners = cage_corners(corners)
    if not _regular(corners):
        raise ValueError('Box Morph target is collapsed or folded.')
    low, high = _bounds((box,), frame)
    widths = tuple(b-a for a, b in zip(low, high))
    if min(widths[:2]) <= 1e-7:
        raise ValueError('Box Morph Reference Box needs nonzero X and Y dimensions.')
    a, b = _bounds((shape,), frame)
    if any(x < lo-1e-6 or y > hi+1e-6 for x, y, lo, hi in zip(a, b, low, high)):
        raise ValueError('Module geometry lies outside the Reference Box.')
    axes = frame.axis_x, frame.axis_y, frame.normal
    origin = _world(frame, low)
    if widths[2] <= 1e-7:
        # A flat reference maps its XY profile onto the base.
        widths = (*widths[:2], 1.)
    deltas = tuple(sub(corners[i], corners[0]) for i in (1, 3, 4))
    affine = all(math.dist(corner, add(corners[0], add(scale(deltas[0], u),
                 add(scale(deltas[1], v), scale(deltas[2], w))))) <= 1e-9
                 for corner, (u, v, w) in zip(corners, (
                     (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                     (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))))
    if affine and g.shape_kind(shape) != 'point':
        matrix = tuple(tuple(sum(delta[i] * axis[j] / width for delta, axis, width in
                                 zip(deltas, axes, widths)) for j in range(3)) for i in range(3))
        transform = gp_GTrsf()
        transform.SetVectorialPart(gp_Mat(*(value for row in matrix for value in row)))
        transform.SetTranslationPart(gp_XYZ(*sub(corners[0], tuple(dot(row, origin) for row in matrix))))
        result = g._gtransform(g.copy_shape(shape), transform)
        if result.IsNull() or not BRepCheck_Analyzer(result).IsValid():
            raise ValueError('OpenCascade returned invalid Box Morph geometry.')
        return result

    def mapped_point(point):
        local = sub(point, origin)
        return gp_Pnt(*_map_box(corners, *(dot(local, axis) / width for axis, width in zip(axes, widths))))

    def build(part):
        if part.ShapeType() == TopAbs_COMPOUND:
            iterator, items = TopoDS_Iterator(part), []
            while iterator.More():
                items.append(build(iterator.Value()))
                iterator.Next()
            return g.make_compound(items)
        kind = g.shape_kind(part)
        if kind == 'point':
            return g.make_point(g.pnt_tuple(mapped_point(g.point_coords(part))))
        if kind == 'curve':
            if part.ShapeType() == TopAbs_EDGE:
                result = _mapped_edge(TopoDS.Edge_s(part), mapped_point)
                if not BRepCheck_Analyzer(result).IsValid():
                    raise ValueError('Box Morph produced an invalid curve.')
                return result
            wire = BRepBuilderAPI_MakeWire()
            original = TopoDS.Wire_s(g.to_wire(part))
            edges = BRepTools_WireExplorer(original)
            while edges.More():
                wire.Add(_mapped_edge(edges.Current(), mapped_point))
                if not wire.IsDone():
                    raise ValueError('Box Morph could not join the mapped curve.')
                edges.Next()
            if not wire.IsDone() or not BRepCheck_Analyzer(wire.Wire()).IsValid() or (
                    BRep_Tool.IsClosed_s(original) and not BRep_Tool.IsClosed_s(wire.Wire())):
                raise ValueError('Box Morph could not join the mapped curve.')
            return wire.Wire()
        if kind not in ('surface', 'solid'):
            raise ValueError('Box Morph requires native points, curves, surfaces or solids.')
        faces = [_mapped_face(face, mapped_point) for face in g.faces_of(part)]
        if len(faces) == 1 and kind == 'surface':
            return faces[0]
        sewing = BRepBuilderAPI_Sewing(1e-5)
        for face in faces:
            sewing.Add(face)
        sewing.Perform()
        result = sewing.SewedShape()
        if kind == 'solid':
            if result.IsNull() or result.ShapeType() != TopAbs_SHELL or sewing.NbFreeEdges():
                raise ValueError('Box Morph could not sew a closed solid.')
            result = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(result)).Solid()
            if not BRepLib.OrientClosedSolid_s(result):
                raise ValueError('Box Morph could not orient the closed solid.')
        elif part.ShapeType() == TopAbs_SHELL and result.ShapeType() != TopAbs_SHELL:
            raise ValueError('Box Morph could not sew the mapped shell.')
        return checked(result)

    return build(shape)


def register_commands(ctx):
    from .curves import PlaneValue
    from .morph_native import box_shape
    from .operation_native import native_job
    from .splines import integer
    from .surface_structure import MAX_PANELS, panel_count

    req = ctx.requests()

    @ctx.command('surfacebox', mutates=False, label='Surface Box')
    def surface_box(command):
        sources = yield req.SelectReq('Select geometry containing the target face',
                                      kinds=('surface', 'solid', 'compound'), min_count=1, max_count=1)
        index = integer((yield req.NumberReq('Face index (0 = Auto)', default=0)), 'Face Index', 0, 10000)
        u = integer((yield req.NumberReq('U Count', default=4, minimum=1)), 'U Count', 1, MAX_PANELS)
        v = integer((yield req.NumberReq('V Count', default=4, minimum=1)), 'V Count', 1, MAX_PANELS)
        height = yield req.NumberReq('Normal Height', default=1.)
        panel_count(u, v, label='Surface Box')

        def build(shapes):
            cages = [cage_shape(corners) for _, _, corners in build_surface_boxes(shapes[0], index, u, v, height)]
            if not cages:
                raise ValueError('No complete, regular Surface Box cells fit this face.')
            return cages

        native_job(ctx, command, sources, build, 'Surface Box')

    @ctx.command('boxmorph', mutates=False, label='Box Morph')
    def box_morph(command):
        sources = yield req.SelectReq('Select the module geometry', kinds=('point', 'curve', 'surface', 'solid', 'compound'),
                                      min_count=1, max_count=240)
        corners = []
        for layer in ('Base', 'Top'):
            for corner in ('00', '10', '11', '01'):
                point = yield req.PointReq(f'{layer} corner {corner} (click or type X,Y,Z)')
                corners.append(tuple(map(float, point)))
        plane = command.cplane
        frame = PlaneValue(tuple(map(float, plane.origin)), tuple(map(float, plane.xdir)),
                           tuple(map(float, plane.normal)))

        def build(shapes):
            box = box_shape(shapes, frame)
            return [box_morph_shape(shape, box, frame, corners) for shape in shapes]

        native_job(ctx, command, sources, build, 'Box Morph')
