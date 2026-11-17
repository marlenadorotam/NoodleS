"""Typed translations and explicit ownership for in-place Move and copying Move GH."""
from dataclasses import dataclass,replace
import hashlib
import json
import math
from .curves import CurveInput,CurveValue,PlaneValue,add,cross,dot,scale,sub,unit,normalize_curve_state,input_tree,matched_inputs
from .point import PointValue
from .arithmetic import VectorValue
from .datatree import Branch,DataTree,aligned,finite
from .parametric import ParametricObject
from .rigid_motion import IDENTITY, IDENTITY_AXES, RigidMotion, from_wire as rigid_from_wire, orient_frames, reflection, rotation, uniform_scale

MOVE_AXES = ('X', 'Y', 'Z')

MOVE_SPECS={
    'move':{'class':'MoveNode','name':'Move','primary':'G','reference':False,'inputs':(
        CurveInput('G','Geometry','move_geometry'),CurveInput('X','Translation X','number',0.),
        CurveInput('Y','Translation Y','number',0.),CurveInput('Z','Translation Z','number',0.),
        CurveInput('W','World Coordinates','boolean',True),
        CurveInput('T','Translation Vector','vector',optional=True)), 'outputs':('G','X','Y','Z','Count')},
    'move_gh':{'class':'MoveGHNode','name':'Move GH','primary':'G','reference':False,'inputs':(
        CurveInput('G','Geometry','move_geometry'),CurveInput('T','Translation Vector','vector',(0.,0.,0.))),
        'outputs':('G','X','Count')},
    'rotate': {'class': 'RotateNode', 'name': 'Rotate', 'primary': 'G', 'reference': False, 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'), CurveInput('C', 'Center', 'point', (0., 0., 0.)),
        CurveInput('P', 'Rotation Plane', 'plane', 'XY'), CurveInput('A', 'Angle (Degrees)', 'number', 0.),
        CurveInput('To', 'Target Point', 'point', optional=True), CurveInput('Cp', 'Copy', 'boolean', False)),
        'outputs': ('G', 'A', 'Count')},
    'scale': {'class': 'ScaleNode', 'name': 'Scale', 'primary': 'G', 'reference': False, 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'), CurveInput('C', 'Center', 'point', (0., 0., 0.)),
        CurveInput('F', 'Factor', 'number', 1.), CurveInput('To', 'Target Point', 'point', optional=True),
        CurveInput('Cp', 'Copy', 'boolean', False)), 'outputs': ('G', 'F', 'Count')},
    'mirror': {'class': 'MirrorNode', 'name': 'Mirror', 'primary': 'G', 'reference': False, 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'), CurveInput('S', 'Line Start', 'point', (0., 0., 0.)),
        CurveInput('E', 'Line End', 'point', (1., 0., 0.)), CurveInput('P', 'Work Plane', 'plane', 'XY'),
        CurveInput('K', 'Keep Original', 'boolean', False),
        CurveInput('M', 'Mirror Plane', 'plane', optional=True)), 'outputs': ('G', 'Count')},
    'orient': {'class': 'OrientNode', 'name': 'Orient', 'primary': 'G', 'reference': False, 'inputs': (
        CurveInput('G', 'Geometry', 'move_geometry'), CurveInput('A', 'Source Plane', 'plane', 'XY'),
        CurveInput('B', 'Target Plane', 'plane', 'XY')), 'outputs': ('G', 'X', 'Count')},
}


@dataclass(frozen=True)
class TranslationValue:
    vector:tuple

    @property
    def matrix(self):
        x,y,z=self.vector
        return ((1.,0.,0.,x),(0.,1.,0.,y),(0.,0.,1.,z),(0.,0.,0.,1.))


@dataclass(frozen=True)
class TranslatedValue:
    key:str
    source:object
    vector:tuple
    kind:str='translated'

    def __post_init__(self):
        if not isinstance(self.key,str) or not 0<len(self.key)<=256 or not is_geometry(self.source):
            raise ValueError('Invalid translated geometry.')
        object.__setattr__(self,'vector',tuple(finite(v) for v in VectorValue(self.vector).xyz))
        if self.depth>16 or self.complexity>10000:
            raise ValueError('Translated geometry exceeds the recipe budget.')

    @property
    def depth(self):
        return 1+getattr(self.source,'depth',0)

    @property
    def complexity(self):
        return 1+getattr(self.source,'complexity',1)

    def to_wire(self):
        return {'key':self.key,'kind':self.kind,'source':geometry_wire(self.source),'vector':list(self.vector)}


