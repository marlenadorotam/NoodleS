"""Native shape construction for the common Move/ParametricObject publisher."""
from .rigid_motion import IDENTITY, IDENTITY_AXES, RigidMotion, from_wire
from .scene_boolean import RESULT_REFS

MOTION='NoodleS.move_offsets'
REFERENCE_FIELDS = ('NoodleS.point_references', 'NoodleS.curve_references', 'NoodleS.geometry_references',
                    'NoodleS.grid_references', RESULT_REFS)


def reference_tags(adapter, obj):
    for field in REFERENCE_FIELDS:
        tags = adapter._json(obj, field, {})
        if isinstance(tags, dict):
            for token, key in tags.items():
                if isinstance(key, str):
                    yield token, key


def applied_motion(adapter,obj,project):
    from .curves import xyz
    records=adapter._json(obj,MOTION,{})
    if not isinstance(records,dict):
        raise ValueError('Invalid saved Move metadata.')
    record = records.get(project, (0.,0.,0.))
    if isinstance(record, dict):
        return from_wire(record.get('transform'))
    return RigidMotion(offset=xyz(record))


def apply_motion(shape, motion):
    from serpentine3d.core import geometry as g
    if motion.axes == IDENTITY_AXES:
        return g.translate(shape, motion.offset)
    from OCP.gp import gp_Trsf
    transform = gp_Trsf()
    transform.SetValues(*(value for row in motion.to_wire() for value in row))
    return g._apply_trsf(shape, transform)


def submit_references(adapter,params):
    import uuid
    from .curves import xyz
    from .native_display import tessellate,geometry_bounds
    entries=params.get('entries')
    if not isinstance(entries,list) or len(entries)>10000:
        raise ValueError('Invalid reference Move frame.')
    if adapter._busy():
        return {'state':'busy'}
    identity = ('reference_moves', str(uuid.UUID(params['client_uuid'])))
    job_id = adapter._begin_job(identity)
    scene=adapter.ctx.scene
    requested = []
    for entry in entries:
        project=str(uuid.UUID(entry['project_uuid']))
        node=str(uuid.UUID(entry['node_uuid']))
        target = from_wire(entry['transform']) if 'transform' in entry else RigidMotion(offset=xyz(entry['offset']))
        key = entry['key']
        if not isinstance(key, str) or not 0 < len(key) <= 256:
            raise ValueError('Invalid reference Move binding key.')
        tag = (adapter._ref_token((project, node, 0)), key.split('/', 1)[0])
        requested.append((tag, project, target, entry.get('reset') is True and target == IDENTITY))
    candidates = {tag: {} for tag, _, _, _ in requested}
    if candidates:
        for obj in scene.all():
            for tag in reference_tags(adapter, obj):
                if tag in candidates:
                    candidates[tag][obj.id] = obj
    snapshots = {}
    for tag, project, target, reset in requested:
        matches = candidates[tag]
        if not matches and reset:
            continue
        if len(matches) != 1:
            raise ValueError('Reference Move binding is missing or duplicated. Set source references again.')
        obj = next(iter(matches.values()))
        if obj.id in snapshots:
            if snapshots[obj.id][1:3]!=(project,target):
                raise ValueError('Conflicting reference Move targets.')
            continue
        previous=applied_motion(adapter,obj,project)
        snapshots[obj.id] = (obj._shape, project, target, previous, tag)
    if all(target == previous for _, _, target, previous, _ in snapshots.values()):
        return {'state':'complete'}
    job={'state':'preparing','identity':identity,'document':scene.layers,
         'move_references':True,'sources':snapshots}
    adapter.jobs[job_id]=job
    def prepare():
        out={}
        for oid, (shape, _, target, previous, _) in snapshots.items():
            if adapter.latest.get(identity)!=job_id:
                raise ValueError('Reference Move superseded.')
            if target != previous:
                moved = apply_motion(shape, target.after(previous.inverse()))
                bounds=geometry_bounds([moved])
                out[oid]=(moved,tessellate(moved,parts=[moved],bounds=bounds),bounds)
        return out
    future=adapter.pool.submit(prepare)
    job['future']=future
    def done(_):
        try:
            adapter.prepared.emit(job_id)
        except RuntimeError:
            pass
    future.add_done_callback(done)
    return {'state':'preparing','job_id':job_id}


def commit_references(adapter,job_id,job):
    import json
    from serpentine3d.core.user_text import with_value
    scene=adapter.ctx.scene
    prepared=job['future'].result()
    for oid, (original, project, _, previous, tag) in job['sources'].items():
        obj=scene.get(oid)
        if (obj is None or obj._shape is not original or tag not in reference_tags(adapter, obj)
                or applied_motion(adapter, obj, project) != previous):
            raise ValueError('Reference geometry changed during Move; retry.')
    snapshot=scene.snapshot()
    adapter._checkpoint('Move referenced geometry')
    try:
        with scene.batched():
            for oid,(shape,mesh,bounds) in prepared.items():
                obj=scene.replace_shape(oid,shape)
                project,target=job['sources'][oid][1:3]
                records=dict(adapter._json(obj,MOTION,{}))
                if target.axes != IDENTITY_AXES:
                    records[project] = {'transform': target.to_wire()}
                elif any(target.offset):
                    records[project] = list(target.offset)
                else:
                    records.pop(project,None)
                obj=scene.update(oid,user_text=with_value(obj.user_text,MOTION,json.dumps(records)))
                obj._mesh=mesh
                obj._bounds=(shape,bounds)
        job.update(state='complete')
    except Exception:
        scene.restore(snapshot)
        history=getattr(adapter.ctx.window,'history',None)
        if history:
            history.discard_checkpoint()
        raise


def materialize(value,resolve):
    from serpentine3d.core import geometry as g
    from .moves import TranslatedValue,RigidValue,GridEditValue,translate,transform_geometry
    if isinstance(value,TranslatedValue):
        return g.translate(resolve(value.source),value.vector)
    if isinstance(value, RigidValue):
        return apply_motion(resolve(value.source), value.motion)
    if not isinstance(value,GridEditValue):
        raise ValueError('Unknown movement recipe.')
    from .grids import members
    from .scene_curves import materialize as native
    import time
    _,_,_,_,points,centres,edges,_=members(value.source,cells=False,cooperate=True)
    edits={(kind,role):vector for kind,role,vector in value.edits}
    valid={('point',r) for r in (*points,*centres)}|{('edge',r) for r in edges}
    if set(edits)-valid:
        raise ValueError('A moved grid member no longer exists.')
    parts=[]
    deadline=time.perf_counter()+.004
    for kind,values in (('point',points),('point',centres),('edge',edges)):
        for role,part in values.items():
            change=edits.get((kind,role))
            if isinstance(change, RigidMotion):
                part=transform_geometry(part, change, part.key)
            elif change is not None:
                part=translate(part,change)
            parts.append(native(part))
            if time.perf_counter()>=deadline:
                time.sleep(.001)
                deadline=time.perf_counter()+.004
    return g.make_compound(parts)
