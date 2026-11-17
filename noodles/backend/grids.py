"""Compact grid recipes, shared topology and DataTree outputs; no OCC or Qt."""
from dataclasses import dataclass
from collections import OrderedDict
import hashlib
import json
import math

from .curves import (CurveInput, PlaneValue, input_tree, normalize_curve_state,
                     matched_inputs, add, line, arc, curve_object_from_wire)
from .datatree import Branch, DataTree, MAX_ITEMS, aligned, finite, flip_matrix, topology as tree_mode
from .point import PointValue
from .parametric import ParametricObject
from .grid_topology import topology
from .wires import WireValue

PLANE = CurveInput('P','Plane / Normal','plane','XY')
ORIGIN = CurveInput('O','Origin','center',(0.,0.,0.))
SIZE = CurveInput('S','Edge Size','number',10.)
EX = CurveInput('Ex','Cells X','grid_count',4)
EY = CurveInput('Ey','Cells Y','grid_count',3)
POINT_GROUPINGS = ('flat', 'rows', 'columns')
GRID_SPECS = {
    'grid_rectangle': {'class':'GridRectangleNode','name':'Grid Rectangle','inputs':(
        PLANE,CurveInput('Sx','Size X','number',10.),CurveInput('Sy','Size Y','number',10.),EX,EY,ORIGIN),
        'outputs':('G','C','P','E','NC','NP','Count')},
    'grid_triangle': {'class':'GridTriangleNode','name':'Grid Triangle','inputs':(PLANE,SIZE,EX,EY,ORIGIN),
        'outputs':('G','C','P','V','E','NC','NP','Count')},
    'grid_hexagon': {'class':'GridHexagonNode','name':'Grid Hexagon','inputs':(PLANE,SIZE,EX,EY,ORIGIN),
        'outputs':('G','C','P','V','E','NC','NP','Count')},
    'grid_radial': {'class':'GridRadialNode','name':'Grid Radial','inputs':(PLANE,
        CurveInput('S','Ring Spacing','number',10.),CurveInput('Er','Radial Cells','grid_count',4),
        CurveInput('Ep','Polar Cells','polar_count',8),ORIGIN),
        'outputs':('G','C','P','E','R','A','NC','NP','Count')},
}
for _spec in GRID_SPECS.values():
    _spec['primary'] = 'G'


def integer(value, minimum=1):
    value = finite(value)
    if value != int(value) or not minimum <= value <= MAX_ITEMS:
        raise ValueError(f'Grid cell counts must be integers from {minimum} to {MAX_ITEMS}.')
    return int(value)


@dataclass(frozen=True)
class GridValue:
    key: str
    kind: str
    frame: PlaneValue
    spacing: tuple
    extents: tuple

    def __post_init__(self):
        if not isinstance(self.key,str) or not self.key or len(self.key)>200 or self.kind not in GRID_SPECS or not isinstance(self.frame,PlaneValue):
            raise ValueError('Invalid grid recipe.')
        spacing = tuple(finite(v) for v in self.spacing)
        if len(spacing) != (2 if self.kind=='grid_rectangle' else 1) or min(spacing)<=1e-8:
            raise ValueError('Grid spacing must be greater than 1e-8.')
        if len(self.extents)!=2:
            raise ValueError('A grid requires two cell counts.')
        ex,ey = integer(self.extents[0]),integer(self.extents[1],3 if self.kind=='grid_radial' else 1)
        object.__setattr__(self,'spacing',spacing)
        object.__setattr__(self,'extents',(ex,ey))
        if max(self.counts)>MAX_ITEMS:
            raise ValueError(f'Grid exceeds the {MAX_ITEMS}-item output limit. Reduce cell counts.')
        # Validate the entire geometric envelope before allocating topology/OCC.
        sx,sy = spacing if len(spacing)==2 else (spacing[0],spacing[0])
        bounds = ((0,ex*sx,0,ey*sy) if self.kind=='grid_rectangle' else
                  (0,(ex+.5*ey)*sx,0,math.sqrt(3)*.5*ey*sy) if self.kind=='grid_triangle' else
                  (-sx,(1.5*(ex-1)+1)*sx,-math.sqrt(3)*.5*sy,math.sqrt(3)*(ey+.5*(ex-1))*sy) if self.kind=='grid_hexagon' else
                  (-ex*sx,ex*sx,-ex*sy,ex*sy))
        for x in bounds[:2]:
            for y in bounds[2:]:
                self.frame.at(x,y)

    @property
    def counts(self):
        """Cells, all published points (vertices + centres), unique edges."""
        x,y=self.extents
        if self.kind=='grid_radial':
            return x*y,1+x*y,2*x*y
        if self.kind=='grid_hexagon':
            return x*y,3*x*y+2*x+2*y,3*x*y+2*x+2*y-1
        cells=x*y*(2 if self.kind=='grid_triangle' else 1)
        return cells,(x+1)*(y+1)+(cells if self.kind=='grid_triangle' else 0),x*(y+1)+y*(x+1)+(x*y if self.kind=='grid_triangle' else 0)

    def to_wire(self):
        return {'key':self.key,'kind':self.kind,'plane':self.frame.to_wire(),
                'spacing':list(self.spacing),'extents':list(self.extents)}