@dataclass(frozen=True)
class RigidValue:
    key: str
    source: object
    motion: RigidMotion
    kind = 'rigid_transform'

    def __post_init__(self):
        if not isinstance(self.key, str) or not 0 < len(self.key) <= 256 or not is_geometry(self.source):
            raise ValueError('Invalid transformed geometry.')
        if self.depth > 16 or self.complexity > 10000:
            raise ValueError('Transformed geometry exceeds the recipe budget.')

    @property
    def depth(self):
        return 1 + getattr(self.source, 'depth', 0)

    @property
    def complexity(self):
        return 1 + getattr(self.source, 'complexity', 1)

    def to_wire(self):
        return {'key': self.key, 'kind': self.kind, 'source': geometry_wire(self.source),
                'motion': self.motion.to_wire()}


@dataclass(frozen=True)
class GridEditValue:
    key:str
    source:object
    edits:tuple
    kind:str='grid_edit'

    def __post_init__(self):
        from .grids import GridValue
        if not isinstance(self.source,GridValue) or self.key!=self.source.key or len(self.edits)>20000:
            raise ValueError('Invalid grid movement recipe.')
        seen=set()
        normalized=[]
        for kind,role,change in self.edits:
            if kind not in ('point','edge') or not isinstance(role,str) or not 0<len(role)<=100 or (kind,role) in seen:
                raise ValueError('Invalid or duplicate moved grid member.')
            seen.add((kind,role))
            if isinstance(change, dict):
                change = rigid_from_wire(change.get('transform'))
            elif not isinstance(change, RigidMotion):
                change = tuple(finite(v) for v in VectorValue(change).xyz)
            normalized.append((kind, role, change))
        object.__setattr__(self,'edits',tuple(normalized))

    def to_wire(self):
        return {'key':self.key,'kind':self.kind,'source':self.source.to_wire(),
            'edits': [[kind, role, {'transform': v.to_wire()} if isinstance(v, RigidMotion) else list(v)]
                      for kind, role, v in self.edits]}


def is_geometry(value):
    from .solids import SolidValue
    from .grids import GridValue
    from .operations import OperationValue
    from .surface_reference import SurfaceReferenceValue
    return isinstance(value,(PointValue,CurveValue,SolidValue,GridValue,OperationValue,TranslatedValue,RigidValue,GridEditValue,SurfaceReferenceValue))


def geometry_wire(value):
    return {'key':value.key,'kind':'point','xyz':list(value.xyz)} if isinstance(value,PointValue) else value.to_wire()


def geometry_from_wire(data,depth=0,budget=None):
    from .geometry import recipe_from_wire
    from .operations import OPERATION_SPECS, operation_from_wire
    if not isinstance(data,dict) or depth>16:
        raise ValueError('Invalid nested movement recipe.')
    budget=[10000] if budget is None else budget
    if data.get('kind') in OPERATION_SPECS:
        return operation_from_wire(data, depth=depth, budget=budget)
    budget[0]-=1
    if budget[0]<0:
        raise ValueError('Movement recipe budget exceeded.')
    if data.get('kind')=='point':
        return PointValue(data.get('key'),data.get('xyz',()))
    if data.get('kind')=='translated':
        return TranslatedValue(data.get('key'),geometry_from_wire(data.get('source'),depth+1,budget),tuple(data.get('vector',())))
    if data.get('kind') == 'rigid_transform':
        return RigidValue(data.get('key'), geometry_from_wire(data.get('source'), depth+1, budget),
                          rigid_from_wire(data.get('motion')))
    if data.get('kind')=='grid_edit':
        source=geometry_from_wire(data.get('source'),depth+1,budget)
        edits=data.get('edits')
        if not isinstance(edits,list) or len(edits)>20000:
            raise ValueError('Invalid grid movements.')
        return GridEditValue(data.get('key'),source,tuple(edits))
    return recipe_from_wire(data)


