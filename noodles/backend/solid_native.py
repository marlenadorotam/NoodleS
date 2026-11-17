"""Read existing native primitive geometry in the shared OCC worker."""
import math
from dataclasses import replace
from .curves import PlaneValue, dot, cross, scale, add, sub, unit
from .solids import SolidValue


def box_data(shape, key):
    from serpentine3d.core import geometry as g
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    faces = list(g.faces_of(shape))
    if len(faces) != 6:
        raise ValueError('Reference Box requires a complete six-face box.')
    axes = []
    for face in faces:
        surface = BRepAdaptor_Surface(face, True)
        if surface.GetType() != GeomAbs_Plane:
            raise ValueError('Box faces must be planar.')
        axis = g.pnt_tuple(surface.Plane().Axis().Direction())
        if not any(abs(dot(axis, other)) > 1-1e-8 for other in axes):
            if any(abs(dot(axis, other)) > 1e-8 for other in axes):
                raise ValueError('Box faces must be orthogonal.')
            axes.append(axis)
    if len(axes) != 3:
        raise ValueError('Box needs three pairs of parallel faces.')
    x, y = axes[:2]
    z = unit(cross(x, y))
    points = []
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        points.append(g.pnt_tuple(BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))))
        explorer.Next()
    if not points:
        raise ValueError('Box has no vertices.')
    ranges = [(min(dot(p, a) for p in points), max(dot(p, a) for p in points)) for a in (x, y, z)]
    dimensions = tuple(b-a for a, b in ranges)
    origin = add(scale(x, ranges[0][0]), add(scale(y, ranges[1][0]), scale(z, ranges[2][0])))
    frame = PlaneValue(origin, x, z)
    for p in points:
        if any(min(abs(dot(p, a)-lo), abs(dot(p, a)-hi)) > max(1e-7, (hi-lo)*1e-8) for a, (lo, hi) in zip((x, y, z), ranges)):
            raise ValueError('Box contains unexpected vertices.')
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    expected = math.prod(dimensions)
    if abs(abs(props.Mass())-expected) > max(1e-7, expected*1e-7):
        raise ValueError('Selected solid is not a complete orthogonal Box.')
    return SolidValue(key, 'box', frame, dimensions)


def inspect_solid(obj, key, primitive):
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from serpentine3d.core import geometry as g
    from . import solid_inspect_legacy as old
    # Never unwrap generated compounds or guess a primitive within a group.
    if obj.shape.ShapeType() not in ((TopAbs_FACE,) if primitive == 'paraboloid' else
            (TopAbs_SOLID, TopAbs_SHELL) if primitive == 'pyramid' else
            (TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE) if primitive == 'ellipsoid' else
            (TopAbs_SOLID, TopAbs_FACE) if primitive in ('cylinder', 'cone', 'truncated_cone') else (TopAbs_SOLID,)):
        raise ValueError('Select independent native '+primitive+' objects, not compounds or subobjects.')
    if primitive in ('box', 'box_from_center'):
        value = box_data(obj.shape, key)
        if primitive == 'box_from_center':
            width, depth, _ = value.dimensions
            value = replace(value, kind=primitive, frame=replace(value.frame, origin=value.frame.at(width/2, depth/2)))
    elif primitive == 'pyramid':
        value = pyramid_data(obj, key)
    elif primitive == 'ellipsoid':
        from .ellipsoid_native import inspect_ellipsoid
        value = inspect_ellipsoid(obj.shape, key)
    elif primitive in ('sphere', 'torus'):
        if len(g.faces_of(obj.shape)) != 1:
            raise ValueError('Reference '+primitive+' requires one complete native surface enclosing a solid.')
        data = (old._sphere_data_from_object if primitive == 'sphere' else old._torus_data_from_object)(obj)
        surfaces = [BRepAdaptor_Surface(face, True) for face in g.faces_of(obj.shape)]
        native = surfaces[0].Sphere() if primitive == 'sphere' else surfaces[0].Torus()
        frame = PlaneValue(data['center'], g.pnt_tuple(native.Position().XDirection()), g.pnt_tuple(native.Position().Direction()))
        dims = (data['radius'],) if primitive == 'sphere' else (data['major_radius'], data['minor_radius'])
        value = SolidValue(key, primitive, frame, dims)
    elif primitive == 'truncated_cone':
        data = old._ref_data_from_object(obj, truncated=True)
        sign = height_sign(obj, primitive)
        frame = PlaneValue(data['base'], data['axis_x'], scale(data['axis'], sign))
        value = SolidValue(key, primitive, frame,
                           (data['radius'], data['top_radius'], sign*data['height']), data['solid'])
    else:
        data = {'cylinder': old._ref_cylinder_data, 'cone': old._ref_data_from_object, 'paraboloid': old._inspect}[primitive](obj)
        origin = data['vertex'] if primitive == 'paraboloid' else data['base']
        frame = PlaneValue(origin, data['axis_x'], data['axis'])
        value = SolidValue(key, primitive, frame, (data['radius'], data['height']), data.get('solid', False))
    return {'key': key, 'id': obj.id, 'name': obj.name, 'recipe': value.to_wire()}


