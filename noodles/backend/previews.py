"""Viewport helpers are data, never ParametricObject or SceneObject geometry."""
from dataclasses import dataclass
import hashlib
import json
import math
from .curves import CurveInput, PlaneValue, xyz, input_tree, normalize_curve_state, matched_inputs
from .arithmetic import VectorValue
from .datatree import Branch, DataTree, aligned
from .pull import request_signature
from .surface_uv import FACE_INDEX, SURFACE, _match, surface_selection
from .annotations import ANNOTATION_COLOR, ANNOTATIONS, DIMENSION, TEXT_TAG, build_annotation

MAX_PREVIEWS=256
UV_GRID_PREVIEW = 'surface_uv_preview'
HIDE = 'hide'
MAX_UV_GRIDS = 16
MAX_UV_GRID_DIVISIONS = 32
MAX_UV_GRID_VERTICES = 6000
ANNOTATION_STYLE = (CurveInput('C', 'Color', 'color', ANNOTATION_COLOR),
                    CurveInput('H', 'Text Size (Pixels)', 'number', 14.),
                    CurveInput('S', 'Visible', 'boolean', True))
PREVIEW_SPECS={
    HIDE: {'class': 'HideNode', 'name': 'Hide', 'primary': 'Count', 'reference': False, 'preview': True,
           'inputs': (CurveInput('G', 'Geometry to Hide', 'items', optional=True),), 'outputs': ()},
    'vector_preview':{'class':'VectorPreviewNode','name':'Vector Preview','primary':'V',
        'reference':False,'preview':True,'inputs':(
            CurveInput('O','Origin','point',(0.,0.,0.)),
            CurveInput('V','Vector','vector'),CurveInput('S','Visible','boolean',True)),
        'outputs':('V','L','Count')},
    'plane_preview': {'class':'PlanePreviewNode', 'name':'Plane Preview', 'primary':'P',
        'reference':False, 'preview':True, 'inputs':(
            CurveInput('P','Plane','plane'), CurveInput('W','Width','number',100.),
            CurveInput('H','Height','number',100.), CurveInput('D','Spacing','number',1.),
            CurveInput('S','Visible','boolean',True)),
        'outputs':('P','S','Count')},
    UV_GRID_PREVIEW: {'class': 'ReparameterizeSurfacePreviewNode', 'name': 'Reparameterize Surface Preview',
        'reference': False, 'preview': True, 'primary': 'Count', 'inputs': (
            SURFACE, CurveInput('U', 'U Divisions', 'uv_grid_count', 8),
            CurveInput('V', 'V Divisions', 'uv_grid_count', 8), FACE_INDEX,
            CurveInput('E', 'Visible', 'boolean', True)),
        'outputs': ('Count',)},
    TEXT_TAG: {'class': 'TextTagNode', 'name': 'Text Tag', 'primary': 'T', 'reference': False,
               'preview': True, 'inputs': (CurveInput('P', 'Anchor Points', 'points'),
                    CurveInput('T', 'Label Text or Number', 'label_text', 'Tag'), *ANNOTATION_STYLE),
               'outputs': ('T', 'Count')},
    DIMENSION: {'class': 'DimensionNode', 'name': 'Dimension', 'primary': 'L', 'reference': False,
                'preview': True, 'inputs': (CurveInput('A', 'Start Point', 'points'),
                    CurveInput('B', 'End Point', 'points'), CurveInput('O', 'Offset Vector', 'vector', (0., 10., 0.)),
                    CurveInput('T', 'Label Prefix', 'text', ''), *ANNOTATION_STYLE), 'outputs': ('L', 'Count')},
}


@dataclass(frozen=True)
class VectorPreviewValue:
    key:str
    origin:tuple
    vector:tuple
    visible:bool

    def to_wire(self):
        return {'key':self.key,'kind':'vector','origin':list(self.origin),
                'vector':list(self.vector),'visible':self.visible}


@dataclass(frozen=True)
class PlanePreviewValue:
    key: str
    frame: PlaneValue
    width: float
    height: float
    spacing: float
    visible: bool

    def __post_init__(self):
        from .datatree import finite
        w, h, step = map(finite, (self.width, self.height, self.spacing))
        if min(w, h, step) <= 0 or max(w, h) > step*200:
            raise ValueError('Plane Preview needs positive sizes and at most 200 grid intervals per axis.')
        for x in (-w/2, w/2):
            for y in (-h/2, h/2):
                self.frame.at(x, y)

    def to_wire(self):
        return {'key': self.key, 'kind': 'plane', 'plane': self.frame.to_wire(),
                'width': self.width, 'height': self.height, 'spacing': self.spacing,
                'visible': self.visible}


def normalize_preview_state(operation,data):
    state=normalize_curve_state(operation,data,spec=PREVIEW_SPECS[operation])
    if state['mode']!='generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Viewport previews do not support native references.')
    return state


