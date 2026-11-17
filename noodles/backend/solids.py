"""Deferred 3D primitive recipes and explicit DataTree slot matching; no OCC/Qt."""
from dataclasses import dataclass
import hashlib
import json
import math

from .curves import (CurveInput, PlaneValue, input_tree, normalize_curve_state,
                     matched_inputs, add, scale, curve_object_from_wire)
from .datatree import Branch, DataTree, aligned, finite, topology
from .arithmetic import VectorValue, finite_number
from .point import PointValue
from .parametric import ParametricObject


BASE = CurveInput('O', 'Base Center', 'center', (0., 0., 0.))
CORNER = CurveInput('O', 'Base Corner', 'center', (0., 0., 0.))
VERTEX = CurveInput('O', 'Vertex', 'center', (0., 0., 0.))
CENTER = CurveInput('O', 'Center', 'center', (0., 0., 0.))
PLANE = CurveInput('P', 'Plane / Normal', 'plane', 'XY')
RADIUS = CurveInput('R', 'Radius', 'number', 10.)
HEIGHT = CurveInput('H', 'Height', 'number', 20.)
TYPE = CurveInput('S', 'Geometry Type', 'solid_mode', True, ('Shell', 'Solid'))
BOX_DIMENSIONS = (CurveInput('X', 'Width', 'number', 10.), CurveInput('Y', 'Depth', 'number', 10.),
                  CurveInput('Z', 'Height', 'number', 10.))
SOLID_SPECS = {
    'box': {'class': 'BoxNode', 'name': 'Box', 'primary': 'G', 'inputs': (*BOX_DIMENSIONS, CORNER, PLANE),
        'outputs': ('G', 'O', 'X', 'Y', 'Z', 'P', 'C', 'V', 'Count')},
    'box_from_center': {'class': 'BoxFromCenterNode', 'name': 'Box from Center', 'primary': 'G',
        'inputs': (*BOX_DIMENSIONS, BASE, PLANE),
        'outputs': ('G', 'O', 'X', 'Y', 'Z', 'P', 'C', 'V', 'Count')},
    'pyramid': {'class': 'PyramidNode', 'name': 'Pyramid', 'primary': 'G',
        'inputs': (*BOX_DIMENSIONS[:2], HEIGHT, BASE, PLANE, TYPE),
        'outputs': ('G', 'O', 'X', 'Y', 'H', 'P', 'Tip', 'V', 'S', 'Count')},
    'sphere': {'class': 'SphereNode', 'name': 'Sphere', 'primary': 'G',
        'inputs': (RADIUS, CENTER, PLANE), 'outputs': ('G', 'O', 'R', 'D', 'P', 'V', 'Count')},
    'ellipsoid': {'class': 'EllipsoidNode', 'name': 'Ellipsoid', 'primary': 'G',
        'inputs': (CurveInput('X', 'Radius X', 'number', 10.), CurveInput('Y', 'Radius Y', 'number', 7.),
                   CurveInput('Z', 'Radius Z', 'number', 5.), CENTER, PLANE, TYPE),
        'outputs': ('G', 'O', 'X', 'Y', 'Z', 'P', 'V', 'S', 'Count')},
    'torus': {'class': 'TorusNode', 'name': 'Torus', 'primary': 'G', 'inputs': (
        CurveInput('R', 'Major Radius', 'number', 20.), CurveInput('r', 'Minor Radius', 'number', 5.), CENTER, PLANE),
        'outputs': ('G', 'O', 'R', 'r', 'Out', 'In', 'P', 'N', 'V', 'Count')},
    'cylinder': {'class': 'CylinderNode', 'name': 'Cylinder', 'primary': 'G',
        'inputs': (RADIUS, HEIGHT, BASE, PLANE, TYPE),
        'outputs': ('G', 'O', 'R', 'H', 'P', 'D', 'Top', 'C', 'N', 'V', 'S', 'Count')},
    'cone': {'class': 'ConeNode', 'name': 'Cone', 'primary': 'G',
        'inputs': (RADIUS, HEIGHT, BASE, PLANE, TYPE),
        'outputs': ('G', 'O', 'R', 'H', 'P', 'D', 'Tip', 'N', 'V', 'S', 'Count')},
    'truncated_cone': {'class': 'TruncatedConeNode', 'name': 'Truncated Cone', 'primary': 'G',
        'inputs': (CurveInput('R', 'Base Radius', 'number', 10.),
                   CurveInput('r', 'Top Radius', 'number', 5.), HEIGHT, BASE, PLANE, TYPE),
        'outputs': ('G', 'O', 'R', 'r', 'H', 'P', 'Top', 'N', 'V', 'S', 'Count')},
    'paraboloid': {'class': 'ParaboloidNode', 'name': 'Paraboloid', 'primary': 'G',
        'inputs': (RADIUS, HEIGHT, VERTEX, PLANE),
        'outputs': ('G', 'O', 'R', 'H', 'P', 'D', 'Top', 'N', 'Count')},
}
SOLID_DIMENSION_PORTS = {kind: tuple(d.port for d in spec['inputs'] if d.kind == 'number')
                         for kind, spec in SOLID_SPECS.items()}