def grid_from_wire(data):
    if not isinstance(data,dict) or not isinstance(data.get('plane'),dict) or not isinstance(data.get('spacing'),(list,tuple)) or not isinstance(data.get('extents'),(list,tuple)):
        raise ValueError('Invalid grid recipe.')
    return GridValue(data.get('key'),data.get('kind'),PlaneValue(**data['plane']),tuple(data['spacing']),tuple(data['extents']))


def normalize_grid_state(operation,data):
    state=normalize_curve_state(operation,data,spec=GRID_SPECS[operation],decoder=grid_from_wire)
    grouping = data.get('parameters', {}).get('point_grouping', 'rows')
    if grouping not in POINT_GROUPINGS:
        raise ValueError('Unknown grid point grouping.')
    state['parameters']['point_grouping'] = grouping
    for raw, ref in zip(data.get('references', []), state['references']):
        path = tuple(raw.get('path', (0,)))
        Branch(path, ())
        if '/' not in ref['key']:
            raise ValueError('Invalid grid reference slot.')
        ref['path'] = list(path)
    return state


def members(value, *, cells=True, cooperate=False):
    """Typed points, canonical edges and exact cell wires shared by both hosts."""
    vertices,edge_defs,cell_defs,centres=topology(value.kind,*value.extents)
    sx,sy=value.spacing if len(value.spacing)==2 else (value.spacing[0],)*2
    def point(role,xy):
        return PointValue(value.key+':'+role,value.frame.at(xy[0]*sx,xy[1]*sy))
    import time
    deadline=time.perf_counter()+.003
    def checkpoint():
        nonlocal deadline
        if cooperate and time.perf_counter()>=deadline:
            time.sleep(.001)
            deadline=time.perf_counter()+.003
    points,center_points={},{}
    for records,destination in ((vertices,points),(centres,center_points)):
        for role,(xy,_) in records.items():
            destination[role]=point(role,xy)
            checkpoint()
    edges={}
    for role,(a,b,path,is_arc) in edge_defs.items():
        key=value.key+':'+role
        if is_arc:
            _,r,index=role.split(':')
            radius=int(r)*sx
            start=math.tau*int(index)/value.extents[1]
            # Use the same lattice endpoints, including the angular seam.
            midpoint=value.frame.at(radius*math.cos(start+math.pi/value.extents[1]),radius*math.sin(start+math.pi/value.extents[1]))
            edges[role]=arc(key,points[a].xyz,midpoint,points[b].xyz)
        else:
            edges[role]=line(key,points[a].xyz,points[b].xyz)
        checkpoint()
    boundaries={}
    if cells:
        for role,corners,boundary,path in cell_defs:
            boundaries[role]=WireValue(value.key+':'+role,'wire',(),frame=value.frame,closed=True,
                segments=tuple(edges[e] for e,_ in boundary),reversed_edges=tuple(r for _,r in boundary))
            checkpoint()
    return vertices,edge_defs,cell_defs,centres,points,center_points,edges,boundaries


def grid_reference_tree(state):
    refs = state['references']
    owners = dict.fromkeys(r['key'].split('/', 1)[0] for r in refs)
    groups = {}
    for index, key in enumerate(owners):
        owners[key] = index
    for ref in refs:
        owner = ref['key'].split('/', 1)[0]
        path = tuple(ref['path'])
        if len(owners) > 1:
            path = (owners[owner],) + path
        groups.setdefault(path, []).append(grid_from_wire(ref['recipe']))
    tree = DataTree(tuple(Branch(path, tuple(items), tuple(v.key for v in items)) for path, items in groups.items()))
    return tree_mode(tree, state['tree_modes'].get('References', 'none'))


def point_branches(kind, grouping, records, points):
    if grouping == 'flat':
        yield (), points.values()
        return
    rows = {}
    for role, (_, path) in records.items():
        rows.setdefault(path, []).append(points[role])
    if grouping == 'rows':
        yield from rows.items()
        return
    if kind == 'grid_radial':
        # The centre belongs to the grid once. Transpose the remaining rings
        # to make one branch per angular direction, ordered outwards.
        yield (0,), rows.pop((0,))
        offset = 1
    else:
        offset = 0
    columns = flip_matrix(DataTree(tuple(Branch(path, items) for path, items in rows.items())))
    for index, branch in enumerate(columns.branches, offset):
        yield (index,), branch.items


