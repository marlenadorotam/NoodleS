"""Explicit native edits, with atomic scene commits and durable result bindings."""
import hashlib
import json
import uuid

from .booleans import BOOLEAN_SPLIT, NATIVE_SCENE_OPERATIONS
from .curves import xyz
from .datatree import Branch
from .fillet_curves import FILLET, checked_radius, fillet_shape


TRANSACTION = 'NoodleS.native_boolean'
RESULT_REFS = 'NoodleS.native_boolean_references'
HISTORY_OP = 'noodles_native_boolean'


def consumed(adapter, identity):
    return any(list(identity[:2]) in record['params'].get('spent', ())
               for record in adapter.ctx.scene.history_records if record.get('op') == HISTORY_OP)


def already_applied(adapter, identity):
    return any(record['params'].get('node') == list(identity[:2])
               for record in adapter.ctx.scene.history_records if record.get('op') == HISTORY_OP)


def scene_token(adapter):
    # Serpentine reuses the Scene instance when opening or clearing a file.
    # Its layer manager is replaced on clear, and retained by ordinary Undo.
    document = adapter.ctx.scene.layers
    token = adapter.boolean_scenes.get(document)
    if token is None:
        token = uuid.uuid4().hex
        adapter.boolean_scenes[document] = token
    return token


def result_rows(adapter, identity, operation):
    rows = []
    for obj in adapter.ctx.scene.all():
        record = adapter._json(obj, TRANSACTION)
        if record and record['node'] == list(identity[:2]):
            if record['primitive'] != operation:
                raise ValueError('The saved native result belongs to a different operation.')
            rows.append((obj, record))
    rows.sort(key=lambda row: row[1]['index'])
    if rows and any(record['count'] != len(rows) or record['index'] != i
                    for i, (_, record) in enumerate(rows)):
        raise ValueError('The native result is incomplete or duplicated in this scene.')
    return rows


def snapshot_result(obj_id, shape, record):
    from serpentine3d.core import geometry as g
    from .surface_reference_native import archive_shape
    result = {'id': obj_id, 'path': record['path'],
              'recipe': archive_shape(shape, record['key'], g.shape_kind(shape)).to_wire()}
    if record['primitive'] == FILLET:
        result.update(radius=record['radius'], corner=record['corner'])
    return result


def check_response_size(records):
    from .surface_reference import MAX_REFERENCE_ARCHIVES
    if sum(len(record['recipe']['brep']) for record in records) > MAX_REFERENCE_ARCHIVES:
        raise ValueError('The native result exceeds the bridge archive size limit.')


def submit_read(adapter, params):
    identity = adapter.identity(params)
    token = scene_token(adapter)
    rows = result_rows(adapter, identity, params['primitive'])
    if not rows:
        return {'state': 'complete', 'records': [], 'consumed': consumed(adapter, identity),
                'missing': already_applied(adapter, identity), 'scene_token': token}
    identity = ('boolean_read', *identity)
    snapshots = [(obj.id, obj._shape, record) for obj, record in rows]
    previous = adapter.jobs.get(adapter.latest.get(identity), {})
    if previous.get('scene_token') == token and previous.get('boolean_snapshots') == snapshots:
        if previous['state'] == 'complete':
            return {'state': 'complete', 'records': previous['records'], 'scene_token': token}
        if previous['state'] == 'preparing':
            return {'job_id': adapter.latest[identity]}

    def prepare(current):
        if not current():
            raise ValueError('Native Boolean read superseded.')
        records = [snapshot_result(oid, shape, record) for oid, shape, record in snapshots]
        check_response_size(records)
        return {'records': records}

    return adapter._submit_worker(identity, prepare, measurement=True, boolean_snapshots=snapshots,
                                  boolean_read=True, scene_token=token)


