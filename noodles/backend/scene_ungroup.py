"""Detach a published result into editable native objects in one CAD undo step."""
from .scene_boolean import scene_token


HISTORY_OP = 'noodles_ungroup'


def detached_owners(scene):
    return [owner for record in getattr(scene, 'history_records', ())
            if record.get('op') == HISTORY_OP
            and isinstance(owner := record.get('params', {}).get('owner'), list)
            and len(owner) == 2 and all(isinstance(value, str) for value in owner)]


def is_detached(scene, identity):
    return list(identity[:2]) in detached_owners(scene)


def _native_parts(shape):
    from OCP.TopAbs import TopAbs_COMPOUND
    from OCP.TopoDS import TopoDS_Iterator, TopoDS_Shape

    if not isinstance(shape, TopoDS_Shape) or shape.ShapeType() != TopAbs_COMPOUND:
        yield shape
        return
    children = TopoDS_Iterator(shape, True, True)
    while children.More():
        yield from _native_parts(children.Value())
        children.Next()


def submit(adapter, identity):
    obj = adapter.owner(identity)
    if obj is None:
        raise ValueError('This node has no published ParametricObject in the active Serpentine document.')
    scene = adapter.ctx.scene
    if obj.locked or scene.layers.is_locked(obj.layer_id):
        raise ValueError('Unlock the ParametricObject and its layer before ungrouping.')
    shape = obj.shape

    def prepare(current):
        from serpentine3d.core import geometry
        import time

        parts = []
        deadline = time.perf_counter() + .004
        for part in _native_parts(shape):
            if not current():
                raise ValueError('Ungroup superseded.')
            parts.append((part, geometry.bbox(part)))
            if time.perf_counter() >= deadline:
                time.sleep(.001)
                deadline = time.perf_counter() + .004
        if not parts:
            raise ValueError('The ParametricObject contains no native parts.')
        return parts

    return adapter._submit_worker(('ungroup', *identity), prepare,
                                  ungroup_owner=identity, source_shape=shape,
                                  source_id=obj.id, scene_token=scene_token(adapter))


def commit(adapter, job):
    from .parent_visibility import BASELINE, CLAIMS, reconcile
    from .scene_points import OWNER, MODEL
    from .move_native import MOTION, REFERENCE_FIELDS

    pieces = job['future'].result()
    identity = job['ungroup_owner']
    scene = adapter.ctx.scene
    source = adapter.owner(identity) if scene_token(adapter) == job['scene_token'] else None
    if (source is None or source.id != job['source_id'] or source._shape is not job['source_shape']
            or source.locked or scene.layers.is_locked(source.layer_id)):
        raise ValueError('The source changed during preparation. Ungroup it again.')
    detached_fields = {name.lower() for name in (OWNER, MODEL, MOTION, CLAIMS, BASELINE, *REFERENCE_FIELDS)}
    user_text = {key: value for key, value in (source.user_text or {}).items()
                 if key.lower() not in detached_fields}
    visible = adapter._json(source, BASELINE, source.visible)
    snapshot = scene.snapshot()
    adapter._checkpoint('Ungroup ParametricObject')
    object_ids = []
    try:
        with scene.batched():
            scene.remove(source.id)
            for index, (shape, bounds) in enumerate(pieces, 1):
                name = source.name if len(pieces) == 1 else f'{source.name} {index}'
                obj = scene.add(shape, name=name, layer_id=source.layer_id)
                obj = scene.update(obj.id, color=source.color, material=source.material,
                                   visible=visible, linetype=source.linetype,
                                   print_width=source.print_width, draw_order=source.draw_order,
                                   user_text=user_text or None)
                obj._bounds = (shape, bounds)
                object_ids.append(obj.id)
            # Empty inputs mark a persistent record without native rebuild dependencies.
            scene.add_record(HISTORY_OP, [], object_ids[0], owner=list(identity[:2]))
            if adapter._json(source, CLAIMS) or adapter._json(source, BASELINE) is not None:
                reconcile(adapter)
    except Exception:
        scene.restore(snapshot)
        history = getattr(adapter.ctx.window, 'history', None)
        if history:
            history.discard_checkpoint()
        raise
    job.update(state='complete', ungrouped=len(object_ids))


def register_commands(ctx):
    @ctx.command('ungroupparametric', label='Ungroup Parametric Object', mutates=False)
    def ungroup(c):
        from PySide6.QtCore import QTimer
        from .scene_points import OWNER

        selected = yield ctx.requests().SelectReq('Select a NoodleS ParametricObject', max_count=1)
        adapter = ctx.window._noodles_bridge.geometry
        obj = selected[0]
        try:
            binding = adapter._json(obj, OWNER)
            if not binding or binding.get('output_index') != 0:
                raise ValueError('Select a published NoodleS ParametricObject.')
            job_id = submit(adapter, adapter.identity(binding))['job_id']
        except ValueError as exc:
            c.echo(str(exc))
            return
        c.echo('Preparing native parts…')
        timer = QTimer(ctx.window, interval=100)

        def report():
            job = adapter.jobs.get(job_id, {})
            if job.get('state') == 'preparing':
                return
            timer.stop()
            timer.deleteLater()
            if job.get('state') == 'complete':
                c.echo(f"Ungrouped into {job['ungrouped']} native object(s).")
            else:
                c.echo(job.get('error') or 'Ungroup cancelled.')

        timer.timeout.connect(report)
        timer.start()
