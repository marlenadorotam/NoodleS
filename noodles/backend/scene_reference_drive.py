"""Prepare and commit updates to existing native references."""
from dataclasses import replace
import json
import math
from types import SimpleNamespace

from .curves import PlaneValue, curve_from_wire, dot, sub
from .reference_drive import REFERENCE_SPECS, decode_updates, reference_target
from .scene_curves import REFERENCES, SOLID_REFERENCES, inspect_curve, materialize
from .datatree import DataTree
from .grids import GRID_SPECS, grid_object_from_wire
from .grid_reference_native import GRID_REFERENCES
from .scene_points import MODEL
from .solids import SOLID_SPECS, solid_from_wire
from .move_native import applied_motion, apply_motion
from .rigid_motion import IDENTITY_AXES
from .primitive_shapes import HEIGHT_SIGN_KEYS


def _materialize_reference(operation, target):
    if operation == 'ellipse' and target.dimensions[0] < target.dimensions[1]:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Ax2, gp_Dir, gp_Elips, gp_Pnt
        frame = target.frame
        ellipse = gp_Elips(gp_Ax2(gp_Pnt(*frame.origin), gp_Dir(*frame.normal),
                                  gp_Dir(*frame.axis_y)), *reversed(target.dimensions))
        # The full edge's seam records the first named axis, even after
        # crossing the major/minor threshold or reopening a BREP.
        return BRepBuilderAPI_MakeEdge(ellipse, 1.5*math.pi, 3.5*math.pi).Edge()
    if operation in ('arc', 'arc_center'):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
        from OCP.TopoDS import TopoDS
        frame = target.frame
        if operation == 'arc':
            through = sub(target.points[1], frame.origin)
            angle = math.atan2(dot(through, frame.axis_y), dot(through, frame.axis_x)) % (2*math.pi)
            frame = PlaneValue(frame.origin, through, frame.normal)
        else:
            angle = 0.
        circle = gp_Circ(gp_Ax2(gp_Pnt(*frame.origin), gp_Dir(*frame.normal),
                               gp_Dir(*frame.axis_x)), target.radius)
        if target.angle < 0:
            edge = BRepBuilderAPI_MakeEdge(circle, target.angle, 0.).Edge()
            return TopoDS.Edge_s(edge.Reversed())
        return BRepBuilderAPI_MakeEdge(circle, -angle, target.angle-angle).Edge()
    return materialize(target)