def submit_apply(adapter, params):
    from .move_native import reference_tags
    from .scene_points import MODEL, OWNER

    identity = adapter.identity(params)
    token = scene_token(adapter)
    if params.get('scene_token') != token:
        raise ValueError('The Serpentine document changed. Wait for the connection to refresh.')
    operation = params['primitive']
    if operation not in NATIVE_SCENE_OPERATIONS:
        raise ValueError('Unknown native operation.')
    fillet = operation == FILLET
    split = operation == BOOLEAN_SPLIT
    update = fillet and params.get('update') is True
    rows = result_rows(adapter, identity, operation)
    if update:
        if not rows:
            raise ValueError('The original Fillet result is missing. Use Undo in Serpentine.')
        return _update_fillet(adapter, params, identity, token, rows)
    if rows:
        return submit_read(adapter, params)
    if consumed(adapter, identity):
        raise ValueError('The native result was used by another operation.')
    if already_applied(adapter, identity):
        raise ValueError('The previous native result is missing. Use Undo in Serpentine.')
    if adapter._busy():
        raise ValueError('Finish the active Serpentine command first.')
    worker_identity = ('boolean_apply', *identity)
    previous = adapter.latest.get(worker_identity)
    if adapter.jobs.get(previous, {}).get('state') == 'preparing':
        return {'job_id': previous}
    raw_rows = params.get('rows')
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= 250:
        raise ValueError('The native operation needs 1–250 result slots.')

    owners, references = {}, {}
    scene = adapter.ctx.scene
    for obj in scene.all():
        owner = adapter._json(obj, OWNER)
        if owner:
            key = (owner['project_uuid'], owner['node_uuid'], owner['output_index'])
            owners.setdefault(key, []).append(obj)
        for tag in reference_tags(adapter, obj):
            references.setdefault(tag, []).append(obj)
    paths, used, spent, retained = set(), set(), set(), set()
    snapshots = []
    for index, row in enumerate(raw_rows):
        path = Branch(tuple(row['path']), ()).path
        targets = row['targets']
        limit = 2 if fillet else 101 if split or operation == 'boolean_difference' else 100
        if (not fillet and not split and path in paths) or not isinstance(targets, list) or not 2 <= len(targets) <= limit:
            raise ValueError('Invalid native operation branch or operand count.')
        paths.add(path)
        sources = []
        row_ids = set()
        for slot, target in enumerate(targets):
            source = adapter.identity(target)
            part = target['key']
            if target['reference']:
                found = references.get((adapter._ref_token(source), part), ())
            else:
                found = owners.get(source, ())
                if adapter.jobs.get(adapter.latest.get(source), {}).get('state') == 'preparing':
                    raise ValueError('Wait for the source geometry to finish publishing.')
            if len(found) != 1:
                raise ValueError('A source is missing, duplicated or still publishing.')
            obj = found[0]
            if not target['reference']:
                model = adapter._json(obj, MODEL, {})
                parts = [item for branch in model.get('branches', ()) for item in branch.get('parts', ())]
                selected = target.get('parts', [part])
                if (not parts or len(parts) != len(selected) or
                        {item['key'] for item in parts} != set(selected)):
                    raise ValueError('The operation needs every part of the source scene object.')
            consumes = not split or slot == 0
            if obj.id in row_ids or obj.id in used or (consumes and obj.id in retained):
                raise ValueError('The operation cannot use one scene object as multiple operands.')
            if (consumes and obj.locked) or not obj.shape_ready:
                raise ValueError('A source is locked or its shape is unavailable.')
            row_ids.add(obj.id)
            sources.append((obj.id, obj._shape, obj.user_text))
            if not consumes:
                retained.add(obj.id)
                continue
            used.add(obj.id)
            owner = adapter._json(obj, OWNER)
            if owner:
                spent.add((owner['project_uuid'], owner['node_uuid']))
            parent = adapter._json(obj, TRANSACTION)
            if parent:
                spent.add(tuple(parent['node']))
        key = hashlib.sha256(json.dumps((path, index) if fillet or split else path).encode()).hexdigest()[:24]
        record = {'node': list(identity[:2]), 'primitive': operation, 'index': index,
                  'count': len(raw_rows), 'key': key, 'path': list(path)}
        if fillet:
            record.update(radius=checked_radius(row['radius']), corner=list(xyz(row['corner'])))
        snapshots.append((sources, record))

    direction = None
    if split:
        processor = getattr(adapter.ctx.window, 'processor', None)
        cplane = getattr(getattr(processor, 'ctx', None), 'cplane', None)
        if cplane is None and (viewport := getattr(adapter.ctx.window, 'viewport', None)) is not None:
            cplane = viewport.active_cplane()
        direction = tuple(map(float, cplane.normal)) if cplane is not None else (0., 0., 1.)
    return _prepare(adapter, worker_identity, token, snapshots, spent, split_direction=direction)


