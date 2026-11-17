"""Native oriented bounds and UVW embossing of planar profiles and straight prisms."""
import math
from functools import lru_cache

from .curves import add, dot, scale, sub


def _axes(frame):
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt

    return gp_Ax3(gp_Pnt(*frame.origin), gp_Dir(*frame.normal), gp_Dir(*frame.axis_x))


def _bounds(shapes, frame):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopLoc import TopLoc_Location
    from OCP.gp import gp_Trsf

    transform = gp_Trsf()
    transform.SetTransformation(_axes(frame))
    location = TopLoc_Location(transform)
    box = Bnd_Box()
    for shape in shapes:
        BRepBndLib.AddOptimal_s(shape.Moved(location), box, False, False)
    if box.IsVoid() or box.IsOpen():
        raise ValueError('Bounding Box requires finite geometry.')
    x0, y0, z0, x1, y1, z1 = box.Get()
    return (x0, y0, z0), (x1, y1, z1)


def _world(frame, point):
    return add(frame.at(*point[:2]), scale(frame.normal, point[2]))


def box_shape(shapes, frame):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from serpentine3d.core import geometry as g

    low, high = _bounds(shapes, frame)
    widths = tuple(b-a for a,b in zip(low, high))
    active = [axis for axis, width in enumerate(widths) if width > 1e-7]
    origin = _world(frame, low)
    if len(active) == 3:
        axes = gp_Ax2(gp_Pnt(*origin), gp_Dir(*frame.normal), gp_Dir(*frame.axis_x))
        return BRepPrimAPI_MakeBox(axes, *widths).Shape()
    if not active:
        return g.make_point(origin)
    def corner(*axes):
        return _world(frame, tuple(high[i] if i in axes else low[i] for i in range(3)))
    if len(active) == 1:
        return g.make_line(origin, corner(*active))
    a, b = active
    return g.planar_face(g.make_polyline([origin, corner(a), corner(a, b), corner(b)], closed=True))


def _target(face, domains):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve2d
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_REVERSED, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from serpentine3d.core import geometry as g
    from .surface_uv_native import uv_bounds

    u0, u1, v0, v1 = uv_bounds(face)
    wires = TopExp_Explorer(face, TopAbs_WIRE)
    if not wires.More():
        raise ValueError('Surface Morph needs a bounded target face.')
    wires.Next()
    if wires.More():
        raise ValueError('Surface Morph needs a target without trim holes.')
    bounds = ((u0, u1), (v0, v1))
    for edge in g.edges_of(face):
        curve = BRepAdaptor_Curve2d(edge, face)
        a, b = curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())
        if curve.GetType() != GeomAbs_Line or not any(
                abs(x-y) <= 1e-7 and min(abs(x-limit) for limit in span) <= 1e-7
                for x,y,span in zip((a.X(), a.Y()), (b.X(), b.Y()), bounds)):
            raise ValueError('Surface Morph needs a rectangular UV region on the target.')
    result = tuple(domain if domain is not None else bound
                   for domain, bound in zip(domains, bounds))
    for interval, (lo, hi) in zip(result, bounds):
        if min(interval) < lo-1e-8 or max(interval) > hi+1e-8:
            raise ValueError('The requested U or V interval lies outside the target face.')
    return BRep_Tool.Surface_s(face), result, -1 if face.Orientation() == TopAbs_REVERSED else 1


