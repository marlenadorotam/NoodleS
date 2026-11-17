"""Universal Serpentine publisher: materialize recipes off-thread, commit on Qt.

Imported only by Serpentine (or isolated native integration tests), never by the
graph engine. References are existing, individually editable SceneObjects.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from collections import OrderedDict
import json
import uuid
from weakref import WeakKeyDictionary

from PySide6 import QtCore

from .point import normalize_point_state, object_from_wire
from .datatree import finite
from .solid_display import SolidDisplayCache

OWNER = "NoodleS.binding"
MODEL = "NoodleS.parametric"
REFERENCES = "NoodleS.point_references"


class ParametricSceneAdapter(QtCore.QObject):
    prepared = QtCore.Signal(str)
    reference_prepared = QtCore.Signal(str, object)
    references_updated = QtCore.Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.jobs = {}
        self.latest = {}
        self._missing_parent_targets = False
        self.preview_hide_targets = lambda scene: ()
        self.boolean_scenes = WeakKeyDictionary()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="NoodleS-OCC")
        self._part_cache = OrderedDict()  # Accessed only by the single OCC worker.
        self._topology_cache = OrderedDict()
        self._solid_display = SolidDisplayCache()
        from .deleted_geometry import DeletedGeometry
        self.deleted = DeletedGeometry(ctx)
        self.prepared.connect(self._commit, QtCore.Qt.ConnectionType.QueuedConnection)
        from .scene_curves import CurveReferences
        self.curves = CurveReferences(self)
        self.reference_prepared.connect(self.curves.prepared, QtCore.Qt.ConnectionType.QueuedConnection)

    def stop(self):
        self.latest.clear()
        self.curves.latest.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def identity(data):
        return (str(uuid.UUID(data["project_uuid"])), str(uuid.UUID(data["node_uuid"])), 0)

    @staticmethod
    def _json(obj, key, default=None):
        from serpentine3d.core.user_text import value_of
        value = value_of(obj.user_text, key)
        if value is None:
            return default
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("Invalid NoodleS metadata on object " + obj.name)

    def owner(self, identity):
        matches = []
        for obj in self.ctx.scene.all():
            binding = self._json(obj, OWNER)
            if binding and (binding.get("project_uuid"), binding.get("node_uuid"), binding.get("output_index")) == identity:
                matches.append(obj)
        if len(matches) > 1:
            raise ValueError("Duplicate ParametricObject binding. Resolve the copied object before updating.")
        return matches[0] if matches else None

    def _checkpoint(self, label):
        history = getattr(self.ctx.window, "history", None)
        if history:
            history.checkpoint(label)

    def dispatch(self, method, params):
        if method == 'geometry.ungroup':
            from .scene_ungroup import submit
            return submit(self, self.identity(params))
        if method == 'geometry.surface_structure':
            from functools import partial
            from .surface_structure_native import measure
            return self._submit_measurement(method, params, partial(measure, cache=self._topology_cache))
        if method == 'geometry.tessellation':
            from .tessellation_native import measure
            return self._submit_measurement(method, params, measure)
        if method == 'geometry.population':
            from .population_native import measure
            return self._submit_measurement(method, params, measure)
        if method == 'geometry.uv_grid':
            from .surface_grid_native import measure
            return self._submit_measurement(method, params, measure)
        if method == 'geometry.topology':
            from functools import partial
            from .topology_native import measure
            return self._submit_measurement(method, params, partial(measure, cache=self._topology_cache))
        if method == 'geometry.mass_properties':
            from functools import partial
            from .mass_properties import measure
            return self._submit_measurement(method, params, partial(measure, cache=self._topology_cache))
        if method in ('geometry.boolean_apply', 'geometry.boolean_read'):
            from . import scene_boolean
            handler = scene_boolean.submit_apply if method == 'geometry.boolean_apply' else scene_boolean.submit_read
            return handler(self, params)
        if method in ('geometry.surface_domain', 'geometry.surface_closest'):
            from functools import partial
            from .surface_uv_native import measure
            return self._submit_measurement(method, params, partial(measure, closest=method == 'geometry.surface_closest'))
        if method in ('geometry.pull', 'geometry.sample'):
            from . import pull_native, curve_sampling_native
            measure = pull_native.measure if method == 'geometry.pull' else curve_sampling_native.measure
            return self._submit_measurement(method, params, measure)
        if method == 'geometry.drive':
            from .scene_reference_drive import submit_reference_drive
            return submit_reference_drive(self, params)
        if method=='geometry.move_refs':
            from .move_native import submit_references
            return submit_references(self,params)
        if method in ('curves.capture', 'geometry.capture'):
            if method == 'geometry.capture' and params.get('primitive') == 'fillet_edge':
                from .fillet_native import submit_capture
                return submit_capture(self, params)
            return self.curves.capture(params)
        if method in ('curves.read', 'geometry.read'):
            return self.curves.read(params)
        method = method.replace('geometry.', 'points.', 1)
        if method == "points.prepare":
            return self.submit(params)
        if method == "points.job":
            job = self.jobs.get(params.get("job_id"))
            if job is None:
                raise ValueError("Point publication job is no longer available.")
            return {key: job[key] for key in ("state", "error", "object_id", "curve_details", 'references',
                                             'measurements', 'records', 'consumed', 'detached', 'ungrouped',
                                             'scene_token') if key in job}
        if method == "points.remove":
            identity = self.identity(params)
            self.latest.pop(identity, None)
            obj = self.owner(identity)
            if obj:
                if self._busy():
                    return {'state': 'busy', 'removed': False}
                details = self._details_for(identity, self._json(obj, MODEL))
                record = self.deleted.remember(identity, obj, details)
                from .parent_visibility import CLAIMS, reconcile
                has_claims = bool(self._json(obj, CLAIMS))
                self._checkpoint("Remove NoodleS geometry")
                scene = self.ctx.scene
                snapshot = scene.snapshot() if has_claims else None
                try:
                    with scene.batched():
                        scene.remove(obj.id)
                        if has_claims:
                            reconcile(self)
                except Exception:
                    if snapshot is not None:
                        scene.restore(snapshot)
                    elif scene.get(obj.id) is None:
                        self.deleted.restore(record, record.obj._shape, record.obj._mesh)
                    history = getattr(self.ctx.window, 'history', None)
                    if history:
                        history.discard_checkpoint()
                    raise
            return {'state': 'complete', 'removed': bool(obj)}
        if method == "points.capture":
            return self.capture(params)
        if method == "points.read":
            return self.read(params)
        if method == "points.drive":
            return self.drive(params)
        raise ValueError("Unsupported Point method.")

    def _submit_measurement(self, method, params, measure):
        identity = (method, *self.identity(params))
        plan = params.get('plan')
        if plan is None:
            self._begin_job(identity)
            return {'state': 'complete'}
        if not isinstance(plan, dict):
            raise ValueError('Invalid native measurement plan.')
        return self._submit_worker(identity, lambda current: measure(plan, current), measurement=True)

    def _submit_worker(self, identity, prepare, **metadata):
        job_id = self._begin_job(identity)
        job = {'state': 'preparing', 'identity': identity, 'document': self.ctx.scene.layers, **metadata}
        self.jobs[job_id] = job
        future = self.pool.submit(prepare, lambda: self.latest.get(identity) == job_id)
        job['future'] = future

        def ready(_):
            try:
                self.prepared.emit(job_id)
            except RuntimeError:
                pass

        future.add_done_callback(ready)
        return {'job_id': job_id}

    def _details_for(self, identity, model):
        for job in reversed(tuple(self.jobs.values())):
            if job.get('identity') == identity and job.get('model') == model and job.get('state') == 'complete':
                return job.get('curve_details', {})
        return {}

    def _begin_job(self, identity):
        job_id = uuid.uuid4().hex
        self.latest[identity] = job_id
        for previous in self.jobs.values():
            if not previous.get('reference_job') and previous.get("identity") == identity and previous["state"] == "preparing":
                previous["state"] = "superseded"
                previous.get("future").cancel()
        if len(self.jobs) > 128:
            for key in list(self.jobs):
                if self.jobs[key]["state"] != "preparing":
                    self.jobs.pop(key)
                if len(self.jobs) <= 64:
                    break
        return job_id

    def submit(self, params):
        model = object_from_wire(params["model"])
        identity = self.identity(params["model"])
        owner = self.owner(identity)
        wire = model.to_wire()
        from .booleans import can_hide_sources
        from .parent_visibility import validated_targets
        targets = validated_targets(params.get('hidden_parents', []))
        if targets and (model.kind not in ('operations', 'transforms') or not model.parts.count or
                        not all(can_hide_sources(part) for part in model.parts.values())):
            raise ValueError('This operation cannot hide its sources.')
        if any(target[1:3] == identity[:2] for target in targets):
            raise ValueError('An operation result cannot hide itself.')
        job_id = self._begin_job(identity)
        job = {"state": "preparing", "identity": identity, "document": self.ctx.scene.layers,
               "owner": owner, "model": wire, "name": str(params.get("name", "Point"))[:200],
               "hidden_parents": targets}
        self.jobs[job_id] = job
        if owner is None:
            from .scene_boolean import consumed
            from .scene_ungroup import is_detached
            if is_detached(self.ctx.scene, identity):
                job.update(state='complete', detached=True)
                return {'job_id': job_id}
            if consumed(self, identity):
                job.update(state='complete', consumed=True)
                return {'job_id': job_id}
        from .operations import OPERATION_SPECS
        needs_details = model.kind not in ('mapped_tessellation', 'uv_panels') and any(
            getattr(part, 'kind', '') in ('curve', 'interpcurve','translated','rigid_transform',*OPERATION_SPECS)
            for part in model.parts.values())
        archived = self.deleted.peek(identity) if owner is None else None
        if archived:
            job['restore'] = archived
            same_geometry = self._json(archived.obj, MODEL) == wire
            job['reuse_archived'] = same_geometry
            if same_geometry and archived.obj._mesh is not None and (not needs_details or archived.details):
                future = Future()
                future.set_result((archived.obj._shape, archived.obj._mesh))
                job.update(future=future, curve_details=archived.details)
                self.prepared.emit(job_id)
                return {'job_id': job_id}
        if owner is not None and self._json(owner, MODEL) == wire and not needs_details:
            job.update(state="complete", object_id=owner.id)
            return {"job_id": job_id}
        if owner is not None:
            previous_model = self._json(owner, MODEL, {})
            leaves = lambda value: [p for b in value.get("branches", []) for p in b.get("points" if value.get('kind') == 'points' else 'parts', [])]
            if leaves(previous_model) == leaves(wire) and all(
                    previous_model.get(field) == wire.get(field) for field in ('vertices','surfaces','sources')):
                if needs_details:
                    job['reuse_shape'] = True
                else:
                    # Graft/Flatten changed topology only. Preserve BREP and mesh.
                    from serpentine3d.core.user_text import with_value
                    self._checkpoint("Update geometry data structure")
                    self.ctx.scene.update(owner.id, user_text=with_value(owner.user_text, MODEL, json.dumps(wire)))
                    job.update(state="complete", object_id=owner.id)
                    return {"job_id": job_id}
        def prepare():
            # A compound is used even for ONE point. Nothing is added to Scene
            # until both its BREP and native display mesh are ready.
            from serpentine3d.core import geometry as g
            from .native_display import tessellate
            if not model.points.count:
                return None, None
            if model.kind == 'solids' and model.parts.count > 1:
                shape, mesh, job['bounds'] = self._solid_display.prepare(
                    model.parts.values(), lambda: self.latest.get(identity) == job_id)
                return shape, mesh
            if model.kind == 'meshes':
                from .mesh_native import materialize, prepare_mesh
                shape, mesh, job['bounds'] = prepare_mesh(materialize(part) for part in model.parts.values())
                return shape, mesh
            if model.kind == 'points':
                parts = [g.make_point(p.xyz) for p in model.parts.values()]
            elif model.kind == 'tessellation':
                from .tessellation_native import build_wires
                parts = build_wires((cell.points for cell in model.parts.values()),
                                    lambda: self.latest.get(identity) == job_id)
            elif model.kind == 'penrose_p2':
                from .penrose_native import build_parts
                parts = build_parts(((part.kind, part.points) for part in model.parts.values()),
                                    lambda: self.latest.get(identity) == job_id)
            else:
                from .scene_curves import materialize
                parts = []
                details = {}
                import time
                deadline=time.perf_counter()+.004
                def resolve(part):
                    nonlocal deadline
                    if self.latest.get(identity) != job_id:
                        raise ValueError('Publication superseded.')
                    signature = json.dumps(part.to_wire(), sort_keys=True, separators=(',', ':'))
                    cached = self._part_cache.get(signature)
                    if cached is None:
                        if part.kind == 'map_surface' and model.kind == 'mapped_tessellation':
                            from .map_surface_native import map_polygon
                            polygon, source, target = part.sources
                            shape = map_polygon(polygon.points, resolve(source), resolve(target))
                        else:
                            shape = materialize(part,resolve=resolve,topology_cache=self._topology_cache) if part.kind in OPERATION_SPECS or part.kind in ('translated','rigid_transform','grid_edit') else materialize(part)
                        record = None
                        if part.kind in ('curve', 'interpcurve'):
                            from .spline_native import describe_spline
                            from .splines import signature as spline_signature
                            record = {'signature': spline_signature(part), 'recipe': describe_spline(shape, part.key, part.kind).to_wire()}
                        elif part.kind in OPERATION_SPECS and model.kind != 'uv_panels' and (part.kind != 'map_surface' or needs_details):
                            from .splines import signature as recipe_signature
                            record={'signature':recipe_signature(part),'kind':g.shape_kind(shape)}
                            if part.kind in ('planar_surface','edge_surface','patch'):
                                record['edge_count']=len(g.edges_of(shape))
                                if part.kind=='planar_surface':
                                    record['normal']=list(g.face_normal(g.faces_of(shape)[0]))
                        elif part.kind in ('translated', 'rigid_transform') and part.source.key == part.key:
                            record = details.get(part.key)
                        cached = (shape, record)
                        self._part_cache[signature] = cached
                    self._part_cache.move_to_end(signature)
                    while len(self._part_cache) > 4096:
                        self._part_cache.popitem(last=False)
                    if cached[1] is not None:
                        details[part.key] = cached[1]
                    if time.perf_counter()>=deadline:
                        time.sleep(.001)
                        deadline=time.perf_counter()+.004
                    return cached[0]
                for part in model.parts.values():
                    parts.append(resolve(part))
                job['curve_details'] = details
            if job.get('reuse_shape'):
                return owner.shape, owner._mesh
            if job.get('reuse_archived'):
                shape = archived.obj._shape
                return shape, archived.obj._mesh if archived.obj._mesh is not None else tessellate(shape)
            shape = g.make_compound(parts)
            if model.kind in ('tessellation','mapped_tessellation','line_network','penrose_p2'):
                from .native_display import geometry_bounds
                edges = g.edges_of(shape)
                job['bounds'] = geometry_bounds(edges) if model.kind in ('mapped_tessellation','penrose_p2') else g.bbox(shape)
                return shape, tessellate(shape, bounds=job['bounds'], wire_edges=edges)
            if model.kind in ('operations','transforms','uv_panels','solids'):
                from .native_display import geometry_bounds
                job['bounds']=geometry_bounds(parts)
                return shape,tessellate(shape,parts=parts,bounds=job['bounds'])
            return shape,tessellate(shape)
        future = self.pool.submit(prepare)
        job["future"] = future
        def ready(_):
            try:
                self.prepared.emit(job_id)
            except RuntimeError:
                pass
        future.add_done_callback(ready)
        return {"job_id": job_id}

    def _busy(self):
        return bool(getattr(getattr(self.ctx.window, "processor", None), "busy", False))

    @QtCore.Slot(str)
    def _commit(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job["state"] != "preparing":
            return
        if (self.ctx.scene.layers is not job['document'] or
                (not job.get('reference_job') and self.latest.get(job['identity']) != job_id)):
            job["state"] = "superseded"
            return
        if self._busy() and not job.get('measurement'):
            QtCore.QTimer.singleShot(50, lambda: self._commit(job_id))
            return
        try:
            if 'ungroup_owner' in job:
                from .scene_ungroup import commit
                commit(self, job)
                return
            if job.get('boolean_read'):
                from .scene_boolean import scene_token
                if scene_token(self) != job['scene_token']:
                    job['state'] = 'superseded'
                else:
                    job.update(state='complete', **job['future'].result())
                return
            if job.get('boolean_apply'):
                from .scene_boolean import commit
                commit(self, job)
                return
            if job.get('measurement'):
                if 'fillet_sources' in job:
                    scene = self.ctx.scene
                    if scene.layers is not job['fillet_document'] or any(
                            scene.get(oid) is None or scene.get(oid)._shape is not shape
                            for oid, shape in job['fillet_sources'].items()):
                        raise ValueError('The source geometry changed during Set Edges. Select the edges again.')
                job.update(state='complete', measurements=job['future'].result())
                return
            if job.get('scene_reference_drive'):
                from .scene_reference_drive import commit_reference_drive
                commit_reference_drive(self, job)
                return
            if job.get('move_references'):
                from .move_native import commit_references
                commit_references(self,job_id,job)
                return
            if job.get('reference_job'):
                self.curves.commit_native(job_id, job)
                return
            shape, mesh = job["future"].result()
            scene = self.ctx.scene
            current = self.owner(job["identity"])
            previous = job["owner"]
            if current is None:
                from .scene_boolean import consumed
                from .scene_ungroup import is_detached
                if is_detached(scene, job['identity']):
                    job.update(state='complete', detached=True)
                    return
                if consumed(self, job['identity']):
                    job.update(state='complete', consumed=True)
                    return
            # Attribute edits are allowed during preparation; shape edits,
            # deletion and a changed owner must never be silently overwritten.
            if previous is not None and (current is None or current._shape is not previous._shape):
                raise ValueError("Generated geometry changed in the scene during preparation. Recompute to retry.")
            if previous is None and current is not None:
                raise ValueError("A generated geometry owner appeared during preparation.")
            if job.get('reuse_shape'):
                from .parent_visibility import CLAIMS, claim_text, reconcile
                targets = job['hidden_parents']
                claims_changed = self._json(current, CLAIMS, []) != [list(target) for target in targets]
                if self._json(current, MODEL) != job['model'] or claims_changed:
                    from serpentine3d.core.user_text import with_value
                    snapshot = scene.snapshot()
                    self._checkpoint('Update geometry data structure')
                    try:
                        with scene.batched():
                            text = claim_text(current, targets)
                            scene.update(current.id, user_text=with_value(text, MODEL, json.dumps(job['model'])))
                            if claims_changed:
                                reconcile(self)
                    except Exception:
                        scene.restore(snapshot)
                        history = getattr(self.ctx.window, 'history', None)
                        if history:
                            history.discard_checkpoint()
                        raise
                job.update(state='complete', object_id=current.id)
                return
            snapshot = scene.snapshot()
            self._checkpoint("Update NoodleS geometry")
            from serpentine3d.core.user_text import with_value
            from .parent_visibility import BASELINE, CLAIMS, claim_text, reconcile
            with scene.batched():
                try:
                    if shape is None:
                        if current:
                            self.deleted.remember(job['identity'], current, self._details_for(job['identity'], self._json(current, MODEL)))
                            scene.remove(current.id)
                            if self._json(current, CLAIMS):
                                reconcile(self)
                        job.update(state="complete", object_id=None)
                        return
                    if current:
                        obj = scene.replace_shape(current.id, shape)
                    elif job.get('restore'):
                        obj = self.deleted.restore(job['restore'], shape, mesh)
                    else:
                        obj = scene.add(shape, name=job['name'])
                    targets = job['hidden_parents']
                    claims_changed = self._json(obj, CLAIMS, []) != [list(target) for target in targets]
                    text = with_value(claim_text(obj, targets), OWNER, json.dumps({
                        "project_uuid": job["identity"][0], "node_uuid": job["identity"][1], "output_index": 0}))
                    text = with_value(text, MODEL, json.dumps(job["model"], allow_nan=False))
                    obj = scene.update(obj.id, user_text=text)
                    obj._mesh = mesh  # Serpentine's own CPU DisplayMesh cache, no alternate renderer.
                    if 'bounds' in job:
                        obj._bounds=(shape,job['bounds'])
                    if claims_changed or (current is None and
                                          (targets or self._missing_parent_targets or
                                           self._json(obj, BASELINE) is not None)):
                        reconcile(self)
                    job.update(state="complete", object_id=obj.id)
                except Exception:
                    scene.restore(snapshot)
                    history = getattr(self.ctx.window, "history", None)
                    if history:
                        history.discard_checkpoint()
                    raise
            if job.get('restore'):
                self.deleted.forget(job['identity'], job['restore'])
        except Exception as exc:
            job.update(state="error", error=str(exc))

    @staticmethod
    def _ref_token(identity):
        return ":".join(map(str, identity))

    @staticmethod
    def _point_record(obj, key):
        from serpentine3d.core import geometry as g
        from OCP.TopAbs import TopAbs_VERTEX
        if obj.shape.ShapeType() != TopAbs_VERTEX:
            raise ValueError("Select native Point objects only, not curves, vertices of solids or generated compounds.")
        if not isinstance(key, str) or not key or len(key) > 256 or len(obj.name) > 1000:
            raise ValueError("Invalid native Point reference metadata.")
        return {"key": key, "id": obj.id, "name": obj.name,
                "xyz": [finite(v) for v in g.point_coords(obj.shape)]}

    def capture(self, params):
        identity = self.identity(params)
        if self._busy():
            raise ValueError("Finish the active CAD command before setting Point references.")
        selection = list(self.ctx.window.selection.objects())
        if not selection:
            raise ValueError("Select one or more points in Serpentine first.")
        if len(selection) > 10000 or len({obj.id for obj in selection}) != len(selection):
            raise ValueError("Invalid Point selection.")
        token = self._ref_token(identity)
        records, changes = [], []
        from serpentine3d.core.user_text import with_value
        for obj in selection:
            bindings = self._json(obj, REFERENCES, {})
            if not isinstance(bindings, dict):
                raise ValueError("Invalid Point reference metadata.")
            key = bindings.get(token) or uuid.uuid4().hex
            records.append(self._point_record(obj, key))
            if token not in bindings:
                changes.append((obj.id, with_value(obj.user_text, REFERENCES, json.dumps({**bindings, token: key}))))
        if len({r["key"] for r in records}) != len(records):
            raise ValueError("Selected points have duplicated binding metadata.")
        if changes:
            scene = self.ctx.scene
            snapshot = scene.snapshot()
            self._checkpoint("Set NoodleS Point references")
            with scene.batched():
                try:
                    for oid, text in changes:
                        scene.update(oid, user_text=text)
                except Exception:
                    scene.restore(snapshot)
                    history = getattr(self.ctx.window, "history", None)
                    if history:
                        history.discard_checkpoint()
                    raise
        return self.with_motion({'references':records},identity[0])

    def read(self, params):
        state = normalize_point_state({**params, "mode": "reference"})
        token = self._ref_token(self.identity(params))
        by_key = {}
        for obj in self.ctx.scene.all():
            bindings = self._json(obj, REFERENCES, {})
            if isinstance(bindings, dict) and token in bindings:
                by_key.setdefault(bindings[token], []).append(obj)
        records = []
        for reference in state["references"]:
            candidates = by_key.get(reference["key"], [])
            if len(candidates) != 1:
                raise ValueError("A referenced Point is missing or has duplicated binding metadata. Set references again.")
            records.append(self._point_record(candidates[0], reference["key"]))
        return self.with_motion({'references':records},state['project_uuid'])

    def with_motion(self,result,project):
        from .move_native import applied_motion
        from .rigid_motion import IDENTITY_AXES
        records=[]
        for record in result['references']:
            obj=self.ctx.scene.get(record['id'])
            if obj is None:
                raise ValueError('Referenced geometry disappeared.')
            motion=applied_motion(self,obj,project)
            if motion.axes != IDENTITY_AXES:
                record = {**record, 'move_transform': motion.to_wire()}
            elif any(motion.offset):
                record = {**record, 'move_offset': list(motion.offset)}
            records.append(record)
        return {**result,'references':records}

    def drive(self, params):
        """Move existing native vertices in one transaction, preserving identity.

        Read all axes from the scene immediately before applying the supplied
        coordinate mask. This never writes stale values to undriven axes.
        """
        state = normalize_point_state({**params, "mode": "reference"})
        drive = params.get("drive")
        if not isinstance(drive, dict):
            raise ValueError("Missing Point coordinate updates.")
        axes, updates = drive.get("axes"), drive.get("updates")
        if (not isinstance(axes, list) or not axes or any(a not in ("X", "Y", "Z") for a in axes)
                or len(axes) != len(set(axes))
                or not isinstance(updates, list) or len(updates) > 10000):
            raise ValueError("Invalid Point coordinate updates.")
        allowed = {r["key"] for r in state["references"]}
        patches = {}
        for update in updates:
            if not isinstance(update, dict) or not isinstance(update.get("key"), str):
                raise ValueError("Invalid referenced Point key.")
            key, coordinates = update["key"], update.get("coordinates")
            if key not in allowed or key in patches or not isinstance(coordinates, dict) or set(coordinates) != set(axes):
                raise ValueError("Invalid or repeated referenced Point update.")
            patches[key] = {axis: finite(coordinates[axis]) for axis in axes}
        if self._busy():
            return {"state": "busy"}
        records = self.read(state)["references"]
        from serpentine3d.core import geometry as g
        changes = []
        for record in records:
            if record['key'] not in patches:
                continue
            if 'move_transform' in record:
                from .rigid_motion import from_wire
                motion = from_wire(record['move_transform'])
                desired = list(motion.inverse().point(record['xyz']))
                for axis, value in patches[record['key']].items():
                    desired[('X', 'Y', 'Z').index(axis)] = value
                moved = motion.point(desired)
                if moved != tuple(record['xyz']):
                    changes.append((record['id'], g.make_point(moved)))
                continue
            desired = list(record["xyz"])
            for axis, value in patches.get(record["key"], {}).items():
                index=("X", "Y", "Z").index(axis)
                desired[index] = finite(value+record.get('move_offset',(0.,0.,0.))[index])
            if desired != record["xyz"]:
                changes.append((record["id"], g.make_point(desired)))
        if changes:
            scene = self.ctx.scene
            snapshot = scene.snapshot()
            self._checkpoint("Move NoodleS referenced points")
            with scene.batched():
                try:
                    for oid, shape in changes:
                        scene.replace_shape(oid, shape)
                except Exception:
                    scene.restore(snapshot)
                    history = getattr(self.ctx.window, "history", None)
                    if history:
                        history.discard_checkpoint()
                    raise
        return {"state": "complete", "references": self.read(state)["references"]}


# Compatibility for existing Point integration clients.
PointSceneAdapter = ParametricSceneAdapter