def submit_reference_drive(adapter, params):
    operation = params.get('primitive')
    if operation not in REFERENCE_SPECS or params.get('mode') != 'reference':
        raise ValueError('Geometry driving requires a native reference.')
    binding = adapter.identity(params)
    identity = ('reference-drive', *binding)
    job_id = adapter._begin_job(identity)
    updates = decode_updates(operation, params.get('drive', {}).get('updates'))
    if not updates:
        return {'state': 'complete'}
    if adapter._busy():
        return {'state': 'busy'}
    solid = operation in SOLID_SPECS
    grid = operation in GRID_SPECS
    metadata = GRID_REFERENCES if grid else SOLID_REFERENCES if solid else REFERENCES
    keys = dict.fromkeys(key.split('/', 1)[0] for key in updates) if grid else updates
    sources = adapter.curves.bound_sources(binding, keys, metadata)
    snapshots = [(SimpleNamespace(id=obj.id, name=obj.name, kind=obj.kind, shape=obj._shape,
                                 user_text=obj.user_text,
                                 manifest=adapter._json(obj, MODEL) if grid else None,
                                 motion=applied_motion(adapter, obj, binding[0])), key)
                 for obj, key in sources]
    job = {'state': 'preparing', 'identity': identity, 'document': adapter.ctx.scene.layers,
           'scene_reference_drive': True, 'binding': binding, 'sources': snapshots, 'metadata': metadata,
           'primitive': operation}
    adapter.jobs[job_id] = job

    def prepare():
        from .solid_native import inspect_solid
        from .native_display import geometry_bounds, tessellate
        shapes = []
        for obj, key in snapshots:
            if adapter.latest.get(identity) != job_id:
                return []
            motion = obj.motion
            rotated = motion.axes != IDENTITY_AXES
            if rotated:
                obj = SimpleNamespace(**{**vars(obj), 'shape': apply_motion(obj.shape, motion.inverse())})
            if grid:
                from serpentine3d.core.geometry import make_compound
                current_model = adapter.curves.grid_model(obj, operation)
                slot_updates = {slot.split('/', 1)[1]: args for slot, args in updates.items() if slot.startswith(key+'/')}
                if set(slot_updates) - {value.key for value in current_model.parts.values()}:
                    raise ValueError('The grid slots changed. Set references again.')
                branches = []
                for branch in current_model.parts.branches:
                    targets = tuple(reference_target(operation, v, slot_updates[v.key]) if v.key in slot_updates else v
                                    for v in branch.items)
                    branches.append(replace(branch, items=targets))
                model = replace(current_model, parts=DataTree(tuple(branches)))
                if model == current_model:
                    continue
                wire = model.to_wire()
                grid_object_from_wire(wire)
                parts = [materialize(value) for value in model.parts.values()]
                if rotated:
                    parts = [apply_motion(part, motion) for part in parts]
                shape = make_compound(parts)
                bounds = geometry_bounds(parts)
                shapes.append((obj.id, shape, tessellate(shape, parts=parts, bounds=bounds), bounds, wire, None))
                continue
            if solid:
                current = solid_from_wire(inspect_solid(obj, key, operation)['recipe'])
            elif operation in ('curve', 'interpcurve'):
                from .spline_native import describe_spline
                current = describe_spline(obj.shape, key, operation, measure=False)
            else:
                current = curve_from_wire(inspect_curve(obj, key, operation)['recipe'])
            target = reference_target(operation, current, updates[key])
            if target == current:
                continue
            shape = _materialize_reference(operation, target)
            if rotated:
                shape = apply_motion(shape, motion)
            bounds = geometry_bounds([shape])
            height_sign = ('-1' if target.dimensions[-1] < 0 else '') if operation in HEIGHT_SIGN_KEYS else None
            shapes.append((obj.id, shape, tessellate(shape, parts=[shape], bounds=bounds), bounds, None, height_sign))
        return shapes

    future = adapter.pool.submit(prepare)
    job['future'] = future

    def ready(_):
        try:
            adapter.prepared.emit(job_id)
        except RuntimeError:
            pass

    future.add_done_callback(ready)
    return {'state': 'preparing', 'job_id': job_id}


def commit_reference_drive(adapter, job):
    from serpentine3d.core.user_text import value_of, with_value
    shapes = job['future'].result()
    snapshots = job['sources']
    height_sign_key = HEIGHT_SIGN_KEYS.get(job['primitive'])
    current = adapter.curves.bound_sources(job['binding'], (key for _, key in snapshots), job['metadata'])
    if any(obj.id != old.id or obj._shape is not old.shape or
           applied_motion(adapter, obj, job['binding'][0]) != old.motion or
           (height_sign_key and
            value_of(obj.user_text, height_sign_key) != value_of(old.user_text, height_sign_key)) or
           (job['metadata'] == GRID_REFERENCES and adapter._json(obj, MODEL) != old.manifest)
           for (old, _), (obj, _) in zip(snapshots, current)):
        job['state'] = 'retry'
        return
    if shapes:
        scene = adapter.ctx.scene
        snapshot = scene.snapshot()
        adapter._checkpoint('Change referenced geometry')
        try:
            with scene.batched():
                for object_id, shape, mesh, bounds, manifest, height_sign in shapes:
                    obj = scene.replace_shape(object_id, shape)
                    if manifest is not None:
                        obj = scene.update(obj.id, user_text=with_value(obj.user_text, MODEL, json.dumps(manifest)))
                    if height_sign is not None and (value_of(obj.user_text, height_sign_key) or '') != height_sign:
                        obj = scene.update(obj.id, user_text=with_value(obj.user_text, height_sign_key, height_sign))
                    obj._mesh = mesh
                    obj._bounds = (shape, bounds)
        except Exception:
            scene.restore(snapshot)
            history = getattr(adapter.ctx.window, 'history', None)
            if history:
                history.discard_checkpoint()
            raise
    job['state'] = 'complete'
