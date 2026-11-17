"""Typed 2D primitive recipes and live native references, without Qt or OCC."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import uuid

from .datatree import Branch, DataTree, MAX_ITEMS, aligned, finite, topology
from .domain import DomainValue
from .point import PointValue
from .arithmetic import VectorValue, finite_number
from .parametric import ParametricObject


POPULATION_COUNT_LIMITS = {'population_2d_count': MAX_ITEMS, 'population_count': 4000}


def add(a, b):
    return tuple(x+y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def scale(a, value):
    return tuple(x*value for x in a)


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def unit(vector):
    length = math.hypot(*vector)
    if not math.isfinite(length) or length <= 1e-12:
        raise ValueError('A plane needs nonzero independent directions.')
    return scale(vector, 1/length)


def xyz(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError('Expected three coordinates.')
    return tuple(finite(v) for v in value)


@dataclass(frozen=True)
class PlaneValue:
    origin: tuple = (0., 0., 0.)
    axis_x: tuple = (1., 0., 0.)
    normal: tuple = (0., 0., 1.)

    def __post_init__(self):
        normal = xyz(self.normal)
        epsilon=8*math.ulp(1.)
        if abs(math.hypot(*normal)-1)>epsilon:
            normal=unit(normal)
        axis = xyz(self.axis_x)
        # Preserve already orthonormal frames bit-for-bit across wire/save
        # roundtrips. Re-normalizing them changed signatures by one ULP and
        # left derived native values permanently pending.
        if abs(math.hypot(*axis)-1)>epsilon or abs(dot(axis,normal))>epsilon:
            axis=unit(sub(axis,scale(normal,dot(axis,normal))))
        object.__setattr__(self, 'origin', xyz(self.origin))
        object.__setattr__(self, 'axis_x', axis)
        object.__setattr__(self, 'normal', normal)

    @property
    def axis_y(self):
        return cross(self.normal, self.axis_x)

    def at(self, x, y):
        return xyz(add(self.origin, add(scale(self.axis_x, x), scale(self.axis_y, y))))

    def to_wire(self):
        return {'origin': list(self.origin), 'axis_x': list(self.axis_x), 'normal': list(self.normal)}


def plane(value):
    if isinstance(value, PlaneValue):
        return value
    if isinstance(value, VectorValue):
        normal = unit(value.xyz)
        seed = min(((1, 0, 0), (0, 1, 0), (0, 0, 1)), key=lambda v: abs(dot(v, normal)))
        return PlaneValue(axis_x=seed, normal=normal)
    if isinstance(value, str) and value in ('XY', 'XZ', 'YZ'):
        return {'XY': PlaneValue(), 'XZ': PlaneValue(normal=(0, -1, 0)),
                'YZ': PlaneValue(axis_x=(0, 1, 0), normal=(1, 0, 0))}[value]
    raise ValueError('Connect Plane data or an explicit Vector normal.')


@dataclass(frozen=True)
class CurveValue:
    key: str
    kind: str
    points: tuple
    frame: PlaneValue = PlaneValue()
    radius: float = 0.
    angle: float = 0.  # signed radians for arcs
    closed: bool = False
    dimensions: tuple = ()

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key or len(self.key) > 256:
            raise ValueError('Invalid geometry part key.')
        if self.kind not in ('circle', 'ellipse', 'rectangle', 'line', 'arc', 'polyline'):
            raise ValueError('Unsupported primitive recipe.')
        object.__setattr__(self, 'points', tuple(xyz(p) for p in self.points))
        if len(self.points) > MAX_ITEMS:
            raise ValueError('Too many primitive vertices.')
        if not isinstance(self.frame, PlaneValue) or type(self.closed) is not bool:
            raise ValueError('Invalid primitive plane or closure.')
        finite_number(self.radius)
        finite_number(self.angle)

    @property
    def length(self):
        if self.kind == 'ellipse':
            return ellipse_perimeter(*self.dimensions)
        if self.kind == 'circle':
            return 2*math.pi*self.radius
        if self.kind == 'arc':
            return self.radius*abs(self.angle)
        pairs = list(zip(self.points, self.points[1:]))
        if self.closed:
            pairs.append((self.points[-1], self.points[0]))
        return sum(math.dist(a, b) for a, b in pairs)

    def to_wire(self):
        return {'key': self.key, 'kind': self.kind, 'points': [list(p) for p in self.points],
                'plane': self.frame.to_wire(), 'radius': self.radius, 'angle': self.angle,
                'closed': self.closed, 'dimensions': list(self.dimensions)}


def circle(key, center, radius, frame):
    radius = finite(radius)
    if radius <= 1e-9:
        raise ValueError('Radius must be greater than 1e-9.')
    return CurveValue(key, 'circle', (xyz(center),), PlaneValue(center, frame.axis_x, frame.normal), radius, closed=True)


@lru_cache(maxsize=4096)
def ellipse_perimeter(radius_x, radius_y):
    """Complete elliptic integral via AGM (NIST DLMF 19.8.1–6).

    Use E=K*(a1²-sum(n>=2, 2**(n-1)*c_n²)) to reduce cancellation for
    thin ellipses. https://dlmf.nist.gov/19.8.E6
    """
    major, minor = max(radius_x, radius_y), min(radius_x, radius_y)
    if major == minor:
        return 2*math.pi*major
    ratio = minor/major
    a1 = (1+ratio)/2
    a, g, weight, terms = a1, math.sqrt(ratio), 2., []
    for _ in range(32):
        c = (a-g)/2
        terms.append(weight*c*c)
        a, g = (a+g)/2, math.sqrt(a*g)
        weight *= 2
        if abs(a-g) <= 4*math.ulp(a):
            break
    integral = math.pi/(2*a)*(a1*a1-math.fsum(terms))
    return finite_number(4*major*integral)


def ellipse(key, center, radius_x, radius_y, frame):
    radius_x, radius_y = finite(radius_x), finite(radius_y)
    if min(radius_x, radius_y) <= 1e-9:
        raise ValueError('Ellipse radii must be greater than 1e-9.')
    return CurveValue(key, 'ellipse', (xyz(center),), PlaneValue(center, frame.axis_x, frame.normal),
                      closed=True, dimensions=(radius_x, radius_y))


def line(key, a, b):
    if math.dist(a, b) <= 1e-9:
        raise ValueError('Line endpoints must differ.')
    return CurveValue(key, 'line', (a, b))


def polyline(key, points, closed=False):
    points = tuple(xyz(p) for p in points)
    if points and closed and math.dist(points[0], points[-1]) <= 1e-9:
        points = points[:-1]
    if len(points) < (3 if closed else 2) or any(math.dist(a, b) <= 1e-9 for a, b in zip(points, points[1:])):
        raise ValueError('Polyline needs distinct consecutive vertices (at least 3 when closed).')
    return CurveValue(key, 'polyline', points, closed=closed)


def rectangle(key, x, y, center, frame):
    def axis(value):
        if isinstance(value, DomainValue):
            if value.start == value.end:
                raise ValueError('Rectangle dimensions must have nonzero length.')
            return abs(value.end-value.start), (value.start+value.end)/2
        value = finite_number(value)
        if value <= 1e-9:
            raise ValueError('Rectangle Width/Height must be positive.')
        return value, 0.
    width, dx = axis(x)
    height, dy = axis(y)
    frame = PlaneValue(add(center, add(scale(frame.axis_x, dx), scale(frame.axis_y, dy))), frame.axis_x, frame.normal)
    corners = tuple(frame.at(u*width/2, v*height/2) for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)))
    return CurveValue(key, 'rectangle', corners, frame, closed=True, dimensions=(width, height))


def arc(key, a, mid, b):
    a, mid, b = xyz(a), xyz(mid), xyz(b)
    u, v = sub(mid, a), sub(b, a)
    normal = cross(u, v)
    size = dot(normal, normal)
    if size <= 1e-24 or min(math.dist(a, mid), math.dist(a, b), math.dist(mid, b)) <= 1e-9:
        raise ValueError('Arc needs three distinct, non-collinear points.')
    center = add(a, scale(add(scale(cross(v, normal), dot(u, u)), scale(cross(normal, u), dot(v, v))), .5/size))
    frame = PlaneValue(center, sub(a, center), normal)
    end = sub(b, center)
    sweep = math.atan2(dot(end, frame.axis_y), dot(end, frame.axis_x)) % (2*math.pi)
    return CurveValue(key, 'arc', (a, mid, b), frame, math.dist(a, center), sweep)


def arc_center(key, center, radius, angle, frame):
    template = circle(key, center, radius, frame)
    angle = math.radians(finite_number(angle))
    if abs(angle) <= 1e-9 or abs(angle) >= 2*math.pi-1e-9:
        raise ValueError('Arc angle in degrees must be nonzero and strictly between -360 and 360.')
    points = tuple(template.frame.at(radius*math.cos(t), radius*math.sin(t)) for t in (0, angle/2, angle))
    return CurveValue(key, 'arc', points, template.frame, radius, angle)


def curve_from_wire(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid geometry recipe.')
    key, kind = data.get('key'), data.get('kind')
    if kind == 'wire':
        from .wires import wire_from_wire
        return wire_from_wire(data)
    if kind in ('curve', 'interpcurve'):
        from .splines import from_wire
        return from_wire(data)
    points = data.get('points')
    if not isinstance(points, list) or len(points) > MAX_ITEMS:
        raise ValueError('Invalid primitive vertices.')
    points = tuple(xyz(p) for p in points)
    if kind in ('circle', 'ellipse', 'rectangle'):
        raw = data.get('plane')
        if not isinstance(raw, dict):
            raise ValueError('Invalid primitive plane.')
        frame = PlaneValue(**raw)
        if kind == 'circle' and len(points) == 1:
            return circle(key, points[0], data.get('radius'), frame)
        if kind == 'ellipse' and len(points) == 1:
            dimensions = data.get('dimensions')
            if not isinstance(dimensions, (list, tuple)) or len(dimensions) != 2:
                raise ValueError('Ellipse needs two radii.')
            return ellipse(key, points[0], *dimensions, frame)
        if kind == 'rectangle' and len(points) == 4:
            width, height = math.dist(points[0], points[1]), math.dist(points[1], points[2])
            result = rectangle(key, width, height, frame.origin, frame)
            if any(math.dist(a, b) > 1e-6 for a, b in zip(result.points, points)):
                raise ValueError('Reference geometry is no longer a rectangle.')
            return result
    if kind == 'line' and len(points) == 2:
        return line(key, *points)
    if kind == 'arc' and len(points) == 3:
        result = arc(key, *points)
        if 'plane' in data and 'angle' in data and 'radius' in data:
            frame = PlaneValue(**data['plane'])
            radius, sweep = finite(data['radius']), finite_number(data['angle'])
            if radius <= 1e-9 or not 1e-9 < abs(sweep) < 2*math.pi-1e-9:
                raise ValueError('Invalid arc parameters.')
            tolerance=max(1e-7,radius*1e-10)
            expected=tuple(frame.at(radius*math.cos(t),radius*math.sin(t)) for t in (0,sweep))
            delta=sub(points[1],frame.origin)
            progress=(math.atan2(dot(delta,frame.axis_y),dot(delta,frame.axis_x))*(1 if sweep>0 else -1))%(2*math.pi)
            # A 3-point Arc's through-point is anywhere INSIDE its sweep,
            # not necessarily at half of the angle (Arc from Center is).
            if (any(math.dist(a,b)>tolerance for a,b in zip((points[0],points[-1]),expected))
                    or abs(math.hypot(*delta)-radius)>tolerance or abs(dot(delta,frame.normal))>tolerance
                    or not 0<progress<abs(sweep)):
                raise ValueError('Arc recipe parameters do not match its points.')
            result = CurveValue(key, 'arc', points, frame, radius, sweep)
        return result
    if kind == 'polyline':
        if type(data.get('closed')) is not bool:
            raise ValueError('Invalid polyline closure.')
        return polyline(key, points, data['closed'])
    raise ValueError('Invalid primitive kind or vertex count.')


@dataclass(frozen=True)
class CurveInput:
    port: str
    label: str
    kind: str
    default: object = None
    choices: tuple = ()
    optional: bool = False


CENTER = CurveInput('C', 'Center', 'center', (0., 0., 0.))
PLANE = CurveInput('P', 'Plane / Normal', 'plane', 'XY')
CURVE_SPECS = {
    'curve': {'name': 'Curve', 'class': 'CurveNode', 'inputs': (
        CurveInput('P', 'Control Points', 'points'), CurveInput('D', 'Degree', 'degree_control', 3),
        CurveInput('C', 'Closed', 'boolean', False)),
        'outputs': ('C', 'V', 'D', 'Cl', 'Per', 'L', 'Count')},
    'interpcurve': {'name': 'InterpCurve', 'class': 'InterpCurveNode', 'inputs': (
        CurveInput('P', 'Interpolation Points', 'points'), CurveInput('D', 'Degree', 'degree_interp', 3),
        CurveInput('C', 'Closed', 'boolean', False), CurveInput('T', 'Periodic', 'boolean', False),
        CurveInput('K', 'Knot Style', 'knot_style', 1, ('Uniform', 'Chord', 'Square Root Chord'))),
        'outputs': ('C', 'V', 'CP', 'D', 'Cl', 'Per', 'L', 'Count')},
    'circle': {'name': 'Circle', 'class': 'CircleNode', 'inputs': (CurveInput('R', 'Radius', 'number', 10.), CENTER, PLANE),
               'outputs': ('C', 'O', 'R', 'N', 'P', 'L', 'Count')},
    'ellipse': {'name': 'Ellipse', 'class': 'EllipseNode', 'inputs': (
        CurveInput('A', 'Radius X', 'number', 10.), CurveInput('B', 'Radius Y', 'number', 5.), CENTER, PLANE),
        'outputs': ('C', 'O', 'A', 'B', 'N', 'P', 'L', 'Count')},
    'rectangle': {'name': 'Rectangle', 'class': 'RectangleNode', 'inputs': (CurveInput('X', 'Width / X Domain', 'dimension', 10.),
        CurveInput('Y', 'Height / Y Domain', 'dimension', 10.), CENTER, PLANE), 'outputs': ('C', 'O', 'X', 'Y', 'P', 'N', 'V', 'L', 'Count')},
    'line': {'name': 'Line', 'class': 'LineNode', 'inputs': (CurveInput('A', 'Start', 'point', (0., 0., 0.)),
        CurveInput('B', 'End', 'point', (10., 0., 0.))), 'outputs': ('C', 'A', 'B', 'L', 'D', 'Count')},
    'arc': {'name': 'Arc', 'class': 'ArcNode', 'inputs': (CurveInput('A', 'Start', 'point', (-10., 0., 0.)),
        CurveInput('M', 'Through', 'point', (0., 10., 0.)), CurveInput('B', 'End', 'point', (10., 0., 0.))),
        'outputs': ('C', 'O', 'R', 'P', 'N', 'A', 'M', 'B', 'L', 'S', 'Count')},
    'arc_center': {'name': 'Arc from Center', 'class': 'ArcCenterNode', 'inputs': (CENTER,
        CurveInput('R', 'Radius', 'number', 10.), CurveInput('A', 'Angle (degrees)', 'number', 90.), PLANE),
        'outputs': ('C', 'O', 'R', 'P', 'N', 'A', 'M', 'B', 'L', 'S', 'Count')},
    'polyline': {'name': 'Polyline', 'class': 'PolylineNode', 'inputs': (CurveInput('P', 'Vertices', 'points'),
        CurveInput('C', 'Closed', 'boolean', False)), 'outputs': ('C', 'V', 'L', 'Closed', 'Count')},
}
CURVE_NODE_OPERATIONS = {spec['class']: op for op, spec in CURVE_SPECS.items()}


def is_curve_recipe(value):
    if isinstance(value, CurveValue):
        return True
    from .moves import RigidValue, TranslatedValue
    from .operations import OperationValue
    from .fillet_curves import FILLET_PARAMETRIC
    from .surface_reference import SurfaceReferenceValue
    while isinstance(value, (RigidValue, TranslatedValue)):
        value = value.source
    if isinstance(value, OperationValue) and value.kind == 'offset':
        return not (value.fill or value.solid) and is_curve_recipe(value.sources[0])
    if isinstance(value, OperationValue) and value.kind in (
            'array', 'array_polar', 'objects_on_points', 'surface_morph', 'box_morph', 'project', 'scale_non_uniform'):
        return is_curve_recipe(value.sources[0])
    return (isinstance(value, CurveValue)
            or isinstance(value, SurfaceReferenceValue) and value.native_kind == 'curve'
            or isinstance(value, OperationValue) and (value.result_kind == 'curve' or value.kind in (
                FILLET_PARAMETRIC, 'map_surface', 'surface_isocurves')))


def input_tree(value, descriptor, mode='none', default=False, *, keep_normal=False):
    if default and descriptor.kind == 'vector':
        value = VectorValue(tuple(value))
    if default and descriptor.kind in ('point', 'center'):
        value = PointValue('default:'+descriptor.port, xyz(value))
    is_path = descriptor.kind == 'path_text' and isinstance(value, tuple) and all(type(i) is int for i in value)
    tree = topology(list(value) if isinstance(value, tuple) and not is_path else value, mode)
    def checked(item):
        if descriptor.kind == 'items':
            return item
        if descriptor.kind == 'text':
            if not isinstance(item, str):
                raise ValueError(descriptor.label + ' requires text.')
            return item
        if descriptor.kind in ('color', 'label_text'):
            from .annotations import color_value, label_text
            return (color_value if descriptor.kind == 'color' else label_text)(item)
        if descriptor.kind == 'path_text':
            from .datatree import branch_path
            return '' if descriptor.port == 'S' and item == '' else branch_path(item)
        if descriptor.kind in ('bool_cast', 'list_index'):
            from .list_nodes import bool_value, list_index
            return (bool_value if descriptor.kind == 'bool_cast' else list_index)(item)
        if descriptor.kind == 'weave_index':
            from .list_nodes import list_index
            return int(item) if type(item) is bool else list_index(item)
        if descriptor.kind == 'pull_attractor':
            from .pull import is_attractor
            if not is_attractor(item):
                raise ValueError('Pull Point G requires typed Points or Curves.')
            return item
        if descriptor.kind == 'sample_curve':
            from .curve_sampling import is_sample_curve
            if not is_sample_curve(item):
                raise ValueError('Connect typed curve geometry.')
            return item
        if descriptor.kind == 'division_count':
            from .curve_sampling import MAX_DIVISIONS
            from .splines import integer
            return integer(item, descriptor.label, 1, MAX_DIVISIONS)
        if descriptor.kind == 'penrose_generations':
            from .penrose import MAX_GENERATIONS
            from .splines import integer
            return integer(item, descriptor.label, 0, MAX_GENERATIONS)
        if descriptor.kind in ('orientation', 'choice_index'):
            from .splines import integer
            return integer(item, descriptor.label, 0, len(descriptor.choices) - 1)
        if descriptor.kind == 'uv_grid_count':
            from .previews import MAX_UV_GRID_DIVISIONS
            from .splines import integer
            return integer(item, descriptor.label, 1, MAX_UV_GRID_DIVISIONS)
        if descriptor.kind == 'braced_grid_count':
            from .surface_structure import divisions
            return divisions(item, descriptor.label)
        if descriptor.kind == 'face_index':
            from .splines import integer
            return integer(item, 'Face Index', 0, MAX_ITEMS)
        if descriptor.kind == 'uv_domain':
            from .surface_uv import checked_uv_domain
            return checked_uv_domain(item)
        if descriptor.kind == 'domain2':
            from .surface_uv import Domain2Value
            if not isinstance(item, Domain2Value):
                raise ValueError(descriptor.label + ' needs a Domain².')
            return item
        if descriptor.kind == 'morph_domain':
            if not isinstance(item, DomainValue):
                raise ValueError(descriptor.label + ' needs a Domain.')
            return item
        if descriptor.kind == 'morph_box':
            from .morph import is_box
            if not is_box(item):
                raise ValueError('Connect a Bounding Box or Box to Reference Box.')
            return item
        if descriptor.kind == 'target_box':
            from .morph import is_target_box
            if not is_target_box(item):
                raise ValueError('Connect Surface Box.B to Target Box.')
            return item
        if descriptor.kind in ('uv_surface', 'domain2_or_surface'):
            from .surface_uv import Domain2Value, is_uv_geometry
            if is_uv_geometry(item) or descriptor.kind == 'domain2_or_surface' and isinstance(item, Domain2Value):
                return item
            raise ValueError(descriptor.label + ' requires typed surface or domain data.')
        if descriptor.kind=='move_geometry':
            from .moves import is_geometry
            if is_geometry(item):
                return item
            raise ValueError(descriptor.label + ' requires typed Point, Curve, Surface, Solid or Grid geometry.')
        if descriptor.kind in ('boolean_solid', 'native_boolean_operand'):
            from .booleans import is_boolean_operand
            solid_only = descriptor.kind == 'boolean_solid'
            if not is_boolean_operand(item, solid_only=solid_only):
                required = 'closed solid' if solid_only else 'solid or surface'
                raise ValueError(descriptor.label + f' requires {required} geometry.')
            return item
        if descriptor.kind in ('curve','geometry'):
            if is_curve_recipe(item):
                return item
            if descriptor.kind=='geometry':
                from .moves import TranslatedValue, RigidValue
                if isinstance(item,(TranslatedValue, RigidValue)):
                    return item
                from .operations import OperationValue
                from .solids import SolidValue
                from .surface_reference import SurfaceReferenceValue
                if isinstance(item,(OperationValue,SolidValue,SurfaceReferenceValue)):
                    return item
            raise ValueError(descriptor.label+' requires deferred Curve/Surface geometry.')
        if descriptor.kind == 'axis':
            if isinstance(item,PlaneValue) or isinstance(item,CurveValue) and item.kind=='line':
                return item
            if default:
                return plane(item)
            raise ValueError('Axis requires a Line or Plane; other curves are not axes.')
        if descriptor.kind == 'loft_options':
            from .data_helpers import LoftOptionsValue
            if not isinstance(item, LoftOptionsValue):
                raise ValueError('Connect typed Loft Options.')
            return item
        if descriptor.kind == 'loft_type':
            from .splines import integer
            return integer(item,'Loft Type',0,1)
        if descriptor.kind == 'surface_u':
            from .splines import integer
            return integer(item,'Points per Row',2,1250)
        if descriptor.kind == 'sweep_samples':
            from .splines import integer
            return integer(item,descriptor.label,4,129)
        if descriptor.kind in POPULATION_COUNT_LIMITS:
            from .splines import integer
            return integer(item, descriptor.label, 0, POPULATION_COUNT_LIMITS[descriptor.kind])
        if descriptor.kind in ('array_count', 'polar_array_count', 'population_seed'):
            from .splines import integer
            low, high = {'array_count': (1, 1600), 'polar_array_count': (2, 360),
                         'population_seed': (-2147483648, 2147483647)}[descriptor.kind]
            return integer(item, descriptor.label, low, high)
        if descriptor.kind == 'placement_scale':
            from .placement import placement_scale
            return placement_scale(item)
        if descriptor.kind == 'vector':
            if not isinstance(item,VectorValue):
                raise ValueError(descriptor.label+' requires typed Vector data.')
            return item
        if descriptor.kind in ('point', 'center', 'points'):
            if not isinstance(item, PointValue):
                raise ValueError(descriptor.label+' requires typed Point data.')
            return item
        if descriptor.kind == 'plane':
            normalized = plane(item)
            return item if keep_normal and isinstance(item, VectorValue) else normalized
        if descriptor.kind == 'dimension' and isinstance(item, DomainValue):
            return item
        if descriptor.kind in ('boolean', 'solid_mode'):
            if type(item) is bool or type(item) in (int, float) and item in (0, 1):
                return bool(item)
            raise ValueError(descriptor.label+' requires Boolean or 0/1.')
        if descriptor.kind in ('grid_count', 'polar_count'):
            from .grids import integer
            return integer(item, 3 if descriptor.kind == 'polar_count' else 1)
        if descriptor.kind.startswith('degree_') or descriptor.kind == 'knot_style':
            from .splines import integer
            low, high = (2, 10) if descriptor.kind == 'degree_control' else (1, 5) if descriptor.kind == 'degree_interp' else (0, 2)
            return integer(item, descriptor.label, low, high)
        return finite_number(item)
    return DataTree(tuple(Branch(b.path, tuple(checked(v) for v in b.items), b.keys) for b in tree.branches))


def normalize_curve_state(operation, data, *, spec=None, decoder=None, reference_kind=None):
    spec = CURVE_SPECS[operation] if spec is None else spec
    decoder = decoder or curve_from_wire
    mode = data.get('mode', 'generate')
    if mode not in ('generate', 'reference'):
        raise ValueError('Unknown geometry mode.')
    state = {'mode': mode, 'primitive': operation}
    for key in ('project_uuid', 'node_uuid'):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError('Invalid geometry UUID.')
        state[key] = str(uuid.UUID(value)) if value else ''
    modes = data.get('tree_modes', {})
    if (not isinstance(modes, dict) or set(modes)-{i.port for i in spec['inputs']}-{'References'}
            or any(v not in ('none', 'graft', 'flatten') for v in modes.values())):
        raise ValueError('Invalid primitive input modifiers.')
    state['tree_modes'] = {p: m for p, m in modes.items() if m != 'none'}
    parameters = data.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('Invalid primitive parameters.')
    state['parameters'] = {}
    for descriptor in spec['inputs']:
        if descriptor.default is not None:
            value = parameters.get(descriptor.port, descriptor.default)
            if descriptor.kind in ('center', 'point','vector'):
                value = list(xyz(value))
            elif descriptor.kind in ('plane','axis'):
                if value not in ('XY', 'XZ', 'YZ'):
                    raise ValueError('Choose a default world plane.')
            elif descriptor.kind in ('boolean', 'solid_mode'):
                if descriptor.kind == 'solid_mode' and type(value) in (int, float) and value in (0, 1):
                    value = bool(value)
                if type(value) is not bool:
                    raise ValueError(descriptor.label+' must be Boolean.')
            elif descriptor.kind == 'bool_cast':
                if type(value) is not bool:
                    raise ValueError('Bool default must be Boolean.')
            elif descriptor.kind == 'list_index':
                from .list_nodes import list_index
                value = list_index(value)
            elif descriptor.kind == 'color':
                from .annotations import color_value
                value = str(color_value(value))
            elif descriptor.kind in ('text', 'path_text', 'label_text'):
                if not isinstance(value, str):
                    raise ValueError(descriptor.label + ' requires text.')
            elif descriptor.kind == 'surface_u' and value == 'auto':
                pass
            elif descriptor.kind.startswith('degree_') or descriptor.kind in POPULATION_COUNT_LIMITS or descriptor.kind in ('knot_style', 'grid_count',
                    'polar_count', 'loft_type', 'surface_u', 'sweep_samples', 'division_count', 'uv_grid_count',
                    'face_index', 'array_count', 'polar_array_count', 'population_seed',
                    'braced_grid_count', 'orientation', 'choice_index', 'penrose_generations'):
                value = input_tree(value, descriptor).values()[0]
            else:
                value = finite(value)
            state['parameters'][descriptor.port] = value
    refs = data.get('references', [])
    if not isinstance(refs, list) or len(refs) > MAX_ITEMS:
        raise ValueError('Invalid primitive references.')
    state['references'] = []
    for ref in refs:
        if (not isinstance(ref, dict) or not all(isinstance(ref.get(k), str) and ref[k] and len(ref[k]) <= 256 for k in ('key', 'id'))
                or not isinstance(ref.get('name', ''), str) or len(ref.get('name', '')) > 1000):
            raise ValueError('Invalid primitive reference record.')
        recipe = decoder({**ref.get('recipe', {}), 'key': ref['key']})
        expected = reference_kind or ('arc' if operation == 'arc_center' else operation)
        if recipe.kind != expected:
            raise ValueError('Reference geometry does not match this primitive.')
        state['references'].append({'key': ref['key'], 'id': ref['id'], 'name': ref.get('name', ''), 'recipe': recipe.to_wire()})
        if 'move_offset' in ref:
            state['references'][-1]['move_offset']=list(xyz(ref['move_offset']))
        if 'move_transform' in ref:
            from .rigid_motion import from_wire
            state['references'][-1]['move_transform'] = from_wire(ref['move_transform']).to_wire()
    if len({r['key'] for r in refs}) != len(refs):
        raise ValueError('Duplicate primitive reference keys.')
    return state


def matched_inputs(trees):
    """Legacy primitive slot matching: one flat full list fills the tree once."""
    multi = [tree for tree in trees if len(tree.branches) > 1]
    if not multi:
        return trees
    rows = tuple(aligned(*multi))
    widths = tuple(len(items) for _, items in rows)
    total = sum(widths)
    result = []
    for tree in trees:
        if len(tree.branches) != 1 or tree.count in (0, 1):
            result.append(tree)
            continue
        branch = tree.branches[0]
        if tree.count == total:
            offset, branches = 0, []
            for path, items in rows:
                width = len(items)
                branches.append(Branch(path, branch.items[offset:offset+width], branch.keys[offset:offset+width]))
                offset += width
            result.append(DataTree(tuple(branches)))
        elif all(tree.count == width for width in widths):
            result.append(tree)
        else:
            raise ValueError('Ambiguous flat primitive input length for these branch widths. Match the DataTree explicitly.')
    return result


def evaluate_curve(operation, parameters, inputs):
    state = normalize_curve_state(operation, parameters)
    if state['mode'] == 'reference':
        if parameters.get('reference_error'):
            raise ValueError(parameters['reference_error'])
        if not state['references']:
            raise ValueError('Select native objects in Serpentine, then click Set reference.')
        values = tuple(curve_from_wire(r['recipe']) for r in state['references'])
        tree = topology(DataTree((Branch((0,), values, tuple(v.key for v in values)),)), state['tree_modes'].get('References', 'none'))
    else:
        spec = CURVE_SPECS[operation]
        trees = []
        for descriptor in spec['inputs']:
            connected = descriptor.port in inputs
            if not connected and descriptor.default is None:
                raise ValueError('Connect input '+descriptor.port+'.')
            value = inputs[descriptor.port] if connected else state['parameters'][descriptor.port]
            trees.append(input_tree(value, descriptor, state['tree_modes'].get(descriptor.port, 'none'), not connected))
        branches, occurrences = [], {}
        if operation in ('polyline', 'curve', 'interpcurve'):
            # Vertices are a list per branch, not one curve per point.
            scaffold = DataTree(tuple(Branch(b.path, (b.items[0],) if b.items else ()) for b in trees[0].branches))
            trees = [trees[0], *matched_inputs([scaffold, *trees[1:]])[1:]]
            groups = []
            for path, rows in aligned(*trees):
                if not rows:
                    groups.append(Branch(path, ()))
                    continue
                args = {}
                for index, descriptor in enumerate(spec['inputs'][1:], 1):
                    unique = {values[index] for values, _ in rows}
                    if len(unique) != 1:
                        raise ValueError(spec['name']+' '+descriptor.label+' must be constant within each point branch.')
                    args[descriptor.port] = next(iter(unique))
                keys = tuple(keys[0] for _, keys in rows)
                key = hashlib.sha256(json.dumps((path, keys)).encode()).hexdigest()[:24]
                vertices = tuple(values[0].xyz for values, _ in rows)
                if operation == 'polyline':
                    value = polyline(key, vertices, args['C'])
                else:
                    from .splines import spline
                    value = spline(key, operation, vertices, args['D'], args['C'], args.get('T', False), args.get('K', 1))
                groups.append(Branch(path, (value,), (key,)))
            tree = DataTree(tuple(groups))
        else:
            trees = matched_inputs(trees)
            for path, rows in aligned(*trees):
                values = []
                for items, provenance in rows:
                    signature = json.dumps(provenance)
                    count = occurrences.get(signature, 0)
                    occurrences[signature] = count+1
                    key = hashlib.sha256(f'{signature}:{count}'.encode()).hexdigest()[:24]
                    args = dict(zip((d.port for d in spec['inputs']), items))
                    if operation in ('circle', 'ellipse', 'rectangle', 'arc_center'):
                        frame = args['P']
                        center = args['C'].xyz if 'C' in inputs else add(frame.origin, args['C'].xyz)
                    if operation == 'circle':
                        value = circle(key, center, args['R'], frame)
                    elif operation == 'ellipse':
                        value = ellipse(key, center, args['A'], args['B'], frame)
                    elif operation == 'rectangle':
                        value = rectangle(key, args['X'], args['Y'], center, frame)
                    elif operation == 'line':
                        value = line(key, args['A'].xyz, args['B'].xyz)
                    elif operation == 'arc':
                        value = arc(key, args['A'].xyz, args['M'].xyz, args['B'].xyz)
                    else:
                        value = arc_center(key, center, args['R'], args['A'], frame)
                    values.append(value)
                branches.append(Branch(path, tuple(values), tuple(v.key for v in values)))
            tree = DataTree(tuple(branches))
    return curve_outputs(operation, tree, parameters.get('curve_details', {}))


def curve_outputs(operation, tree, details=None):
    def mapped(fn):
        return DataTree(tuple(Branch(b.path, tuple(fn(v) for v in b.items), b.keys) for b in tree.branches))
    def vertex(value, index):
        return PointValue(value.key+':v'+str(index), value.points[index])
    resolved = {}
    if operation in ('curve', 'interpcurve'):
        from .splines import signature
        for value in tree.values():
            record = (details or {}).get(value.key, {})
            if record.get('signature') == signature(value):
                resolved[value.key] = curve_from_wire(record['recipe'])
    actual = lambda v: resolved.get(v.key, v)
    outputs = {'C': tree, 'Count': tree.count, 'L': mapped(lambda v: actual(v).length)}
    if operation in ('circle', 'ellipse', 'rectangle', 'arc', 'arc_center'):
        outputs.update(O=mapped(lambda v: PointValue(v.key+':center', v.frame.origin)),
                       P=mapped(lambda v: v.frame), N=mapped(lambda v: VectorValue(v.frame.normal)))
    if operation in ('circle', 'arc', 'arc_center'):
        outputs['R'] = mapped(lambda v: v.radius)
    if operation in ('arc', 'arc_center'):
        outputs.update(A=mapped(lambda v: vertex(v, 0)), M=mapped(lambda v: vertex(v, 1)),
                       B=mapped(lambda v: vertex(v, 2)), S=mapped(lambda v: math.degrees(v.angle)))
    if operation == 'line':
        outputs.update(A=mapped(lambda v: vertex(v, 0)), B=mapped(lambda v: vertex(v, 1)),
                       D=mapped(lambda v: VectorValue(sub(v.points[1], v.points[0]))))
    if operation == 'rectangle':
        outputs.update(X=mapped(lambda v: v.dimensions[0]), Y=mapped(lambda v: v.dimensions[1]))
    if operation == 'ellipse':
        outputs.update(A=mapped(lambda v: v.dimensions[0]), B=mapped(lambda v: v.dimensions[1]))
    if operation in ('rectangle', 'polyline', 'curve', 'interpcurve'):
        groups = []
        for branch in tree.branches:
            if not branch.items:
                groups.append(Branch(branch.path+(0,), ()))
            for i, value in enumerate(branch.items):
                # Interpolation sites cannot be recovered from an arbitrary native NURBS.
                vertices = (() if operation == 'interpcurve' and value.knots else
                            tuple(vertex(value, j) for j in range(len(value.points))))
                groups.append(Branch(branch.path+(i,), vertices, tuple(v.key for v in vertices)))
        outputs['V'] = DataTree(tuple(groups))
    if operation in ('curve', 'interpcurve'):
        from .splines import PendingGeometry
        outputs.update(D=mapped(lambda v: actual(v).degree), Cl=mapped(lambda v: actual(v).closed),
                       Per=mapped(lambda v: actual(v).periodic))
        if operation == 'interpcurve':
            groups = []
            for branch in tree.branches:
                for i, value in enumerate(branch.items):
                    source = actual(value)
                    vertices = tuple(vertex(source, j) for j in range(len(source.points))) if source.knots else (PendingGeometry(),)
                    groups.append(Branch(branch.path+(i,), vertices))
            outputs['CP'] = DataTree(tuple(groups))
    if operation == 'polyline':
        outputs['Closed'] = mapped(lambda v: v.closed)
    return {name: outputs[name] for name in CURVE_SPECS[operation]['outputs']}


def curve_object_from_outputs(parameters, outputs):
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['C'],
                            parameters['mode'], tuple((r['key'], r['id']) for r in parameters.get('references', [])), kind='curves')


def curve_object_from_wire(data, *, decoder=None, kind='curves'):
    decoder = decoder or curve_from_wire
    if type(data.get('schema')) is not int or data['schema'] != 1 or data.get('mode') != 'generate':
        raise ValueError('Invalid curve ParametricObject schema or mode.')
    project, node = str(uuid.UUID(data['project_uuid'])), str(uuid.UUID(data['node_uuid']))
    branches = data.get('branches')
    if not isinstance(branches, list) or len(branches) > MAX_ITEMS:
        raise ValueError('Invalid primitive branches.')
    result = []
    total = 0
    for branch in branches:
        if not isinstance(branch, dict) or not isinstance(branch.get('parts'), list):
            raise ValueError('Invalid primitive branch.')
        total += len(branch['parts'])
        if total > MAX_ITEMS:
            raise ValueError('Too many geometry parts.')
        values = tuple(decoder(item) for item in branch['parts'])
        result.append(Branch(branch.get('path', ()), values, tuple(v.key for v in values)))
    tree = DataTree(tuple(result))
    if len({v.key for v in tree.values()}) != tree.count:
        raise ValueError('Geometry part keys must be unique.')
    return ParametricObject(project, node, tree, kind=kind)