def translate(value,vector,key=None):
    """Preserve mathematical types; only opaque operation results need a wrapper."""
    from .solids import SolidValue
    from .grids import GridValue
    from .wires import WireValue
    key=value.key if key is None else key
    frame=lambda p:PlaneValue(add(p.origin,vector),p.axis_x,p.normal)
    if isinstance(value,PointValue):
        return PointValue(key,add(value.xyz,vector))
    if isinstance(value,WireValue):
        return replace(value,key=key,frame=frame(value.frame),segments=tuple(
            translate(s,vector,key+':'+str(i)) for i,s in enumerate(value.segments)))
    if isinstance(value,CurveValue):
        return replace(value,key=key,points=tuple(add(p,vector) for p in value.points),frame=frame(value.frame))
    if isinstance(value,(SolidValue,GridValue)):
        return replace(value,key=key,frame=frame(value.frame))
    if isinstance(value,TranslatedValue):
        return replace(value,key=key,vector=add(value.vector,vector))
    if isinstance(value,RigidValue):
        return RigidValue(key,value.source,RigidMotion(offset=vector).after(value.motion))
    if is_geometry(value):
        return TranslatedValue(key,value,tuple(vector))
    raise ValueError('Move requires Point, Curve, Surface, Solid or Grid geometry.')


def transform_frame(frame, motion):
    directions = motion.directions
    axis_x = tuple(dot(row, frame.axis_x) for row in directions)
    axis_y = tuple(dot(row, frame.axis_y) for row in directions)
    return PlaneValue(motion.point(frame.origin), axis_x, cross(axis_x, axis_y))


def transform_geometry(value, motion, key):
    from .solids import SolidValue
    from .grids import GridValue
    from .wires import WireValue
    from .splines import SplineValue

    if motion.axes == IDENTITY_AXES:
        return translate(value, motion.offset, key)
    if isinstance(value, PointValue):
        return PointValue(key, motion.point(value.xyz))
    if isinstance(value, WireValue):
        return replace(value, key=key, frame=transform_frame(value.frame, motion),
                       segments=tuple(transform_geometry(seg, motion, key+':'+str(i))
                                      for i, seg in enumerate(value.segments)))
    factor = motion.factor
    if isinstance(value, SplineValue):
        length = value.measured_length
        return replace(value, key=key, points=tuple(motion.point(p) for p in value.points),
                       frame=transform_frame(value.frame, motion),
                       measured_length=length * factor if length is not None else None)
    if isinstance(value, CurveValue):
        return replace(value, key=key, points=tuple(motion.point(p) for p in value.points),
                       frame=transform_frame(value.frame, motion), radius=value.radius*factor,
                       dimensions=scale(value.dimensions, factor))
    if isinstance(value, SolidValue) and not motion.reflected:
        return replace(value, key=key, frame=transform_frame(value.frame, motion),
                       dimensions=scale(value.dimensions, factor))
    if isinstance(value, GridValue):
        return replace(value, key=key, frame=transform_frame(value.frame, motion),
                       spacing=scale(value.spacing, factor))
    if isinstance(value, RigidValue):
        return RigidValue(key, value.source, motion.after(value.motion))
    if isinstance(value, TranslatedValue):
        return RigidValue(key, value.source, motion.after(RigidMotion(offset=value.vector)))
    return RigidValue(key, value, motion)


def inactive_motion_ports(operation, ports):
    if operation == 'move' and 'T' in ports:
        return MOVE_AXES
    if operation == 'mirror' and 'M' in ports:
        return ('S', 'E', 'P')
    if operation in ('rotate', 'scale'):
        direct = 'A' if operation == 'rotate' else 'F'
        if direct in ports:
            return ('To',)
        if 'To' in ports:
            return (direct,)
    return ()


def normalize_move_state(operation,data):
    state=normalize_curve_state(operation,data,spec=MOVE_SPECS[operation])
    if state['mode']!='generate' or state['references'] or 'References' in state['tree_modes']:
        raise ValueError('Connect source geometry to Move; set references on its source node.')
    return state


@dataclass(frozen=True)
class Binding:
    owner:str
    part:str
    selectors:tuple=()
    frame:PlaneValue=PlaneValue()
    offset:tuple=(0.,0.,0.)
    chain:tuple=()
    reference_id:str=''
    applied:tuple=(0.,0.,0.)
    project:str=''
    source_uuid:str=''
    grid_reference_compound:bool=False
    motion:RigidMotion|None=None
    applied_motion:RigidMotion|None=None

    @property
    def target(self):
        return self.motion or RigidMotion(offset=self.offset)

    @property
    def applied_target(self):
        return self.applied_motion or RigidMotion(offset=self.applied)


class MoveConflict(ValueError):
    def __init__(self,message,owners):
        super().__init__(message)
        self.owners=tuple(owners)