def _update_fillet(adapter, params, identity, token, saved):
    if adapter._busy():
        raise ValueError('Finish the active Serpentine command first.')
    worker_identity = ('boolean_apply', *identity)
    previous = adapter.latest.get(worker_identity)
    if adapter.jobs.get(previous, {}).get('state') == 'preparing':
        return {'job_id': previous}
    rows = params.get('rows')
    if not isinstance(rows, list) or len(rows) != len(saved):
        raise ValueError('Update must keep the original Fillet result slots.')
    snapshots = []
    for row, (obj, record) in zip(rows, saved):
        if row['key'] != record['key'] or row['path'] != record['path'] or obj.locked or not obj.shape_ready:
            raise ValueError('A Fillet result is unavailable or the result layout has changed.')
        snapshots.append(([(obj.id, obj._shape, obj.user_text)], {
            **record, 'radius': checked_radius(row['radius']), 'corner': list(xyz(row['corner'])),
        }))
    return _prepare(adapter, worker_identity, token, snapshots, (), update=True)


def _prepare(adapter, worker_identity, token, snapshots, spent, *, update=False, split_direction=None):
    def prepare(current):
        from .boolean_native import boolean_shape, split_solids
        from .native_display import geometry_bounds, tessellate
        from .surface_reference import SurfaceReferenceValue, MAX_REFERENCE_ARCHIVES
        from .surface_reference_native import archive_shape, materialize_surface
        from serpentine3d.core import geometry as g
        prepared, records = [], []
        for sources, record in snapshots:
            if not current():
                raise ValueError('Native operation superseded.')
            operation = record['primitive']
            shapes = [shape for _, shape, _ in sources]
            if operation == BOOLEAN_SPLIT:
                parts = split_solids(shapes, split_direction)
                for slot, shape in enumerate(parts):
                    if len(prepared) >= 10000:
                        raise ValueError('Boolean Split exceeds the 10000-piece limit.')
                    piece = {**record, 'key': f"{record['key']}:{slot}",
                             'target_index': record['index'], 'index': len(prepared)}
                    bounds = geometry_bounds([shape])
                    prepared.append((shape, tessellate(shape, parts=[shape], bounds=bounds), bounds, piece))
                    records.append(snapshot_result(None, shape, piece))
                continue
            if operation == FILLET:
                if update:
                    originals = record['originals']
                    shapes = [materialize_surface(SurfaceReferenceValue(str(i), archive, 'curve', 0))
                              for i, archive in enumerate(originals)]
                shape = fillet_shape(*shapes, record['radius'], tuple(record['corner']))
                if not update:
                    record['originals'] = [archive_shape(g.unwrap_compound(source), str(i), 'curve').brep
                                           for i, source in enumerate(shapes)]
                    if sum(map(len, record['originals'])) > MAX_REFERENCE_ARCHIVES:
                        raise ValueError('The Fillet source snapshots exceed the archive size limit.')
            else:
                shape = boolean_shape(NATIVE_SCENE_OPERATIONS[operation][0], shapes, solid_only=False)
            bounds = geometry_bounds([shape])
            prepared.append((shape, tessellate(shape, parts=[shape], bounds=bounds), bounds, record))
            records.append(snapshot_result(sources[0][0], shape, record))
        if split_direction is not None:
            for _, _, _, record in prepared:
                record['count'] = len(prepared)
        check_response_size(records)
        return prepared, records

    return adapter._submit_worker(worker_identity, prepare, boolean_apply=True,
                                  boolean_sources=snapshots, boolean_spent=sorted(spent),
                                  native_update=update, scene_token=token)


