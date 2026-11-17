"""Latest-value publication, reference drives and live reads off the GUI thread."""
from collections import deque
import copy
import threading
import uuid

from Qt import QtCore

from .bridge import BridgeClient, BridgeError, BridgeRemoteError
from .backend.surface_reference import ARCHIVED_REFERENCE_OPS, surface_reference_request
from .backend.booleans import NATIVE_SCENE_OPERATIONS


class GeometryService(QtCore.QObject):
    result = QtCore.Signal(str, str, object)
    _delivered = QtCore.Signal(int, str, str, object)

    def __init__(self, parent=None, client=None):
        super().__init__(parent)
        self.client = client or BridgeClient(timeout=2)
        self.scene_scope = None
        self.condition = threading.Condition()
        self.models = {}
        self.measurements = {}
        self.removals = {}
        self.references = {}
        self.drives = {}
        self.completed_geometry_drives = {}
        self.unconfirmed_geometry_drives = set()
        self.pending_drives = {}
        self.pending = {}
        self.commands = deque()
        self.dirty = True
        self.generation = 0
        self.stopping = None
        self.active = False
        self.motion_client = str(uuid.uuid4())
        self.motion_targets = {}
        self.motion_resets = {}
        self.motion_request = None
        self.pending_motion = None
        self._delivered.connect(self._receive)

    def _receive(self, generation, node_id, kind, data):
        if generation == self.generation and self.active:
            self.result.emit(node_id, kind, data)

    def start(self, scene_scope=None):
        if self.active:
            return
        self.active = True
        self.scene_scope = scene_scope
        self.generation += 1
        self.stopping = threading.Event()
        with self.condition:
            self.pending.update(self.removals)
            self.pending.update(self.models)
            self.pending.update({key: {'measurement': data} for key, data in self.measurements.items()})
            if self.motion_targets or self.motion_resets:
                self._queue_motion()
            self.pending_drives.update({key: copy.deepcopy(state) for key, state in self.references.items()
                                        if key in self.drives and (key in self.unconfirmed_geometry_drives
                                            or self.completed_geometry_drives.get(key) != self.drives[key])})
            self.dirty = True
        client = self.client.for_scene(scene_scope) if scene_scope else self.client
        for target in (self._work, self._events):
            threading.Thread(target=target, args=(self.generation, self.stopping, client), daemon=True,
                             name="NoodleS-Point-" + target.__name__).start()

    def stop(self):
        self.active = False
        self.generation += 1
        if self.stopping:
            self.stopping.set()
        with self.condition:
            self.commands.clear()
            self.motion_request = self.pending_motion = None
            self.pending_drives.clear()
            self.condition.notify_all()

    def clear_context(self, *, restart=True):
        was_active = self.active
        self.stop()
        with self.condition:
            self.models.clear()
            self.measurements.clear()
            self.removals.clear()
            self.references.clear()
            self.drives.clear()
            self.completed_geometry_drives.clear()
            self.unconfirmed_geometry_drives.clear()
            self.pending_drives.clear()
            self.pending.clear()
            self.commands.clear()
            self.motion_targets.clear()
            self.motion_resets.clear()
            self.dirty = True
        if was_active and restart:
            self.start(self.scene_scope)

    @staticmethod
    def _drive_signature(state):
        drive = state.get("drive")
        if not drive or not drive["updates"]:
            return None
        return (state["project_uuid"], state["node_uuid"],
                tuple(r["key"] for r in state["references"]), drive)

    def sync(self, models, references, measurements=None):
        with self.condition:
            for key, model in models.items():
                self.removals.pop(key, None)
                if self.models.get(key) != model:
                    self.pending[key] = copy.deepcopy(model)
            for key in self.models.keys() - models.keys():
                request = {"remove": self.models[key]["model"]}
                self.removals[key] = request
                self.pending[key] = request
            if {key: tuple(r["key"] for r in state["references"]) for key, state in references.items()} != {
                    key: tuple(r["key"] for r in state["references"]) for key, state in self.references.items()}:
                self.dirty = True
            self.models = copy.deepcopy(models)
            measurements = measurements or {}
            for key, data in measurements.items():
                if self.measurements.get(key) != data:
                    self.pending[key] = {'measurement': copy.deepcopy(data)}
            for key in self.measurements.keys() - measurements.keys():
                previous = self.measurements[key]
                # Join/Explode publish as soon as their measurement resolves.
                # A cancellation for the finished read must not replace that write.
                self.pending.setdefault(key, {'measurement': {
                    name: previous[name] for name in ('method', 'project_uuid', 'node_uuid')}})
            self.measurements = copy.deepcopy(measurements)
            desired = {}
            for key, state in references.items():
                signature = self._drive_signature(state)
                if signature is not None:
                    desired[key] = copy.deepcopy(signature)
                    if self.drives.get(key) != signature:
                        self.pending_drives[key] = copy.deepcopy(state)
            for key in self.drives.keys() - desired.keys():
                previous = self.references[key]
                if not references.get(key, {}).get('drive_paused'):
                    self.completed_geometry_drives.pop(key, None)
                    self.unconfirmed_geometry_drives.discard(key)
                if 'primitive' in previous:
                    self.pending_drives[key] = {**previous, 'drive': {'updates': []}}
                else:
                    self.pending_drives.pop(key, None)
            self.references = copy.deepcopy(references)
            self.drives = desired
            self.condition.notify_all()

    def _geometry_drive_payload(self, key, state, signature):
        params = {name: state[name] for name in ('project_uuid', 'node_uuid', 'primitive', 'mode', 'drive')}
        with self.condition:
            previous = None if key in self.unconfirmed_geometry_drives else self.completed_geometry_drives.get(key)
        if signature and previous and signature[:3] == previous[:3]:
            old_values = {row['key']: row['values'] for row in previous[-1]['updates']}
            updates = []
            for row in state['drive']['updates']:
                old = old_values.get(row['key'], {})
                changed = {port: value for port, value in row['values'].items() if old.get(port) != value}
                if changed:
                    updates.append(row if state['primitive'] == 'interpcurve' else {'key': row['key'], 'values': changed})
            params['drive'] = {'updates': updates}
        return params

    def _finish_geometry_drive(self, generation, key, signature):
        if signature is None:
            return
        with self.condition:
            if self._drive_wanted(generation, key, signature):
                self.completed_geometry_drives[key] = signature
                self.unconfirmed_geometry_drives.discard(key)
                self.dirty = True
                self._emit(generation, key, 'reference_driven',
                           {'node_uuid': signature[1], 'request_keys': signature[2]})

    def _drive_error(self, generation, key, state, message):
        self._emit(generation, key, 'reference_drive_error' if 'primitive' in state else 'error',
                   {'error': str(message), 'node_uuid': state['node_uuid'],
                    'request_keys': tuple(ref['key'] for ref in state['references'])})

    def _drive_wanted(self, generation, key, signature):
        with self.condition:
            return generation == self.generation and self.drives.get(key) == signature

    def _retry_drive(self, generation, key, signature, state):
        with self.condition:
            if self._drive_wanted(generation, key, signature):
                self.pending_drives.setdefault(key, state)

    def sync_movements(self, entries, frozen=()):
        """Full desired frame, including explicit reset after removing a Move."""
        with self.condition:
            desired = {(entry['project_uuid'], entry['id']): copy.deepcopy(entry) for entry in entries}
            for key, entry in self.motion_targets.items():
                if entry['owner'] in frozen:
                    desired[key] = entry
            if desired == self.motion_targets:
                return
            for key, entry in self.motion_targets.items():
                if key not in desired:
                    reset = {**entry, 'offset': [0., 0., 0.], 'reset': True}
                    reset.pop('transform', None)
                    self.motion_resets[key] = reset
            active_bindings = {(entry['project_uuid'], entry['node_uuid'], entry['key'])
                               for entry in desired.values()}
            self.motion_resets = {key: entry for key, entry in self.motion_resets.items()
                                  if key not in desired and
                                  (entry['project_uuid'], entry['node_uuid'], entry['key']) not in active_bindings}
            self.motion_targets = desired
            self._queue_motion()
            self.condition.notify_all()

    def _queue_motion(self):
        self.motion_request = self.pending_motion = {
            'client_uuid': self.motion_client,
            'entries': [*self.motion_targets.values(), *self.motion_resets.values()],
        }

    def _motion_wanted(self, generation, request):
        return generation == self.generation and request is self.motion_request

    def _retry_motion(self, generation, request):
        with self.condition:
            if self._motion_wanted(generation, request):
                self.pending_motion = request

    def _finish_motion(self, generation, request, error=None):
        with self.condition:
            if not self._motion_wanted(generation, request):
                return
            if error is None:
                self.motion_resets.clear()
                self.dirty = True
        for entry in request['entries']:
            if not entry.get('reset'):
                self._emit(generation, entry['node_id'], 'moved' if error is None else 'error',
                           {'reference': True} if error is None else error)

    def _wanted(self, generation, key, params):
        with self.condition:
            if 'measurement' in params:
                return (self.active and generation == self.generation
                        and self.measurements.get(key) == (params['measurement'] if 'plan' in params['measurement'] else None))
            desired = self.removals.get(key) if 'remove' in params else self.models.get(key)
            return self.active and generation == self.generation and desired == params

    def _retry(self, generation, key, params):
        with self.condition:
            if self._wanted(generation, key, params):
                # A newer graph edit always wins over an operation being retried.
                self.pending.setdefault(key, copy.deepcopy(params))

    def _measurement_result(self, generation, key, params, data):
        request = params['measurement']
        if 'signature' in request and self._wanted(generation, key, params):
            result = {'node_uuid': request['node_uuid'], 'signature': request['signature']}
            if 'measurements' in data:
                result['values'] = data['measurements']
            else:
                result['error'] = data.get('error', 'Native measurement failed.')
            self._emit(generation, key, 'measured', result)

    def capture(self, node_id, state):
        if not self.active:
            self.result.emit(node_id, "error", "Connect to Serpentine with the current NoodleSBridge first.")
            return
        with self.condition:
            self.commands.append((node_id, copy.deepcopy(state)))
            self.condition.notify_all()

    def apply_boolean(self, node_id, plan):
        if not self.active:
            self.result.emit(node_id, 'boolean_apply_error', {'error': 'Connect to Serpentine first.'})
            return
        with self.condition:
            self.commands.append((node_id, copy.deepcopy(plan)))
            self.condition.notify_all()

    def ungroup(self, node_id, identity):
        with self.condition:
            self.commands.append((node_id, {**identity, 'ungroup': True}))
            self.condition.notify_all()

    def refresh(self):
        with self.condition:
            self.dirty = True
            self.condition.notify_all()

    def _emit(self, generation, key, kind, data):
        try:
            self._delivered.emit(generation, key, kind, data)
        except RuntimeError:
            pass

    def _events(self, generation, stop, client):
        while not stop.is_set():
            try:
                for event in client.events(stop):
                    if event.get("event") == "scene_changed":
                        self.refresh()
            except BridgeError:
                if stop.wait(1):
                    return

    def _work(self, generation, stop, client):
        jobs = {}
        reference_jobs = {}
        drive_jobs = {}
        motion_jobs = {}
        while not stop.is_set():
            retry_delay = 0.
            with self.condition:
                pending, self.pending = self.pending, {}
                drives, self.pending_drives = self.pending_drives, {}
                commands, self.commands = self.commands, deque()
                dirty, self.dirty = self.dirty, False
                references = copy.deepcopy(self.references) if dirty else {}
                motion, self.pending_motion = self.pending_motion, None
            if motion is not None and self._motion_wanted(generation, motion):
                try:
                    data = client.call('geometry.move_refs', motion)['data']
                    if data['state'] == 'busy':
                        self._retry_motion(generation, motion)
                        retry_delay = max(retry_delay, .05)
                    elif 'job_id' in data:
                        motion_jobs[data['job_id']] = motion
                    else:
                        self._finish_motion(generation, motion)
                except (BridgeError, KeyError, TypeError) as exc:
                    if isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        self._retry_motion(generation, motion)
                        retry_delay = max(retry_delay, .25)
                    else:
                        self._finish_motion(generation, motion, str(exc))
            for key, state in commands:
                if stop.is_set():
                    return
                if state.get('primitive') in NATIVE_SCENE_OPERATIONS or state.get('ungroup'):
                    continue  # Apply after submitting the latest source publications.
                fillet = state.get('primitive') == 'fillet_edge'
                kind = 'fillet_capture' if fillet else 'capture'
                try:
                    family = 'geometry' if 'primitive' in state else 'points'
                    request = surface_reference_request(state) if state.get('primitive') in ARCHIVED_REFERENCE_OPS else state
                    data = client.call(family+'.capture', request)["data"]
                    if 'job_id' in data:
                        reference_jobs[key] = (data['job_id'], state['node_uuid'], kind, state.get('fillet_targets'))
                    else:
                        self._emit(generation, key, kind, {**data, "node_uuid": state["node_uuid"]})
                except BridgeError as exc:
                    if fillet:
                        self._emit(generation, key, 'fillet_capture_error', {'error': str(exc), 'node_uuid': state['node_uuid']})
                    else:
                        self._emit(generation, key, "error", str(exc))
            for key, params in pending.items():
                if stop.is_set():
                    return
                if not self._wanted(generation, key, params):
                    continue
                try:
                    if 'measurement' in params:
                        request = params['measurement']
                        data = client.call(request['method'], request)['data']
                        if 'job_id' in data and self._wanted(generation, key, params):
                            jobs[key] = (data['job_id'], params['measurement']['node_uuid'], params)
                        elif 'plan' not in params['measurement']:
                            jobs.pop(key, None)
                    elif "remove" in params:
                        family = 'geometry' if params['remove'].get('kind') != 'points' else 'points'
                        response = client.call(family+'.remove', params["remove"])['data']
                        if response.get('state') == 'busy':
                            self._retry(generation, key, params)
                            retry_delay = max(retry_delay, .05)
                            continue
                        jobs.pop(key, None)
                    else:
                        family = 'geometry' if params['model'].get('kind') != 'points' else 'points'
                        job = client.call(family+'.prepare', params)["data"]["job_id"]
                        if self._wanted(generation, key, params):
                            jobs[key] = (job, params["model"]["node_uuid"], params)
                            self._emit(generation, key, "publishing", "Preparing native geometry…")
                except (BridgeError, KeyError, TypeError) as exc:
                    if isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        self._retry(generation, key, params)
                        retry_delay = max(retry_delay, .25)
                    elif self._wanted(generation, key, params):
                        if 'measurement' in params:
                            self._measurement_result(generation, key, params, {'error': str(exc)})
                        else:
                            self._emit(generation, key, 'remove_error' if 'remove' in params else 'error', str(exc))
            for key, plan in commands:
                ungroup = plan.get('ungroup')
                if not ungroup and plan.get('primitive') not in NATIVE_SCENE_OPERATIONS:
                    continue
                if stop.is_set():
                    return
                kind = 'ungroup' if ungroup else 'boolean_apply'
                try:
                    params = {k: v for k, v in plan.items() if k != 'ungroup'} if ungroup else plan
                    data = client.call('geometry.' + kind, params)['data']
                    if 'job_id' in data:
                        reference_jobs[key] = (data['job_id'], plan['node_uuid'], kind, None)
                    else:
                        self._emit(generation, key, kind, {**data, 'node_uuid': plan['node_uuid']})
                except (BridgeError, KeyError, TypeError) as exc:
                    self._emit(generation, key, kind + '_error', {'error': str(exc), 'node_uuid': plan['node_uuid']})
                    self.refresh()  # A response can be lost after a native commit.
            for key, state in references.items():
                if stop.is_set():
                    return
                request_keys = tuple(ref['key'] for ref in state['references'])
                try:
                    if key in reference_jobs and reference_jobs[key][2] in ('capture', 'boolean_apply', 'ungroup'):
                        continue
                    if state.get('primitive') in NATIVE_SCENE_OPERATIONS:
                        request = {field: state[field] for field in ('project_uuid', 'node_uuid', 'primitive')}
                        data = client.call('geometry.boolean_read', request)['data']
                        if 'job_id' in data:
                            reference_jobs[key] = (data['job_id'], state['node_uuid'], 'boolean_read', None)
                        else:
                            reference_jobs.pop(key, None)
                            self._emit(generation, key, 'boolean_read', {**data, 'node_uuid': state['node_uuid']})
                        continue
                    family = 'geometry' if 'primitive' in state else 'points'
                    request = surface_reference_request(state) if state.get('primitive') in ARCHIVED_REFERENCE_OPS else state
                    data = client.call(family+'.read', request)["data"]
                    if 'job_id' in data:
                        reference_jobs[key] = (data['job_id'], state['node_uuid'], 'references', request_keys)
                    else:
                        self._emit(generation, key, "references", {**data, "node_uuid": state["node_uuid"]})
                except (BridgeError, KeyError, TypeError) as exc:
                    kind = 'boolean_read_error' if state.get('primitive') in NATIVE_SCENE_OPERATIONS else 'reference_error'
                    self._emit(generation, key, kind,
                               {'error': str(exc), 'request_keys': request_keys, 'node_uuid': state['node_uuid']})
            for key, state in drives.items():
                if stop.is_set():
                    return
                signature = self._drive_signature(state)
                if not self._drive_wanted(generation, key, signature):
                    continue
                geometry = 'primitive' in state
                try:
                    # An unacknowledged write may already have committed, so
                    # changed-port matching is only safe from a confirmed state.
                    params = self._geometry_drive_payload(key, state, signature) if geometry else state
                    data = client.call('geometry.drive' if geometry else 'points.drive', params)['data']
                    if data["state"] == "busy":
                        self._retry_drive(generation, key, signature, state)
                    elif geometry and 'job_id' in data:
                        with self.condition:
                            self.unconfirmed_geometry_drives.add(key)
                        drive_jobs[key] = (data['job_id'], state, signature)
                    elif geometry:
                        drive_jobs.pop(key, None)
                        self._finish_geometry_drive(generation, key, signature)
                    else:
                        self._emit(generation, key, "references", {**data, "node_uuid": state["node_uuid"]})
                except (BridgeError, KeyError, TypeError) as exc:
                    if geometry and isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        with self.condition:
                            self.unconfirmed_geometry_drives.add(key)
                        self._retry_drive(generation, key, signature, state)
                        retry_delay = max(retry_delay, .25)
                    elif signature is not None and self._drive_wanted(generation, key, signature):
                        self._drive_error(generation, key, state, exc)
            for key, (job_id, state, signature) in list(drive_jobs.items()):
                if not self._drive_wanted(generation, key, signature):
                    drive_jobs.pop(key, None)
                    continue
                try:
                    data = client.call('geometry.job', {'job_id': job_id})['data']
                    if data['state'] == 'preparing':
                        continue
                    drive_jobs.pop(key, None)
                    if data['state'] == 'complete':
                        self._finish_geometry_drive(generation, key, signature)
                    elif data['state'] == 'retry':
                        self._retry_drive(generation, key, signature, state)
                    elif data['state'] != 'superseded' and self._drive_wanted(generation, key, signature):
                        self._drive_error(generation, key, state, data.get('error', 'Reference update failed.'))
                except (BridgeError, KeyError, TypeError) as exc:
                    drive_jobs.pop(key, None)
                    if isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        self._retry_drive(generation, key, signature, state)
                        retry_delay = max(retry_delay, .25)
                    elif self._drive_wanted(generation, key, signature):
                        self._drive_error(generation, key, state, exc)
            for key, (job_id, node_uuid, params) in list(jobs.items()):
                if stop.is_set():
                    return
                if not self._wanted(generation, key, params):
                    jobs.pop(key, None)
                    continue
                try:
                    data = client.call("points.job", {"job_id": job_id})["data"]
                    if data["state"] != "preparing":
                        jobs.pop(key, None)
                        if 'measurement' in params:
                            if data['state'] == 'superseded':
                                self._retry(generation, key, params)
                            else:
                                self._measurement_result(generation, key, params, data)
                        else:
                            self._emit(generation, key, "published" if data["state"] == "complete" else "error",
                                       {**data, "node_uuid": node_uuid})
                except (BridgeError, KeyError, TypeError) as exc:
                    jobs.pop(key, None)
                    if 'measurement' in params and isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        self._retry(generation, key, params)
                        retry_delay = max(retry_delay, .25)
                    elif 'measurement' in params:
                        self._measurement_result(generation, key, params, {'error': str(exc)})
                    else:
                        self._emit(generation, key, "error", str(exc))
            for key, (job_id, node_uuid, kind, request_keys) in list(reference_jobs.items()):
                if stop.is_set():
                    return
                try:
                    data = client.call('geometry.job', {'job_id': job_id})['data']
                    if data['state'] == 'preparing':
                        continue
                    reference_jobs.pop(key, None)
                    if kind == 'boolean_apply':
                        self.refresh()
                    if data['state'] == 'complete':
                        self._emit(generation, key, kind, {**data, 'node_uuid': node_uuid, 'request_keys': request_keys})
                    elif data['state'] == 'superseded' and kind in ('references', 'boolean_read'):
                        self.refresh()
                    elif data['state'] != 'superseded' or kind in ('boolean_apply', 'fillet_capture', 'ungroup'):
                        error = data.get('error', 'Ungroup cancelled.' if kind == 'ungroup' else 'Native reference inspection failed.')
                        named_error = kind == 'ungroup' or kind.startswith(('boolean_', 'fillet_'))
                        error_kind = kind + '_error' if named_error else 'error' if kind == 'capture' else 'reference_error'
                        self._emit(generation, key, error_kind,
                                   {'error': error, 'request_keys': request_keys, 'node_uuid': node_uuid})
                except (BridgeError, KeyError, TypeError) as exc:
                    reference_jobs.pop(key, None)
                    if kind == 'boolean_apply':
                        self.refresh()
                    named_error = kind == 'ungroup' or kind.startswith(('boolean_', 'fillet_'))
                    error_kind = kind + '_error' if named_error else 'error' if kind == 'capture' else 'reference_error'
                    self._emit(generation, key, error_kind,
                               {'error': str(exc), 'request_keys': request_keys, 'node_uuid': node_uuid})
            for job_id, motion in list(motion_jobs.items()):
                if not self._motion_wanted(generation, motion):
                    motion_jobs.pop(job_id, None)
                    continue
                try:
                    data = client.call('geometry.job', {'job_id': job_id})['data']
                    if data['state'] == 'preparing':
                        continue
                    motion_jobs.pop(job_id, None)
                    if data['state'] == 'complete':
                        self._finish_motion(generation, motion)
                    elif data['state'] == 'error':
                        error = data.get('error', 'Reference Move failed.')
                        if error == 'Reference geometry changed during Move; retry.':
                            self._retry_motion(generation, motion)
                        else:
                            self._finish_motion(generation, motion, error)
                except (BridgeError, KeyError, TypeError) as exc:
                    motion_jobs.pop(job_id, None)
                    if isinstance(exc, BridgeError) and not isinstance(exc, BridgeRemoteError):
                        self._retry_motion(generation, motion)
                        retry_delay = max(retry_delay, .25)
                    else:
                        self._finish_motion(generation, motion, str(exc))
            with self.condition:
                if retry_delay and not stop.is_set():
                    self.condition.wait(retry_delay)
                elif not self.pending and not self.commands and not self.dirty and not stop.is_set():
                    self.condition.wait(0.03 if jobs or reference_jobs or drive_jobs or motion_jobs or self.pending_drives or self.pending_motion else 2)


# Compatibility with the first Point-only service.
PointService = GeometryService