def truncated_cone_dimensions(base_radius, top_radius, height):
    base_radius, top_radius, height = map(finite, (base_radius, top_radius, height))
    if min(base_radius, top_radius) <= 1e-9:
        raise ValueError('Base Radius and Top Radius must be greater than 1e-9.')
    if abs(base_radius - top_radius) <= 1e-7:
        raise ValueError('Base Radius and Top Radius must differ. Use Cylinder for equal radii.')
    if abs(height) <= 1e-9:
        raise ValueError('Height must be nonzero.')
    return base_radius, top_radius, height


@dataclass(frozen=True)
class SolidValue:
    key: str
    kind: str
    frame: PlaneValue
    dimensions: tuple
    solid: bool = True

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key or len(self.key) > 256 or self.kind not in SOLID_SPECS:
            raise ValueError('Invalid 3D primitive recipe.')
        if not isinstance(self.frame, PlaneValue) or type(self.solid) is not bool:
            raise ValueError('Invalid primitive frame or Solid flag.')
        expected = len(SOLID_DIMENSION_PORTS[self.kind])
        values = tuple(finite(v) for v in self.dimensions)
        if len(values) != expected:
            raise ValueError('Invalid number of primitive dimensions.')
        if self.kind == 'truncated_cone':
            truncated_cone_dimensions(*values)
        elif self.kind == 'pyramid':
            if min(values[0], values[1], abs(values[2])) <= 1e-9:
                raise ValueError('Pyramid needs positive Width and Depth and nonzero Height.')
        elif min(values) <= 1e-9:
            raise ValueError('Primitive dimensions must be greater than 1e-9.')
        if self.kind == 'torus' and values[1] >= values[0]:
            raise ValueError('Torus Minor Radius must be smaller than Major Radius.')
        if (self.kind in ('box', 'box_from_center', 'sphere', 'torus') and not self.solid
                or self.kind == 'paraboloid' and self.solid):
            raise ValueError('This primitive does not support the requested Solid/Shell mode.')
        object.__setattr__(self, 'dimensions', values)

    @property
    def volume(self):
        if not self.solid:
            return 0.
        values = self.dimensions
        if self.kind in ('box', 'box_from_center'):
            result = math.prod(values)
        elif self.kind == 'pyramid':
            result = abs(math.prod(values))/3
        elif self.kind == 'sphere':
            result = 4*math.pi*values[0]**3/3
        elif self.kind == 'ellipsoid':
            result = 4*math.pi*math.prod(values)/3
        elif self.kind == 'torus':
            result = 2*math.pi**2*values[0]*values[1]**2
        elif self.kind == 'truncated_cone':
            base, top, height = values
            result = math.pi*abs(height)*(base**2 + base*top + top**2)/3
        else:
            result = math.pi*values[0]**2*values[1]/(3 if self.kind == 'cone' else 1)
        return finite_number(result)

    def to_wire(self):
        return {'key': self.key, 'kind': self.kind, 'plane': self.frame.to_wire(),
                'dimensions': list(self.dimensions), 'solid': self.solid}


def solid_from_wire(data):
    if not isinstance(data, dict) or not isinstance(data.get('plane'), dict) or not isinstance(data.get('dimensions'), (list, tuple)):
        raise ValueError('Invalid 3D geometry recipe.')
    return SolidValue(data.get('key'), data.get('kind'), PlaneValue(**data['plane']), tuple(data['dimensions']), data.get('solid'))


def normalize_solid_state(operation, data):
    return normalize_curve_state(operation, data, spec=SOLID_SPECS[operation], decoder=solid_from_wire)