def evaluate_grid(operation,parameters,inputs):
    state=normalize_grid_state(operation,parameters)
    spec=GRID_SPECS[operation]
    if state['mode'] == 'reference':
        if parameters.get('reference_error'):
            raise ValueError(parameters['reference_error'])
        if not state['references']:
            raise ValueError('Select matching native grids, then click Set reference.')
        grid_tree = grid_reference_tree(state)
        if any(sum(v.counts[i] for v in grid_tree.values()) > MAX_ITEMS for i in range(3)):
            raise ValueError('Combined grids exceed output limit.')
    else:
        trees=matched_inputs([input_tree(inputs.get(d.port,state['parameters'][d.port]),d,
            state['tree_modes'].get(d.port,'none'),d.port not in inputs) for d in spec['inputs']])
        branches,occurrences=[],{}
        total=[0,0,0]
        for path,rows in aligned(*trees):
            widths=[len((next((b for b in t.branches if b.path==path),None) or t.branches[0]).items) for t in trees if t.branches]
            if widths and any(w not in (0,1,max(widths)) for w in widths):
                raise ValueError('Grid lists must have equal lengths or one item. Match the DataTree explicitly.')
            values=[]
            for items,provenance in rows:
                args=dict(zip((d.port for d in spec['inputs']),items))
                sig=json.dumps(provenance)
                count=occurrences.get(sig,0)
                occurrences[sig]=count+1
                key=hashlib.sha256(f'{sig}:{count}'.encode()).hexdigest()[:24]
                frame=args['P']
                origin=args['O'].xyz if 'O' in inputs else add(frame.origin,args['O'].xyz)
                spacing=tuple(args[p] for p in (('Sx','Sy') if operation=='grid_rectangle' else ('S',)))
                extents=tuple(args[p] for p in (('Er','Ep') if operation=='grid_radial' else ('Ex','Ey')))
                value=GridValue(key,operation,PlaneValue(origin,frame.axis_x,frame.normal),spacing,extents)
                total=[a+b for a,b in zip(total,value.counts)]
                if max(total)>MAX_ITEMS:
                    raise ValueError(f'Combined grids exceed the {MAX_ITEMS}-item output limit.')
                values.append(value)
            branches.append(Branch(path,tuple(values),tuple(v.key for v in values)))
        grid_tree=DataTree(tuple(branches))
    result={p:OrderedDict() for p in spec['outputs'] if p not in ('G','Count','NC','NP')}
    def append(port,path,value):
        result[port].setdefault(path,[]).append(value)
    for branch in grid_tree.branches:
        for index,value in enumerate(branch.items):
            # Preserve input identity/path when multiple grid slots are expanded.
            prefix=() if len(grid_tree.branches)==1 and branch.path==(0,) and len(branch.items)==1 else branch.path+(index,)
            vertices,edge_defs,cell_defs,centres,points,center_points,edges,boundaries=members(value)
            if centres:
                for role, (_, path) in vertices.items():
                    append('V', prefix + path, points[role])
            for path, items in point_branches(operation, state['parameters']['point_grouping'],
                                             centres or vertices, center_points if centres else points):
                result['P'].setdefault((prefix + path) or (0,), []).extend(items)
            for role,(_,_,path,is_arc) in edge_defs.items():
                append('E',prefix+path,edges[role])
                if operation=='grid_radial':
                    append('A' if is_arc else 'R',prefix+(path[1],),edges[role])
            for role,_,_,path in cell_defs:
                append('C',prefix+path,boundaries[role])
    outputs={p:DataTree(tuple(Branch(path,tuple(items),tuple(v.key for v in items)) for path,items in groups.items())) for p,groups in result.items()}
    outputs.update(G=grid_tree,Count=grid_tree.count)
    for port,i in (('NC',0),('NP',1)):
        outputs[port]=DataTree(tuple(Branch(b.path,tuple(v.counts[i] for v in b.items),b.keys) for b in grid_tree.branches))
    return {p:outputs[p] for p in spec['outputs']}


def grid_object_from_outputs(parameters,outputs):
    return ParametricObject(parameters['project_uuid'],parameters['node_uuid'],outputs['G'],parameters['mode'],
        tuple((r['key'], r['id']) for r in parameters.get('references', [])), kind='grids')


def grid_object_from_wire(data):
    model=curve_object_from_wire(data,decoder=grid_from_wire,kind='grids')
    if any(sum(v.counts[i] for v in model.parts.values())>MAX_ITEMS for i in range(3)):
        raise ValueError('Combined grids exceed output limit.')
    return model