def commit(adapter, job):
    from serpentine3d.core.user_text import with_value
    from .move_native import MOTION, REFERENCE_FIELDS
    from .parent_visibility import BASELINE, CLAIMS, reconcile
    from .scene_points import MODEL, OWNER

    prepared, records = job['future'].result()
    scene = adapter.ctx.scene
    if scene_token(adapter) != job['scene_token']:
        raise ValueError('The Serpentine document changed during preparation.')
    snapshots = job['boolean_sources']
    split = snapshots[0][1]['primitive'] == BOOLEAN_SPLIT
    for sources, _ in snapshots:
        for slot, (oid, shape, text) in enumerate(sources):
            obj = scene.get(oid)
            if obj is None or obj._shape is not shape or obj.user_text != text or (obj.locked and (not split or slot == 0)):
                raise ValueError('A source changed during preparation. Apply again.')
    scene_snapshot = scene.snapshot()
    update = job['native_update']
    adapter._checkpoint('NoodleS ' + NATIVE_SCENE_OPERATIONS[snapshots[0][1]['primitive']][0])
    visibility_changed = False
    try:
        with scene.batched():
            if split:
                layers = []
                for sources, _ in snapshots:
                    source = scene.get(sources[0][0])
                    visibility_changed |= bool(adapter._json(source, CLAIMS)) or adapter._json(source, BASELINE) is not None
                    layers.append(source.layer_id)
                    scene.remove(source.id)
                for record_index, (shape, mesh, bounds, record) in enumerate(prepared):
                    obj = scene.add(shape, layer_id=layers[record.pop('target_index')])
                    tag = adapter._ref_token((*record['node'], 0))
                    text = with_value(obj.user_text, RESULT_REFS, json.dumps({tag: record['key']}))
                    obj = scene.update(obj.id, user_text=with_value(text, TRANSACTION, json.dumps(record)))
                    obj._mesh, obj._bounds = mesh, (shape, bounds)
                    records[record_index]['id'] = obj.id
            else:
                for (sources, _), (shape, mesh, bounds, record) in zip(snapshots, prepared, strict=True):
                    first = sources[0][0]
                    for oid, _, _ in sources:
                        source = scene.get(oid)
                        visibility_changed |= bool(adapter._json(source, CLAIMS)) or adapter._json(source, BASELINE) is not None
                    for oid, _, _ in sources[1:]:
                        scene.remove(oid)
                    obj = scene.replace_shape(first, shape)
                    text = obj.user_text
                    if not update:
                        for field in (OWNER, MODEL, MOTION, CLAIMS, *REFERENCE_FIELDS):
                            text = with_value(text, field, '')
                        tag = adapter._ref_token((*record['node'], 0))
                        text = with_value(text, RESULT_REFS, json.dumps({tag: record['key']}))
                    text = with_value(text, TRANSACTION, json.dumps(record))
                    obj = scene.update(first, user_text=text)
                    obj._mesh, obj._bounds = mesh, (shape, bounds)
            if visibility_changed:
                reconcile(adapter)
            # An inert document record, like Serpentine's script outputs.
            # It persists even when the result is later deleted, and follows CAD Undo.
            if not update:
                _, first_record = snapshots[0]
                scene.add_record(HISTORY_OP, [], records[0]['id'], node=first_record['node'],
                                 spent=[list(identity) for identity in job['boolean_spent']])
    except Exception:
        scene.restore(scene_snapshot)
        history = getattr(adapter.ctx.window, 'history', None)
        if history:
            history.discard_checkpoint()
        raise
    job.update(state='complete', records=records)
