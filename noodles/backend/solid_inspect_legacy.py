"""Native readers reused from our former Serpentine/Ryven plugins; no scene writes."""
import math

# Source: RyvenLink.py:9241
def _sphere_data_from_object(obj):
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.GeomAbs import GeomAbs_Sphere
    from serpentine3d.core import geometry as geo

    object_id = str(getattr(obj, "id", ""))
    name = str(getattr(obj, "name", ""))
    kind = str(getattr(obj, "kind", "")).lower()
    shape = getattr(obj, "shape", None)

    if not object_id:
        raise ValueError("Sphere object has no SceneObject id")

    if shape is None:
        raise ValueError("Sphere object has no shape")

    if kind != "solid":
        raise ValueError(
            "Sphere requires a Serpentine solid; "
            f"received kind={kind or '?'}"
        )

    faces = list(geo.faces_of(shape))

    if not faces:
        raise ValueError(
            "Sphere contains no faces"
        )

    spherical_faces = []

    for face in faces:
        try:
            adaptor = BRepAdaptor_Surface(
                face,
                True,
            )

            if adaptor.GetType() == GeomAbs_Sphere:
                spherical_faces.append(
                    adaptor.Sphere()
                )
        except Exception:
            pass

    if len(spherical_faces) != 1:
        raise ValueError(
            "Sphere requires exactly one spherical face"
        )

    sphere = spherical_faces[0]
    location = sphere.Location()
    radius = float(
        sphere.Radius()
    )

    if radius <= 0.0:
        raise ValueError(
            "Sphere radius must be greater than zero"
        )

    # Reject a trimmed spherical solid / spherical sector. A genuine native
    # sphere fills the complete 4/3*pi*r^3 volume.
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(
        shape,
        props,
    )
    volume = abs(
        float(
            props.Mass()
        )
    )

    expected_volume = (
        (4.0 / 3.0)
        * math.pi
        * radius
        * radius
        * radius
    )

    tolerance = max(
        1.0e-8,
        expected_volume * 1.0e-7,
    )

    if abs(
        volume - expected_volume
    ) > tolerance:
        raise ValueError(
            "Selected solid is not a complete Sphere"
        )

    center = [
        float(location.X()),
        float(location.Y()),
        float(location.Z()),
    ]

    return {
        "id": object_id,
        "name": name,
        "kind": kind,
        "geometry_type": "sphere",
        "center": center,
        "radius": radius,
        "diameter": radius * 2.0,
        "volume": volume,
    }


# Source: RyvenLink.py:9984
def _torus_data_from_object(obj):
    import math

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.GeomAbs import GeomAbs_Torus
    from serpentine3d.core import geometry as geo

    object_id = str(getattr(obj, "id", ""))
    name = str(getattr(obj, "name", ""))
    kind = str(getattr(obj, "kind", "")).lower()
    shape = getattr(obj, "shape", None)

    if not object_id:
        raise ValueError("Torus object has no SceneObject id")

    if shape is None:
        raise ValueError("Torus object has no shape")

    if kind != "solid":
        raise ValueError(
            "Torus requires a Serpentine solid; "
            f"received kind={kind or '?'}"
        )

    faces = list(
        geo.faces_of(shape)
    )

    toroidal_faces = []

    for face in faces:
        try:
            adaptor = BRepAdaptor_Surface(
                face,
                True,
            )

            if adaptor.GetType() == GeomAbs_Torus:
                toroidal_faces.append(
                    adaptor.Torus()
                )
        except Exception:
            pass

    # A complete OCC torus made by the primitive builder is a closed solid
    # whose skin is one complete toroidal face. Partial/trimmed torii normally
    # introduce additional boundary faces and are deliberately rejected.
    if (
        len(faces) != 1
        or len(toroidal_faces) != 1
    ):
        raise ValueError(
            "Selected solid is not one complete Torus"
        )

    torus = toroidal_faces[0]

    location = torus.Location()
    axis_direction = torus.Axis().Direction()

    major_radius = float(
        torus.MajorRadius()
    )
    minor_radius = float(
        torus.MinorRadius()
    )

    if major_radius <= 0.0:
        raise ValueError(
            "Torus major radius must be greater than zero"
        )

    if minor_radius <= 0.0:
        raise ValueError(
            "Torus minor radius must be greater than zero"
        )

    center = [
        float(location.X()),
        float(location.Y()),
        float(location.Z()),
    ]

    axis = [
        float(axis_direction.X()),
        float(axis_direction.Y()),
        float(axis_direction.Z()),
    ]

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(
        shape,
        props,
    )
    volume = abs(
        float(
            props.Mass()
        )
    )

    # Standard ring-torus volume. The native Serpentine Torus primitive uses
    # the standard OCC torus representation.
    expected_volume = (
        2.0
        * math.pi
        * math.pi
        * major_radius
        * minor_radius
        * minor_radius
    )

    tolerance = max(
        1.0e-8,
        expected_volume * 1.0e-7,
    )

    if abs(
        volume - expected_volume
    ) > tolerance:
        raise ValueError(
            "Selected solid is not a complete standard Torus"
        )

    return {
        "id": object_id,
        "name": name,
        "kind": kind,
        "geometry_type": "torus",
        "center": center,
        "axis": axis,
        "major_radius": major_radius,
        "minor_radius": minor_radius,
        "outer_radius": major_radius + minor_radius,
        "inner_radius": major_radius - minor_radius,
        "volume": float(volume),
    }