def source_bindings(node,outputs,model):
    """Keys are scoped to one output, never matched by name or coordinates."""
    from .grids import GridValue
    from .wires import WireValue
    from .geometry import GEOMETRY_SPECS
    from .booleans import SHOW_PARENT_OPERATIONS
    from .mesh_nodes import MESH, MeshValue
    from .operations import SECONDARY_GEOMETRY_PORTS
    refs={r['key']:r for r in node.parameters.get('references',[])}
    if node.operation == MESH:
        return {'M': {value.key: Binding(node.id, value.key, (), PlaneValue(),
                                        reference_id=refs[value.key]['id'], project=node.parameters['project_uuid'],
                                        source_uuid=node.parameters['node_uuid'])
                      for value in outputs['M'].values() if value.key in refs}}
    if model is None:
        return {}
    parts={v.key:v for v in model.parts.values()}
    from collections import Counter
    reference_sizes = Counter(r['id'] for r in refs.values())
    primary='P' if node.operation=='point' else GEOMETRY_SPECS[node.operation].get('primary','C')
    result={}
    for port,tree in outputs.items():
        if not isinstance(tree,DataTree):
            continue
        bindings={}
        for value in tree.values():
            if not is_geometry(value) and not isinstance(value, MeshValue):
                continue
            primary_output = (port == primary or (node.operation in (*SHOW_PARENT_OPERATIONS, 'array') and port == 'Flat')
                              or (node.operation == 'bounding_box' and port == 'G')
                              or port == SECONDARY_GEOMETRY_PORTS.get(node.operation)
                              or (model.kind == 'line_network' and port == 'B')
                              or (node.operation == 'hexagon_tiling' and port == 'H')
                              or (node.operation == 'penrose_p2' and port in ('K', 'D', 'A')))
            part=parts.get(value.key) if primary_output else None
            selectors=()
            if part is None:
                prefix=value.key
                while ':' in prefix:
                    prefix=prefix.rpartition(':')[0]
                    candidate=parts.get(prefix)
                    if isinstance(candidate,GridValue):
                        part=candidate
                        break
                if part is None:
                    continue
                if isinstance(value,PointValue):
                    selectors=(('point',value.key[len(part.key)+1:]),)
                elif isinstance(value,WireValue):
                    selectors=tuple(('edge',s.key[len(part.key)+1:]) for s in value.segments)
                elif isinstance(value,CurveValue):
                    selectors=(('edge',value.key[len(part.key)+1:]),)
                else:
                    continue
            ref=refs.get(part.key,{}) if model.mode=='reference' else {}
            frame = part.axis if node.operation == 'bounding_box' else getattr(part, 'frame', PlaneValue())
            bindings[value.key]=Binding(node.id,part.key,selectors,frame,
                reference_id=ref.get('id',''),applied=tuple(ref.get('move_offset',(0.,0.,0.))),project=model.project_uuid,
                source_uuid=node.parameters.get('node_uuid',''),
                grid_reference_compound=isinstance(part, GridValue) and reference_sizes[ref.get('id')] > 1,
                applied_motion=rigid_from_wire(ref['move_transform']) if 'move_transform' in ref else None)
        if bindings:
            result[port]=bindings
    return result


