"""Deferred area and volume measurements with separate centroids."""
import math

from .arithmetic import finite_number
from .curves import CurveInput, input_tree, normalize_curve_state
from .datatree import Branch, DataTree, MAX_ITEMS
from .point import PointValue
from .pull import request_signature
from .splines import PendingGeometry


MASS_SPECS = {
    'area': {'class': 'AreaNode', 'name': 'Area', 'category': 'Operations', 'reference': False,
             'inputs': (CurveInput('G', 'Breps or Closed Planar Curves', 'geometry'),),
             'outputs': ('A', 'C'), 'primary': 'A'},
    'volume': {'class': 'VolumeNode', 'name': 'Volume', 'category': 'Operations', 'reference': False,
               'inputs': (CurveInput('G', 'Closed Solid Breps', 'boolean_solid'),),
               'outputs': ('V', 'C'), 'primary': 'V'},
}


def normalize_state(operation, data):
    state = normalize_curve_state(operation, data, spec=MASS_SPECS[operation])
    if state['mode'] != 'generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Connect geometry to measure it.')
    return state


def evaluate(operation, parameters, inputs):
    state = normalize_state(operation, parameters)
    spec = MASS_SPECS[operation]
    tree = input_tree(inputs['G'], spec['inputs'][0], state['tree_modes'].get('G', 'none'))
    sources = list(dict.fromkeys(tree.values()))
    plan = {'operation': operation, 'sources': [source.to_wire() for source in sources]}
    signature = request_signature(plan)
    detail = parameters.get('sampling_details') or {}
    port = spec['primary']
    pending = PendingGeometry(f'Waiting for native {operation} measurements')
    if sources and detail.get('signature') != signature:
        preview = DataTree(tuple(Branch(b.path, (pending,) * len(b.items), b.keys) for b in tree.branches))
        return {port: preview, 'C': preview, '_sampling': {'project_uuid': state['project_uuid'],
                'node_uuid': state['node_uuid'], 'signature': signature, 'plan': plan}}
    if sources and detail.get('error'):
        raise ValueError(detail['error'])
    values = dict(zip(sources, detail.get('values', []) if sources else (), strict=True))
    measures, centers = [], []
    for branch in tree.branches:
        rows = [values[value] for value in branch.items]
        measures.append(Branch(branch.path, tuple(finite_number(row[0]) for row in rows), branch.keys))
        centers.append(Branch(branch.path, tuple(PointValue(key, row[1]) for key, row in zip(branch.keys, rows)),
                              branch.keys))
    return {port: DataTree(tuple(measures)), 'C': DataTree(tuple(centers))}


def measure(plan, wanted, cache):
    from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_Shell, BRepCheck_Status
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Iterator
    from serpentine3d.core import geometry as g, occ
    from .moves import geometry_from_wire
    from .scene_curves import materialize

    operation, sources = plan.get('operation'), plan.get('sources')
    if operation not in MASS_SPECS or not isinstance(sources, list) or len(sources) > MAX_ITEMS:
        raise ValueError('Invalid mass properties request.')
    shapes, budget = {}, [MAX_ITEMS]

    def resolve(value):
        if value not in shapes:
            shapes[value] = materialize(value, resolve=resolve, topology_cache=cache)
        return shapes[value]

    def components(shape):
        if shape.ShapeType() not in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
            yield shape
            return
        children = TopoDS_Iterator(shape)
        while children.More():
            yield from components(children.Value())
            children.Next()

    def properties(part):
        kind = g.shape_kind(part)
        if operation == 'volume':
            if kind != 'solid' or not BRepCheck_Analyzer(part).IsValid():
                raise ValueError('Volume needs a valid closed solid BREP.')
            shells = TopExp_Explorer(part, TopAbs_SHELL)
            while shells.More():
                if BRepCheck_Shell(TopoDS.Shell_s(shells.Current())).Closed() != BRepCheck_Status.BRepCheck_NoError:
                    raise ValueError('Volume needs a valid closed solid BREP.')
                shells.Next()
            props = occ.volume_properties(part)
        else:
            if kind == 'curve' and g.is_closed_curve(part):
                part = g.planar_face(g.copy_shape(part))
            elif kind not in ('surface', 'solid'):
                raise ValueError('Area needs a BREP or a closed planar curve.')
            props = occ.surface_properties(part)
        mass = abs(finite_number(props.Mass()))
        if mass == 0:
            raise ValueError(f'{MASS_SPECS[operation]["name"]} found zero measure.')
        return mass, g.pnt_tuple(props.CentreOfMass())

    output = []
    for source in sources:
        if not wanted():
            return []
        shape = resolve(geometry_from_wire(source, budget=budget))
        rows = [properties(part) for part in components(shape)]
        mass = finite_number(math.fsum(size for size, _ in rows))
        if mass == 0:
            raise ValueError('Cannot measure an empty BREP.')
        centroid = tuple(math.fsum(size/mass * center[i] for size, center in rows) for i in range(3))
        output.append((mass, centroid))
    return output