# Source: serpentine_cylinder.py:110
def _ref_cylinder_coords(point):
    return [float(point.X()), float(point.Y()), float(point.Z())]


# Source: serpentine_cylinder.py:114
def _ref_cylinder_data(obj):
    """Read exact analytic cylindrical lateral Face or complete capped Solid.

    Never trusts object names or guesses dimensions from a bounding box.
    The native first/last V parameters identify the two end circles; the
    cylindrical axis and U-start identify a stable local frame.
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp

    shape = getattr(obj, 'shape', None)
    if shape is None or shape.IsNull():
        raise ValueError('Selected object has no OCC shape')
    topology = shape.ShapeType()
    if topology not in (TopAbs_FACE, TopAbs_SOLID):
        raise ValueError('Expected one cylindrical Surface or complete Solid')
    solid = topology == TopAbs_SOLID
    kind = str(getattr(obj, 'kind', '')).lower()
    if kind != ('solid' if solid else 'surface'):
        raise ValueError('SceneObject kind and native Cylinder topology disagree')

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    lateral = None
    cap_planes = []
    faces = 0
    while explorer.More():
        faces += 1
        adaptor = BRepAdaptor_Surface(TopoDS.Face_s(explorer.Current()), True)
        if adaptor.GetType() == GeomAbs_Cylinder:
            if lateral is not None:
                raise ValueError('Multiple cylindrical faces; not one Cylinder')
            lateral = adaptor
        elif adaptor.GetType() == GeomAbs_Plane:
            cap_planes.append(adaptor.Plane())
        else:
            raise ValueError('Cylinder contains non-cylindrical/non-planar faces')
        explorer.Next()
    if lateral is None or faces != (3 if solid else 1) or len(cap_planes) != (2 if solid else 0):
        raise ValueError('Expected one lateral face and two caps (Solid) or one face (Surface)')

    u0, u1 = float(lateral.FirstUParameter()), float(lateral.LastUParameter())
    v0, v1 = float(lateral.FirstVParameter()), float(lateral.LastVParameter())
    if (not all(math.isfinite(t) for t in (u0,u1,v0,v1)) or
            v1 - v0 <= 1e-9 or abs((u1-u0) - 2.0*math.pi) > 1e-5):
        raise ValueError('Reference Cylinder v.2 requires a complete untrimmed 360-degree lateral face')
    cylinder = lateral.Cylinder()
    radius = float(cylinder.Radius())
    if not math.isfinite(radius) or radius <= 1e-9:
        raise ValueError('Cylinder radius is invalid')
    location = _ref_cylinder_coords(cylinder.Location())
    axis = _ref_cylinder_coords(cylinder.Axis().Direction())
    point0 = _ref_cylinder_coords(lateral.Value(u0, v0))
    point1 = _ref_cylinder_coords(lateral.Value(u0, v1))
    t0 = sum((p-l)*a for p,l,a in zip(point0,location,axis))
    t1 = sum((p-l)*a for p,l,a in zip(point1,location,axis))
    base = [location[i] + t0*axis[i] for i in range(3)]
    top = [location[i] + t1*axis[i] for i in range(3)]
    delta = [top[i]-base[i] for i in range(3)]
    height = math.sqrt(sum(d*d for d in delta))
    if height <= 1e-9:
        raise ValueError('Cylinder has zero height')
    # OCC v is measured along its axis. Reject reversed/unexpected parametrizations
    # rather than producing a reference which flips on an update.
    if sum(delta[i]*axis[i] for i in range(3)) <= 0:
        raise ValueError('Cylinder has unsupported reversed V parametrization')
    radial = [point0[i]-base[i] for i in range(3)]
    radial_norm = math.sqrt(sum(x*x for x in radial))
    if radial_norm <= 1e-9:
        raise ValueError('Cylinder has no valid local X axis')
    axis_x = [x/radial_norm for x in radial]
    if abs(sum(a*b for a,b in zip(axis_x,axis))) > 1e-6:
        raise ValueError('Cylinder lateral frame is not orthogonal')
    centre = [(base[i]+top[i])/2.0 for i in range(3)]

    if solid:
        for cap in cap_planes:
            cp = _ref_cylinder_coords(cap.Location())
            tn = sum((cp[i]-location[i])*axis[i] for i in range(3))
            normal = _ref_cylinder_coords(cap.Axis().Direction())
            if abs(abs(sum(a*b for a,b in zip(normal, axis))) - 1.0) > 1e-6:
                raise ValueError('Cylinder cap is not perpendicular to the axis')
            if min(abs(tn-t0), abs(tn-t1)) > max(1e-6,height*1e-7):
                raise ValueError('Cylinder cap is not at an end circle')
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        volume = abs(float(props.Mass()))
        expected = math.pi*radius*radius*height
        if not math.isfinite(volume) or abs(volume-expected) > max(1e-6,expected*1e-6):
            raise ValueError('Selected Cylinder Solid is not a complete full cylinder')
    else:
        volume = 0.0
    return {'id':str(obj.id), 'name':str(obj.name), 'kind':kind,
            'geometry_type':'cylinder','solid':solid,
            'base':base, 'radius':radius,'diameter':2.0*radius,
            'height':height, 'top':top,'center':centre, 'axis':axis,
            'axis_x':axis_x, 'volume':volume}


# Source: serpentine_cone.py:136
def _ref_xyz(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(label + ' must be an XYZ vector')
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError(label + ' must contain finite coordinates')
    return result


# Source: serpentine_cone.py:145
def _ref_distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


# Source: serpentine_cone.py:149
def _ref_coords(p):
    return [float(p.X()), float(p.Y()), float(p.Z())]


# Source: serpentine_cone.py:153
def _ref_data_from_object(obj, *, truncated=False):
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp

    shape = getattr(obj, 'shape', None)
    if shape is None:
        raise ValueError('Object has no OCC shape')
    topology = shape.ShapeType()
    if topology not in (TopAbs_FACE, TopAbs_SOLID):
        raise ValueError('Selected object is not a single conical Face/Solid')
    solid = topology == TopAbs_SOLID
    kind = str(getattr(obj, 'kind', '')).lower()
    if kind != ('solid' if solid else 'surface'):
        raise ValueError('Native SceneObject kind does not match Cone topology')

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    cone = None
    caps = []
    number_faces = 0
    while explorer.More():
        number_faces += 1
        face = TopoDS.Face_s(explorer.Current())
        adaptor = BRepAdaptor_Surface(face, True)
        tp = adaptor.GetType()
        if tp == GeomAbs_Cone:
            if cone is not None:
                raise ValueError('Selected object contains multiple conical faces')
            cone = adaptor
        elif tp == GeomAbs_Plane:
            caps.append(adaptor)
        else:
            raise ValueError('Selected object has non-conical/non-planar faces')
        explorer.Next()
    cap_count = (2 if truncated else 1) if solid else 0
    if cone is None or number_faces != cap_count + 1 or len(caps) != cap_count:
        label = 'Truncated Cone' if truncated else 'Cone'
        raise ValueError('Selected object is not a complete ' + label)

    umin, umax = float(cone.FirstUParameter()), float(cone.LastUParameter())
    vmin, vmax = float(cone.FirstVParameter()), float(cone.LastVParameter())
    if (not all(math.isfinite(v) for v in (umin, umax, vmin, vmax))
            or vmax <= vmin or abs((umax-umin)-2*math.pi) > 1e-5):
        raise ValueError('Only full 360-degree untrimmed cones are supported')

    native = cone.Cone()
    location = _ref_coords(native.Location())
    native_z = _ref_coords(native.Axis().Direction())

    def cross_section(v):
        p = _ref_coords(cone.Value(umin, v))
        t = sum((p[i]-location[i])*native_z[i] for i in range(3))
        centre = [location[i]+native_z[i]*t for i in range(3)]
        return p, centre, _ref_distance(p, centre)

    end_a, centre_a, radius_a = cross_section(vmin)
    end_b, centre_b, radius_b = cross_section(vmax)
    if truncated:
        base_edge, base, radius = end_a, centre_a, radius_a
        tip, small = centre_b, radius_b
    elif radius_b > radius_a:
        base_edge, base, radius = end_b, centre_b, radius_b
        tip, small = centre_a, radius_a
    else:
        base_edge, base, radius = end_a, centre_a, radius_a
        tip, small = centre_b, radius_b
    height = _ref_distance(tip, base)
    if truncated:
        from .solids import truncated_cone_dimensions
        truncated_cone_dimensions(radius, small, height)
    elif not (math.isfinite(height) and math.isfinite(radius) and
              height > 1e-9 and radius > 1e-9 and small <= max(1e-8, radius*1e-7)):
        raise ValueError('Reference Cone needs one zero-radius apex')
    axis = [(tip[i]-base[i])/height for i in range(3)]
    x_axis = [(base_edge[i]-base[i])/radius for i in range(3)]
    # Axis & X are perpendicular for a true analytic cone.
    if abs(sum(axis[i]*x_axis[i] for i in range(3))) > 1e-6:
        raise ValueError('Invalid conical frame')
    if solid:
        cap_positions = []
        for adaptor in caps:
            cap = adaptor.Plane()
            cap_location = _ref_coords(cap.Location())
            normal = _ref_coords(cap.Axis().Direction())
            if abs(abs(sum(a*b for a, b in zip(normal, axis))) - 1.) > 1e-6:
                raise ValueError('Solid Cone cap is not perpendicular to its axis')
            cap_positions.append(sum((cap_location[i]-base[i])*axis[i] for i in range(3)))
        expected_positions = [0., height] if truncated else [0.]
        if any(abs(a-b) > max(1e-6, height*1e-7) for a, b in zip(sorted(cap_positions), expected_positions)):
            raise ValueError('Solid Cone has an unexpected planar cap')
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        volume = abs(float(props.Mass()))
        expected = math.pi*(radius*radius + radius*small + small*small if truncated else radius*radius)*height/3.
        if not math.isfinite(volume) or abs(volume-expected) > max(1e-6,expected*1e-6):
            raise ValueError('Selected solid is not a full conical solid')
    else:
        volume = 0.0
    data = {
        'id': str(obj.id), 'name': str(obj.name), 'kind':kind,
        'geometry_type':'cone', 'solid':solid,
        'base':base, 'radius':radius, 'diameter':2*radius,
        'height':height, 'tip':tip, 'axis':axis, 'axis_x':x_axis,
        'volume':volume,
    }
    if truncated:
        data.update(geometry_type='truncated_cone', top_radius=small)
    return data


# Source: serpentine_paraboloid.py:34
def _coords(native):
    return [float(native.X()), float(native.Y()), float(native.Z())]


# Source: serpentine_paraboloid.py:38
def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


# Source: serpentine_paraboloid.py:42
def _sub(a, b):
    return [x-y for x, y in zip(a, b)]


# Source: serpentine_paraboloid.py:46
def _norm(a):
    return math.sqrt(_dot(a, a))


# Source: serpentine_paraboloid.py:107
def _inspect(obj):
    """Read exact native Bezier-revolved surface; reject unrelated shapes.

    The shape itself, not its name or a transient SceneObject ID, supplies the
    dimensions. This also works after Serpentine restarts and rewrites IDs.
    """
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRep import BRep_Tool
    from OCP.Geom import Geom_SurfaceOfRevolution, Geom_BezierCurve

    if str(getattr(obj, 'kind', '')).lower() != 'surface':
        raise ValueError('Reference Paraboloid requires a native Surface')
    explorer = TopExp_Explorer(obj.shape, TopAbs_FACE)
    if not explorer.More():
        raise ValueError('Paraboloid has no OCC face')
    face = TopoDS.Face_s(explorer.Current())
    explorer.Next()
    if explorer.More():
        raise ValueError('Reference Paraboloid requires exactly ONE face')
    surface = BRep_Tool.Surface_s(face)
    if not isinstance(surface, Geom_SurfaceOfRevolution):
        raise ValueError('Not an analytic revolved Paraboloid from this plugin')
    profile = surface.BasisCurve()
    if not isinstance(profile, Geom_BezierCurve) or profile.NbPoles() != 3 or profile.IsRational():
        raise ValueError('Paraboloid must have a quadratic Bezier meridian')
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    adaptor = BRepAdaptor_Surface(face, True)
    u0,u1 = float(adaptor.FirstUParameter()),float(adaptor.LastUParameter())
    v0,v1 = float(adaptor.FirstVParameter()),float(adaptor.LastVParameter())
    if (not all(map(math.isfinite, (u0,u1,v0,v1))) or
            abs(u1-u0-2*math.pi)>1e-5 or abs(v0)>1e-7 or abs(v1-1.)>1e-7):
        raise ValueError('Only complete untrimmed Paraboloids are supported')
    vertex = _coords(profile.Pole(1))
    mid = _coords(profile.Pole(2))
    rim = _coords(profile.Pole(3))
    # Geometry is independent of axis direction sign: the increasing meridian
    # profile fixes which end is the vertex and which is the rim.
    axis = _coords(surface.Axis().Direction())
    height_signed = _dot(_sub(rim,vertex),axis)
    if height_signed < 0:
        axis = [-v for v in axis]
    height = abs(height_signed)
    rim_vec = _sub(rim,vertex)
    radius_vec = [rim_vec[j]-height*axis[j] for j in range(3)]
    radius = _norm(radius_vec)
    if radius < 1e-9 or height < 1e-9:
        raise ValueError('Degenerate native Paraboloid')
    axis_x = [v/radius for v in radius_vec]
    expected_mid = [vertex[j]+0.5*radius_vec[j] for j in range(3)]
    if _norm(_sub(expected_mid, mid))>max(1e-6,radius*1e-7):
        raise ValueError('Revolved profile is not a parabola z = H*(r/R)^2')
    rim_centre = [vertex[j]+height*axis[j] for j in range(3)]
    return {'id':str(obj.id), 'name':str(obj.name), 'kind':'surface',
            'geometry_type':'paraboloid', 'vertex':vertex,
            'radius':radius, 'diameter':2.*radius, 'height':height,
            'rim_center':rim_centre, 'axis':axis, 'axis_x':axis_x}