def evaluate_move(operation,parameters,inputs,bindings=None,node_id=''):
    state=normalize_move_state(operation,parameters)
    spec=MOVE_SPECS[operation]
    bindings=bindings or {}
    vector_connected = operation == 'move' and 'T' in inputs
    inactive = inactive_motion_ports(operation, inputs)
    descriptors = tuple(d for d in spec['inputs'] if d.port not in inactive
                        and (not d.optional or d.port in inputs))
    trees=matched_inputs([input_tree(inputs.get(d.port,state['parameters'].get(d.port)),d,
        state['tree_modes'].get(d.port,'none'),d.port not in inputs) for d in descriptors])
    records=[]
    transforms=[]
    effects=[]
    inherited={}
    own=[]
    occurrences={}
    widths_by_tree = [{b.path: len(b.items) for b in t.branches} for t in trees]
    for path,rows in aligned(*trees):
        widths = [index.get(path, len(t.branches[0].items)) for index, t in zip(widths_by_tree, trees)]
        if rows and any(width not in (1, len(rows)) for width in widths):
            raise ValueError('Move lists must have equal lengths or one item. Match the DataTree explicitly.')
        values=[]
        vectors=[]
        owned=[]
        for items,provenance in rows:
            value=items[0]
            binding=bindings.get(value.key) if operation not in ('move_gh', 'orient') else None
            if operation == 'orient':
                motion = orient_frames(items[1], items[2])
                displayed = motion
            elif operation == 'mirror':
                args = {d.port: item for d, item in zip(descriptors, items)}
                if 'M' in args:
                    plane = args['M']
                    motion = reflection(plane.origin, plane.normal)
                else:
                    start, end, plane = args['S'], args['E'], args['P']
                    normal = cross(plane.normal, sub(end.xyz, start.xyz))
                    if math.hypot(*normal) <= 1e-12:
                        raise ValueError('Mirror needs a line with a direction along the work plane.')
                    motion = reflection(start.xyz, unit(normal))
                if args['K']:
                    binding = None
                displayed = None
            elif operation in ('rotate', 'scale'):
                args = {d.port: item for d, item in zip(descriptors, items)}
                center = args['C'].xyz
                if operation == 'scale':
                    displayed = math.dist(center, args['To'].xyz) if 'To' in args else args['F']
                    motion = uniform_scale(center, displayed)
                else:
                    plane = args['P']
                    if 'To' in args:
                        ray = sub(args['To'].xyz, center)
                        x, y = dot(ray, plane.axis_x), dot(ray, plane.axis_y)
                        displayed = math.degrees(math.atan2(y, x)) if math.hypot(x, y) > 1e-12 else 0.
                    else:
                        displayed = args['A']
                    motion = rotation(center, plane.normal, displayed)
                if args['Cp']:
                    binding = None
            elif operation=='move_gh':
                vector=items[1].xyz
            else:
                if vector_connected:
                    world, translation = items[1:]
                    vector = translation.xyz
                else:
                    *coordinates, world = items[1:]
                    vector = tuple(coordinates)
                if not world:
                    x, y, z = vector
                    frame=binding.frame if binding else getattr(value,'frame',PlaneValue())
                    if binding and not binding.chain and binding.applied_motion is not None and hasattr(value, 'frame'):
                        frame = transform_frame(frame, binding.applied_motion.inverse())
                    vector=add(add(scale(frame.axis_x,x),scale(frame.axis_y,y)),scale(frame.normal,z))
            if operation in ('move', 'move_gh'):
                motion = RigidMotion(offset=vector)
                displayed = TranslationValue(tuple(vector))
            if binding and binding.reference_id and '/' in binding.part and (binding.selectors or binding.grid_reference_compound):
                action = {'move': 'Use Move GH', 'mirror': 'Enable Keep Original'}.get(operation, 'Enable Copy')
                raise MoveConflict(f'In-place transformation requires a whole single-grid reference. {action} for grid members.', (binding.owner,))
            target = motion.after(binding.target) if binding else motion
            delta = motion
            if binding and binding.reference_id and not binding.chain:
                applied = binding.applied_target
                delta = IDENTITY if target == applied else target.after(applied.inverse())
            text=json.dumps(provenance)
            count=occurrences.get(text,0)
            occurrences[text]=count+1
            key=value.key if binding else hashlib.sha256(f'{text}:{count}'.encode()).hexdigest()[:24]
            moved=transform_geometry(value,delta,key)
            values.append(moved)
            vectors.append(displayed)
            if binding:
                frame = binding.frame if delta.axes == IDENTITY_AXES else transform_frame(binding.frame, delta)
                updated=replace(binding,offset=target.offset, motion=None if target.axes == IDENTITY_AXES else target,
                                frame=frame, chain=binding.chain+(node_id,))
                prior=inherited.get(key)
                if prior and prior.target!=updated.target:
                    raise MoveConflict('One source element cannot occupy two different Move positions; use Move GH for copies.',(binding.owner,))
                inherited[key]=updated
                effects.append(updated)
            else:
                owned.append(moved)
        keys=tuple(v.key for v in values)
        records.append(Branch(path,tuple(values),keys))
        transforms.append(Branch(path,tuple(vectors),keys))
        own.append(Branch(path,tuple(owned),tuple(v.key for v in owned)))
    tree=DataTree(tuple(records))
    t=DataTree(tuple(transforms))
    out={'G':tree,'Count':tree.count}
    if operation in ('move_gh', 'orient'):
        out['X']=t
    elif operation == 'rotate':
        out['A'] = t
    elif operation == 'scale':
        out['F'] = t
    elif operation == 'move':
        for axis,port in enumerate(MOVE_AXES):
            out[port]=DataTree(tuple(Branch(b.path,tuple(v.vector[axis] for v in b.items),b.keys) for b in t.branches))
    own_tree=DataTree(tuple(own))
    model=ParametricObject(state['project_uuid'],state['node_uuid'],own_tree,kind='transforms') if own_tree.count else None
    return out,model,{'G':inherited},tuple(effects)