def height_sign(obj, primitive):
    from serpentine3d.core.user_text import value_of
    from .primitive_shapes import HEIGHT_SIGN_KEYS

    return -1. if value_of(getattr(obj, 'user_text', None), HEIGHT_SIGN_KEYS[primitive]) == '-1' else 1.


def pyramid_data(obj, key):
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import geometry as g

    def elements(shape, kind):
        values = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, kind, values)
        return [values.FindKey(i) for i in range(1, values.Extent() + 1)]

    shape = obj.shape
    solid = shape.ShapeType() == TopAbs_SOLID
    error = 'Reference Pyramid needs four planar triangles and a centered rectangular base.'
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError(error)
    vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertices)
    if vertices.Extent() != 5:
        raise ValueError(error)

    sides, caps = [], []
    for face in g.faces_of(shape):
        if (BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane or len(elements(face, TopAbs_WIRE)) != 1 or
                any(BRepAdaptor_Curve(TopoDS.Edge_s(e)).GetType() != GeomAbs_Line for e in elements(face, TopAbs_EDGE))):
            raise ValueError(error)
        ids = [vertices.FindIndex(v) for v in elements(face, TopAbs_VERTEX)]
        if len(ids) == 3:
            sides.append(ids)
        elif len(ids) == 4:
            caps.append(set(ids))
        else:
            raise ValueError(error)
    if len(sides) != 4 or len(caps) != int(solid):
        raise ValueError(error)
    shared = set.intersection(*(set(side) for side in sides))
    if len(shared) != 1:
        raise ValueError(error)
    tip_id, = shared
    edges = [tuple(i for i in side if i != tip_id) for side in sides]
    base_ids = set().union(*edges)
    if (len(base_ids) != 4 or len({frozenset(edge) for edge in edges}) != 4 or
            any(sum(i in edge for edge in edges) != 2 for i in base_ids) or solid and caps[0] != base_ids):
        raise ValueError(error)

    def coordinates(i):
        return g.pnt_tuple(BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertices.FindKey(i))))

    a, b = edges[0]
    c = next(j for edge in edges[1:] if a in edge for j in edge if j != a)
    d, = base_ids - {a, b, c}
    a, b, c, d = map(coordinates, (a, b, c, d))
    x, y = sub(b, a), sub(c, a)
    width, depth = math.dist(a, b), math.dist(a, c)
    if min(width, depth) <= 1e-9 or abs(dot(unit(x), unit(y))) > 1e-7:
        raise ValueError(error)
    center = add(a, scale(add(x, y), .5))
    offset = sub(coordinates(tip_id), center)
    height = math.dist(coordinates(tip_id), center)
    tol = max(1e-7, max(width, depth, height)*1e-7)
    if (height <= 1e-9 or math.dist(d, add(a, add(x, y))) > tol or
            max(abs(dot(offset, unit(x))), abs(dot(offset, unit(y)))) > tol):
        raise ValueError(error)
    sign = height_sign(obj, 'pyramid')
    frame = PlaneValue(center, x, scale(offset, sign/height))
    return SolidValue(key, 'pyramid', frame, (width, depth, sign*height), solid)