def _mapped_wire(wire, profile_face, plane, surface, uv):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomAPI import GeomAPI
    from OCP.Geom2dConvert import Geom2dConvert
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt2d

    builder = BRepBuilderAPI_MakeWire()
    edges = (BRepTools_WireExplorer(wire, profile_face) if profile_face is not None
             else BRepTools_WireExplorer(wire))
    while edges.More():
        edge = edges.Current()
        adaptor = BRepAdaptor_Curve(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        curve = BRep_Tool.Curve_s(edge, first, last)
        planar = GeomAPI.To2d_s(Geom_TrimmedCurve(curve, first, last), plane)
        spline = Geom2dConvert.CurveToBSplineCurve_s(planar)
        for i in range(1, spline.NbPoles()+1):
            p = spline.Pole(i)
            spline.SetPole(i, gp_Pnt2d(*uv(p.X(), p.Y())))
        result = BRepBuilderAPI_MakeEdge(spline, surface)
        if not result.IsDone() or not BRepLib.BuildCurves3d_s(result.Edge(), 1e-7):
            raise ValueError('OpenCascade could not build the morphed edge.')
        mapped = result.Edge()
        builder.Add(TopoDS.Edge_s(mapped.Reversed()) if edge.Orientation() == TopAbs_REVERSED else mapped)
        edges.Next()
    if not builder.IsDone():
        raise ValueError('OpenCascade could not join the morphed outline.')
    return builder.Wire()


def _wires(face):
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_FORWARD, TopAbs_WIRE
    from OCP.TopoDS import TopoDS, TopoDS_Iterator

    face = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
    outer = BRepTools.OuterWire_s(face)
    others = []
    iterator = TopoDS_Iterator(face)
    while iterator.More():
        child = iterator.Value()
        if child.ShapeType() == TopAbs_WIRE and not child.IsSame(outer):
            others.append(TopoDS.Wire_s(child))
        iterator.Next()
    return face, (outer, *others)


def _cap(surface, wires, reverse):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepLib import BRepLib
    from OCP.TopoDS import TopoDS

    if reverse:
        wires = tuple(TopoDS.Wire_s(wire.Reversed()) for wire in wires)
    face = BRepBuilderAPI_MakeFace(surface, wires[0], True)
    for hole in wires[1:]:
        face.Add(hole)
    if not face.IsDone():
        raise ValueError('OpenCascade could not trim the morphed surface.')
    result = face.Face()
    BRepLib.SameParameter_s(result, 1e-7, True)
    return result


def _reverse_cap(face, frame, uv_reversed):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.gp import gp_Pnt, gp_Vec
    from .surface_uv_native import uv_bounds

    u0, u1, v0, v1 = uv_bounds(face)
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    BRepAdaptor_Surface(face).D1((u0+u1)/2, (v0+v1)/2, p, du, dv)
    alignment = du.Crossed(dv).Dot(gp_Vec(*frame.normal))
    if abs(alignment) <= 1e-12:
        raise ValueError('The planar profile has a singular parametrization.')
    return (alignment < 0) != uv_reversed


def _prism_profile(shape, frame, low, high):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.gp import gp_Vec
    from serpentine3d.core import geometry as g

    for face in g.faces_of(shape):
        if BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane:
            continue
        a, b = _bounds((face,), frame)
        if max(abs(a[2]-low), abs(b[2]-low)) > 1e-6:
            continue
        prism = BRepPrimAPI_MakePrism(face, gp_Vec(*scale(frame.normal, high-low))).Shape()
        expected = abs(g.volume(shape))
        if expected <= 1e-12 or not math.isclose(abs(g.volume(prism)), expected, rel_tol=1e-6):
            continue
        common = BRepAlgoAPI_Common(prism, shape)
        if common.IsDone() and math.isclose(abs(g.volume(common.Shape())), expected, rel_tol=1e-6):
            return face
    raise ValueError('Surface Morph solids must be straight extrusions along the reference box Z axis.')


def _solid(caps, sections):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    from .operation_native import checked

    sewing = BRepBuilderAPI_Sewing(1e-5)
    for cap in caps:
        sewing.Add(cap)
    for lower, upper in zip(*sections):
        loft = BRepOffsetAPI_ThruSections(False, True, 1e-7)
        loft.CheckCompatibility(False)
        loft.AddWire(lower)
        loft.AddWire(upper)
        loft.Build()
        if not loft.IsDone():
            raise ValueError('OpenCascade could not build the relief walls.')
        sewing.Add(loft.Shape())
    sewing.Perform()
    shell = sewing.SewedShape()
    if shell.IsNull() or shell.ShapeType() != TopAbs_SHELL or sewing.NbFreeEdges():
        raise ValueError('Surface Morph could not sew a closed relief shell.')
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shell)).Solid()
    if not BRepLib.OrientClosedSolid_s(solid):
        raise ValueError('OpenCascade could not orient the relief solid.')
    return checked(solid)