def evaluate_solid(operation, parameters, inputs):
    state = normalize_solid_state(operation, parameters)
    if state['mode'] == 'reference':
        if parameters.get('reference_error'):
            raise ValueError(parameters['reference_error'])
        if not state['references']:
            raise ValueError('Select native objects in Serpentine, then click Set reference.')
        values = tuple(solid_from_wire(r['recipe']) for r in state['references'])
        tree = topology(DataTree((Branch((0,), values, tuple(v.key for v in values)),)), state['tree_modes'].get('References', 'none'))
    else:
        spec = SOLID_SPECS[operation]
        trees = matched_inputs([input_tree(inputs.get(d.port, state['parameters'][d.port]), d,
            state['tree_modes'].get(d.port, 'none'), d.port not in inputs) for d in spec['inputs']])
        branches, occurrences = [], {}
        for path, rows in aligned(*trees):
            widths = [len((next((b for b in t.branches if b.path == path), None) or t.branches[0]).items)
                      for t in trees if t.branches]
            if widths and any(w not in (0, 1, max(widths)) for w in widths):
                raise ValueError('3D primitive lists must have equal lengths or one item. Match the DataTree explicitly.')
            values = []
            for items, provenance in rows:
                args = dict(zip((d.port for d in spec['inputs']), items))
                signature = json.dumps(provenance)
                count = occurrences.get(signature, 0)
                occurrences[signature] = count+1
                key = hashlib.sha256(f'{signature}:{count}'.encode()).hexdigest()[:24]
                frame = args['P']
                origin = args['O'].xyz if 'O' in inputs else add(frame.origin, args['O'].xyz)
                dimensions = tuple(args[p] for p in SOLID_DIMENSION_PORTS[operation])
                values.append(SolidValue(key, operation, PlaneValue(origin, frame.axis_x, frame.normal), dimensions,
                                         args.get('S', operation != 'paraboloid')))
            branches.append(Branch(path, tuple(values), tuple(v.key for v in values)))
        tree = DataTree(tuple(branches))
    def mapped(fn):
        return DataTree(tuple(Branch(b.path, tuple(fn(v) for v in b.items), b.keys) for b in tree.branches))
    def point(v, suffix, xyz):
        return PointValue(v.key+':'+suffix, xyz)
    def axial(v, factor=1):
        return add(v.frame.origin, scale(v.frame.normal, v.dimensions[-1]*factor))
    output = {'G': tree, 'Count': tree.count, 'O': mapped(lambda v: point(v, 'origin', v.frame.origin)),
              'P': mapped(lambda v: v.frame), 'N': mapped(lambda v: VectorValue(v.frame.normal)),
              'V': mapped(lambda v: v.volume), 'S': mapped(lambda v: v.solid)}
    if operation in ('box', 'box_from_center', 'pyramid', 'ellipsoid'):
        for i, port in enumerate(SOLID_DIMENSION_PORTS[operation]):
            output[port] = mapped(lambda v, i=i: v.dimensions[i])
    if operation == 'box':
        output['C'] = mapped(lambda v: point(v, 'center', add(v.frame.origin,
            add(scale(v.frame.axis_x, v.dimensions[0]/2), add(scale(v.frame.axis_y, v.dimensions[1]/2), scale(v.frame.normal, v.dimensions[2]/2))))))
    elif operation == 'box_from_center':
        output['C'] = mapped(lambda v: point(v, 'center', axial(v, .5)))
    elif operation == 'pyramid':
        output['Tip'] = mapped(lambda v: point(v, 'tip', axial(v)))
    elif operation == 'truncated_cone':
        output.update(R=mapped(lambda v: v.dimensions[0]), r=mapped(lambda v: v.dimensions[1]),
                      H=mapped(lambda v: v.dimensions[-1]), Top=mapped(lambda v: point(v, 'top', axial(v))),
                      N=mapped(lambda v: VectorValue(scale(v.frame.normal, math.copysign(1., v.dimensions[-1])))))
    elif operation != 'ellipsoid':
        output['R'] = mapped(lambda v: v.dimensions[0])
        output['D'] = mapped(lambda v: 2*v.dimensions[0])
        if operation == 'torus':
            output.update(r=mapped(lambda v: v.dimensions[1]), Out=mapped(lambda v: sum(v.dimensions)),
                          In=mapped(lambda v: v.dimensions[0]-v.dimensions[1]))
        elif operation != 'sphere':
            output['H'] = mapped(lambda v: v.dimensions[1])
            output['Top' if operation != 'cone' else 'Tip'] = mapped(lambda v: point(v, 'top', axial(v)))
            output['C'] = mapped(lambda v: point(v, 'center', axial(v, .5)))
    return {p: output[p] for p in SOLID_SPECS[operation]['outputs']}


def solid_object_from_outputs(parameters, outputs):
    return ParametricObject(parameters['project_uuid'], parameters['node_uuid'], outputs['G'], parameters['mode'],
        tuple((r['key'], r['id']) for r in parameters.get('references', [])), kind='solids')


def solid_object_from_wire(data):
    return curve_object_from_wire(data, decoder=solid_from_wire, kind='solids')