def evaluate_preview(operation,parameters,inputs):
    state=normalize_preview_state(operation,parameters)
    spec=PREVIEW_SPECS[operation]
    if operation == HIDE:
        return evaluate_hide(state, inputs, {})
    trees=[input_tree(inputs.get(d.port,state['parameters'].get(d.port)),d,
        state['tree_modes'].get(d.port,'none'),d.port not in inputs) for d in spec['inputs']]
    if operation == UV_GRID_PREVIEW:
        return evaluate_uv_grid(state, trees, parameters.get('sampling_details') or {})
    trees=matched_inputs(trees)
    records=[]
    total=0
    occurrences={}
    for path,rows in aligned(*trees):
        widths=[len((next((b for b in t.branches if b.path==path),None) or t.branches[0]).items) for t in trees if t.branches]
        if widths and any(w not in (0,1,max(widths)) for w in widths):
            raise ValueError('Preview lists must have equal lengths or one item. Match the DataTree explicitly.')
        values=[]
        for items,provenance in rows:
            total+=1
            if total>MAX_PREVIEWS:
                raise ValueError(f'{spec["name"]} supports up to {MAX_PREVIEWS} items per node.')
            signature=json.dumps(provenance)
            occurrence=occurrences.get(signature,0)
            occurrences[signature]=occurrence+1
            key=hashlib.sha256(f'{signature}:{occurrence}'.encode()).hexdigest()[:24]
            if operation in ANNOTATIONS:
                values.append(build_annotation(operation, key, items))
            elif operation == 'plane_preview':
                values.append(PlanePreviewValue(key, *items))
            else:
                origin,vector,visible=items
                length=math.hypot(*vector.xyz)
                if length<1e-12 or not math.isfinite(length):
                    raise ValueError('Vector Preview needs a nonzero finite Vector.')
                xyz(tuple(a+b for a,b in zip(origin.xyz,vector.xyz)))
                values.append(VectorPreviewValue(key,origin.xyz,vector.xyz,visible))
        records.append(Branch(path,tuple(values),tuple(v.key for v in values)))
    tree=DataTree(tuple(records))
    def mapped(fn):
        return DataTree(tuple(Branch(b.path,tuple(fn(v) for v in b.items),b.keys) for b in tree.branches))
    if operation == 'plane_preview':
        return {'P': mapped(lambda v: v.frame), 'S': mapped(lambda v: v.visible), 'Count': tree.count, '_preview': tree}
    if operation == TEXT_TAG:
        return {'T': mapped(lambda v: v.text), 'Count': tree.count, '_preview': tree}
    if operation == DIMENSION:
        return {'L': mapped(lambda v: v.length), 'Count': tree.count, '_preview': tree}
    return {'V':mapped(lambda v:VectorValue(v.vector)), 'L':mapped(lambda v:math.hypot(*v.vector)),
            'Count':tree.count,'_preview':tree}


def preview_payload(parameters,outputs):
    return {'project_uuid':parameters['project_uuid'],'node_uuid':parameters['node_uuid'],
            'items': outputs['_uv_grid'] if '_uv_grid' in outputs else
                     [v.to_wire() for v in outputs['_preview'].values()]}


def evaluate_hide(state, inputs, bindings):
    from .booleans import visibility_targets
    from .mesh_nodes import MeshValue
    from .moves import is_geometry

    if 'G' not in inputs:
        return {'Count': 0, '_hide_targets': ()}
    tree = input_tree(inputs['G'], PREVIEW_SPECS[HIDE]['inputs'][0], state['tree_modes'].get('G', 'none'))
    values = tree.values()
    if any((not is_geometry(value) and not isinstance(value, MeshValue)) or value.key not in bindings
           for value in values):
        raise ValueError('Connect geometry published or referenced in Serpentine.')
    targets = visibility_targets(bindings[value.key] for value in values)
    return {'Count': len(targets), '_hide_targets': targets}


def evaluate_uv_grid(state, trees, details):
    sources, rows = {}, []
    for _, items in _match(*trees):
        for (surface, u, v, face, visible), _ in items:
            if visible and (u > 1 or v > 1):
                source, face = surface_selection(surface, face)
                rows.append({'source': sources.setdefault(source, len(sources)), 'face': face, 'u': u, 'v': v})
    if len(rows) > MAX_UV_GRIDS:
        raise ValueError(f'Surface Preview supports up to {MAX_UV_GRIDS} visible grids per node.')
    outputs = {'Count': len(rows), '_uv_grid': []}
    if not rows:
        return outputs
    plan = {'sources': [source.to_wire() for source in sources], 'rows': rows}
    signature = request_signature(plan)
    if details.get('signature') != signature:
        outputs['_sampling'] = {'project_uuid': state['project_uuid'], 'node_uuid': state['node_uuid'],
                                 'signature': signature, 'plan': plan}
    elif details.get('error'):
        raise ValueError(details['error'])
    else:
        values = details['values']
        if len(values) != len(rows):
            raise ValueError('Surface Preview received incomplete geometry.')
        outputs['_uv_grid'] = [{'key': str(index), 'kind': 'uv_grid', 'visible': True, 'u': u, 'v': v}
                               for index, (u, v) in enumerate(values)]
    return outputs