def apply_effects(results,nodes):
    """Resolve a graph frame before ANY scene command. Keep cached base models immutable."""
    from .grids import GridValue
    frozen={owner for result in results.values() for owner in result.motion_errors}
    chosen={}
    conflicts=set()
    bad_nodes=set()
    for node_id,result in results.items():
        for binding in result.movements:
            selectors=binding.selectors or (None,)
            for selector in selectors:
                identity=('reference',binding.project,binding.reference_id) if binding.reference_id else ('owner',binding.owner,binding.part)
                key=identity+(selector,)
                old=chosen.get(key)
                if old is not None:
                    old_id,prior=old
                    if prior.chain==binding.chain:
                        if prior.target!=binding.target:
                            conflicts.update((prior.owner,binding.owner))
                            bad_nodes.update((old_id,node_id))
                    elif prior.chain==binding.chain[:len(prior.chain)]:
                        chosen[key]=(node_id,binding)
                    elif binding.chain==prior.chain[:len(binding.chain)]:
                        continue
                    elif prior.target!=binding.target:
                        conflicts.update((prior.owner,binding.owner))
                        bad_nodes.update((old_id,node_id))
                else:
                    chosen[key]=(node_id,binding)
    # A whole-owner move and an independent member move cannot silently
    # override one another. The user can compose moves in an explicit chain.
    whole={k[:-1]:(n,b) for k,(n,b) in chosen.items() if k[-1] is None}
    for key,(node_id,binding) in chosen.items():
        if key[-1] is not None and key[:-1] in whole:
            other,prior=whole[key[:-1]]
            conflicts.update((binding.owner,prior.owner))
            bad_nodes.update((node_id,other))
    frozen.update(conflicts)
    changed=True
    while changed:
        changed=False
        for node in nodes:
            if node.id not in bad_nodes and any(c.node_id in bad_nodes for c in node.inputs.values()):
                bad_nodes.add(node.id)
                changed=True
    out=dict(results)
    for node_id in bad_nodes:
        out[node_id]=replace(out[node_id],outputs={},error='Conflicting transformation targets. Use a chain for composition or copies for independent results.',
            parametric_object=None,bindings={},movements=())
    owners={}
    references=[]
    for key,(node_id,binding) in chosen.items():
        if binding.owner in frozen or node_id in bad_nodes:
            continue
        if binding.reference_id:
            entry = {'node_id':node_id,'owner':binding.owner,'id':binding.reference_id,
                'project_uuid':binding.project,'key':binding.part,
                'node_uuid':binding.source_uuid,'applied_hint':list(binding.applied)}
            if binding.motion is not None:
                entry['transform'] = binding.motion.to_wire()
            else:
                entry['offset'] = list(binding.offset)
            references.append(entry)
        elif binding.target != IDENTITY:
            owners.setdefault(binding.owner,{}).setdefault(binding.part,[]).append((key[-1],binding.target))
    for owner,parts in owners.items():
        result=out[owner]
        model=result.parametric_object
        if model is None:
            frozen.add(owner)
            continue
        branches=[]
        for branch in model.parts.branches:
            values=[]
            for value in branch.items:
                entries=parts.get(value.key,())
                if not entries:
                    values.append(value)
                elif entries[0][0] is None:
                    motion = entries[0][1]
                    values.append(TranslatedValue(value.key,value,motion.offset) if motion.axes == IDENTITY_AXES
                                  else RigidValue(value.key, value, motion))
                elif isinstance(value,GridValue):
                    values.append(GridEditValue(value.key,value,tuple(
                        (selector[0], selector[1], t.offset if t.axes == IDENTITY_AXES else t)
                        for selector, t in entries)))
                else:
                    raise ValueError('Only grid geometry has selectable generated members.')
            branches.append(Branch(branch.path,tuple(values),branch.keys))
        out[owner]=replace(result,parametric_object=ParametricObject(model.project_uuid,model.node_uuid,
            DataTree(tuple(branches)),kind='transforms'))
    return out,tuple(references),frozenset(frozen)


def object_from_wire(data):
    from .curves import curve_object_from_wire
    budget=[10000]
    return curve_object_from_wire(data,decoder=lambda d:geometry_from_wire(d,budget=budget),kind='transforms')