def _sloped_face(face, mapped_point):
    """Fit the mapped support, then transfer the original trim loops in UV."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    from .surface_native import make_surface_from_points
    from .surface_uv_native import uv_bounds

    profile, outlines = _wires(face)
    adaptor = BRepAdaptor_Surface(profile)
    if adaptor.GetType() != GeomAbs_Plane:
        raise ValueError('Surface Morph supports sloped panels made of planar faces.')
    u0, u1, v0, v1 = uv_bounds(profile)

    def sample(u, v):
        return mapped_point(g.pnt_tuple(adaptor.Value(u0+(u1-u0)*u, v0+(v1-v0)*v)))

    for count in (9, 17, 33):
        steps = count-1
        points = tuple(g.pnt_tuple(sample(i/steps, j/steps)) for j in range(count) for i in range(count))
        fitted = BRep_Tool.Surface_s(make_surface_from_points(points, count))
        a, b, c, d = fitted.Bounds()
        def uv(u, v):
            return a+(u-u0)*(b-a)/(u1-u0), c+(v-v0)*(d-c)/(v1-v0)
        mids = tuple((i+.5)/steps for i in range(steps))
        if all(fitted.Value(a+(b-a)*u, c+(d-c)*v).Distance(sample(u, v)) <= 2e-6
               for u in (0., *mids, 1.) for v in (0., *mids, 1.)):
            rings = tuple(_mapped_wire(w, profile, adaptor.Plane(), fitted, uv) for w in outlines)
            result = checked(_cap(fitted, rings, False))
            return TopoDS.Face_s(result.Oriented(face.Orientation()))
    raise ValueError('Surface Morph could not fit the sloped panel within its sampling tolerance.')


@lru_cache(maxsize=24)
def _cylinder_patch(shape, box, target, frame, domains):
    return morph_shape(shape, box, target, frame, domains, reuse_cylinder=False)


def _repeat_cylinder(shape, box, target, frame, face, uv_bounds, intervals, w):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.gp import gp_Trsf, gp_Vec

    adaptor = BRepAdaptor_Surface(face)
    if adaptor.GetType() != GeomAbs_Cylinder:
        return None
    (u0, u1), (v0, v1) = intervals
    start_u, _, start_v, _ = uv_bounds
    # Equal UV cells may differ by a few ULPs. Use one canonical fit per size.
    width, height = round(u1-u0, 12), round(v1-v0, 12)
    if width <= 1e-8 or height <= 1e-8:
        return None
    template = _cylinder_patch(shape, box, target, frame,
                               ((start_u, start_u+width), (start_v, start_v+height), w))
    cylinder = adaptor.Cylinder()
    angle = u0-start_u if cylinder.Position().Direct() else start_u-u0
    transform = gp_Trsf()
    transform.SetRotation(cylinder.Axis(), angle)
    translation = gp_Vec(cylinder.Axis().Direction()).Multiplied(v0-start_v)
    transform.SetTranslationPart(gp_Vec(transform.TranslationPart()).Added(translation))
    return BRepBuilderAPI_Transform(template, transform, False).Shape()


def morph_shape(shape, box, target, frame, domains, *, reuse_cylinder=True):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.Geom import Geom_OffsetSurface
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SHELL
    from OCP.TopoDS import TopoDS, TopoDS_Iterator
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt, gp_Vec
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    from .surface_uv_native import select_face, uv_bounds

    low, high = _bounds((box,), frame)
    dx, dy, dz = (b-a for a,b in zip(low, high))
    if min(dx, dy) <= 1e-7:
        raise ValueError('Reference Box must have nonzero X and Y dimensions.')
    target_face = select_face(g.faces_of(target), 0)
    surface, ((u0, u1), (v0, v1)), orientation = _target(target_face, domains)
    uv_reversed = (u1-u0)*(v1-v0) < 0
    w0, w1 = domains[2] if domains[2] is not None else (0., dz)
    if reuse_cylinder and u0 < u1 and v0 < v1 and g.shape_kind(shape) == 'surface':
        a, b = _bounds((shape,), frame)
        if b[2]-a[2] > 1e-6:
            repeated = _repeat_cylinder(shape, box, target, frame, target_face, uv_bounds(target_face),
                                        ((u0, u1), (v0, v1)), (w0, w1))
            if repeated is not None:
                return repeated
    def uv(x, y):
        return u0+(x-low[0])*(u1-u0)/dx, v0+(y-low[1])*(v1-v0)/dy
    def normal_offset(z):
        return w0 if dz <= 1e-7 else w0+(z-low[2])*(w1-w0)/dz
    def layer(z):
        w = normal_offset(z)
        offset = surface if abs(w) <= 1e-12 else Geom_OffsetSurface(surface, orientation*w)
        plane = gp_Pln(gp_Ax3(gp_Pnt(*_world(frame, (0., 0., z))),
                              gp_Dir(*frame.normal), gp_Dir(*frame.axis_x)))
        return plane, offset
    def mapped_point(point):
        local = sub(point, frame.origin)
        x, y, z = (dot(local, axis) for axis in (frame.axis_x, frame.axis_y, frame.normal))
        u, v = uv(x, y)
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        surface.D1(u, v, p, du, dv)
        normal = du.Crossed(dv)
        if normal.Magnitude() <= 1e-12:
            raise ValueError('Surface Morph encountered a singular target normal.')
        normal.Normalize()
        p.Translate(normal.Multiplied(orientation*normal_offset(z)))
        return p

    def build(part):
        if part.ShapeType() == TopAbs_COMPOUND:
            iterator, items = TopoDS_Iterator(part), []
            while iterator.More():
                items.append(build(iterator.Value()))
                iterator.Next()
            return g.make_compound(items)
        kind = g.shape_kind(part)
        a, b = _bounds((part,), frame)
        if any(x < lo-1e-6 or y > hi+1e-6 for x,y,lo,hi in zip(a,b,low,high)):
            raise ValueError('Input geometry lies outside the Reference Box.')
        if kind == 'point':
            return g.make_point(g.pnt_tuple(layer(a[2])[1].Value(*uv(*a[:2]))))
        if kind == 'solid':
            if abs(w1-w0) <= 1e-7:
                raise ValueError('A relief solid needs a nonzero W span.')
            if any(period and abs(end-start) >= period-1e-7 for start,end,period in (
                    (u0, u1, surface.UPeriod() if surface.IsUPeriodic() else 0.),
                    (v0, v1, surface.VPeriod() if surface.IsVPeriodic() else 0.))):
                raise ValueError('Use a partial UV interval to keep the relief from overlapping at the seam.')
            profile, outlines = _wires(_prism_profile(part, frame, a[2], b[2]))
            reverse = _reverse_cap(profile, frame, uv_reversed)
            caps, sections = [], []
            plane, _ = layer(a[2])
            for height in (a[2], b[2]):
                _, offset = layer(height)
                rings = tuple(_mapped_wire(w, profile, plane, offset, uv) for w in outlines)
                caps.append(_cap(offset, rings, reverse))
                sections.append(rings)
            return _solid(caps, sections)
        if kind == 'surface' and b[2]-a[2] > 1e-6:
            from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

            faces = [_sloped_face(face, mapped_point) for face in g.faces_of(part)]
            if len(faces) == 1:
                return faces[0]
            sewing = BRepBuilderAPI_Sewing(1e-5)
            for face in faces:
                sewing.Add(face)
            sewing.Perform()
            result = sewing.SewedShape()
            if part.ShapeType() == TopAbs_SHELL and result.ShapeType() != TopAbs_SHELL:
                raise ValueError('Surface Morph could not sew the folded panel.')
            return checked(result)
        if b[2]-a[2] > 1e-6:
            raise ValueError('Surface Morph requires planar profiles parallel to the reference box XY plane.')
        plane, offset = layer((a[2]+b[2])/2)
        if kind == 'curve':
            result = _mapped_wire(TopoDS.Wire_s(g.to_wire(part)), None, plane, offset, uv)
            if not BRepCheck_Analyzer(result).IsValid():
                raise ValueError('OpenCascade returned an invalid morphed wire.')
            return result
        if kind == 'surface':
            faces = []
            for face in g.faces_of(part):
                profile, outlines = _wires(face)
                faces.append(checked(_cap(offset, tuple(
                    _mapped_wire(w, profile, plane, offset, uv) for w in outlines),
                    _reverse_cap(profile, frame, uv_reversed))))
            return faces[0] if len(faces) == 1 else g.make_compound(faces)
        raise ValueError('Surface Morph requires points, planar profiles or straight extrusions.')

    return build(shape)


def register_commands(ctx):
    from .curves import PlaneValue
    from .morph import morph_domains
    from .operation_native import native_job

    req = ctx.requests()
    kinds = ('point', 'curve', 'surface', 'solid', 'compound')

    def frame(command):
        plane = command.cplane
        return PlaneValue(tuple(map(float, plane.origin)), tuple(map(float, plane.xdir)),
                          tuple(map(float, plane.normal)))

    @ctx.command('boundingboxparam', mutates=False, label='Bounding Box')
    def bounding_box(command):
        sources = yield req.SelectReq('Select geometry to bound', kinds=kinds, min_count=1, max_count=240)
        mode = yield req.OptionReq('Bounding Box mode', ['Per Object', 'Union'], 'Per Object')
        plane = frame(command)
        def build(shapes):
            return [box_shape(shapes, plane)] if mode == 'Union' else [
                box_shape((shape,), plane) for shape in shapes]
        native_job(ctx, command, sources, build, 'Bounding Box')

    @ctx.command('surfacemorphparam', mutates=False, label='Surface Morph')
    def surface_morph(command):
        sources = yield req.SelectReq('Select geometry to morph', kinds=kinds, min_count=1, max_count=240)
        target = yield req.SelectReq('Select the target surface', kinds=('surface',),
                                     min_count=1, max_count=1, allow_preselected=False)
        plane = frame(command)
        mode = yield req.OptionReq('Target domains', ['Entire Surface', 'Custom UVW'], 'Entire Surface')
        domains = []
        if mode == 'Custom UVW':
            for axis in 'UVW':
                a = yield req.NumberReq(f'{axis} domain start', default=0.)
                b = yield req.NumberReq(f'{axis} domain end', default=1.)
                domains.append((a, b))
        settings = morph_domains(domains or (None, None, None))
        def build(shapes):
            items, surface = shapes[:-1], shapes[-1]
            box = box_shape(items, plane)
            return [morph_shape(shape, box, surface, plane, settings) for shape in items]
        native_job(ctx, command, [*sources, *target], build, 'Surface Morph')
