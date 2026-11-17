"""Native OCC construction and read-only reference interrogation for curve recipes."""
import json
import math
import uuid
from collections import OrderedDict

from .curves import (PlaneValue, add, sub, cross, unit, circle, ellipse, arc, arc_center, line,
                     polyline, rectangle, curve_from_wire)
from .geometry import normalize_geometry_state
from .curve_collection import CURVES
from .mesh_nodes import MAX_MESH_ELEMENTS, MESH, mesh_from_wire
from .solids import SOLID_SPECS
from .grids import GRID_SPECS
from .grid_reference_native import GRID_REFERENCES, grid_records, inspect_grid
from .surface_reference import ARCHIVED_REFERENCE_OPS, MAX_REFERENCE_ARCHIVES, MAX_REFERENCE_OBJECTS, SurfaceReferenceValue

REFERENCES = 'NoodleS.curve_references'
SOLID_REFERENCES = 'NoodleS.geometry_references'


def materialize(value, *, resolve=None, topology_cache=None):
    from serpentine3d.core import geometry as g
    from .solids import SolidValue
    from .grids import GridValue
    from .operations import OperationValue
    from .point import PointValue
    from .moves import TranslatedValue,RigidValue,GridEditValue
    if isinstance(value, SurfaceReferenceValue):
        from .surface_reference_native import materialize_surface
        return materialize_surface(value)
    if isinstance(value,PointValue):
        return g.make_point(value.xyz)
    if isinstance(value,(TranslatedValue,RigidValue,GridEditValue)):
        from .move_native import materialize as native_move
        return native_move(value,resolve or materialize)
    if isinstance(value,OperationValue):
        from .topology_operations import TOPOLOGY_SOURCE_LIMITS
        if value.kind in TOPOLOGY_SOURCE_LIMITS:
            from .topology_native import materialize_piece
            return materialize_piece(value, resolve or materialize, topology_cache)
        from .operation_native import materialize as operation_shape
        return operation_shape(value,resolve or materialize,topology_cache)
    if isinstance(value, GridValue):
        from .grid_native import materialize as grid_shape
        return grid_shape(value)
    if value.kind == 'wire':
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
        from OCP.TopoDS import TopoDS
        wire = BRepBuilderAPI_MakeWire()
        for segment, reverse in zip(value.segments,value.reversed_edges):
            edge = materialize(segment)
            wire.Add(TopoDS.Edge_s(edge.Reversed()) if reverse else edge)
        if not wire.IsDone():
            raise ValueError('OpenCascade could not build the cell boundary.')
        return wire.Wire()
    if isinstance(value, SolidValue):
        from .primitive_shapes import materialize as materialize_primitive
        return materialize_primitive(value)
    if value.kind in ('curve', 'interpcurve'):
        from .spline_native import materialize_spline
        return materialize_spline(value)
    if value.kind == 'circle':
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Circ
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        frame = value.frame
        return BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(*frame.origin), gp_Dir(*frame.normal), gp_Dir(*frame.axis_x)), value.radius)).Edge()
    if value.kind == 'line':
        return g.make_line(*value.points)
    if value.kind == 'ellipse':
        return g.make_ellipse_axis(value.frame.origin, value.frame.axis_x,
                                   *value.dimensions, value.frame.normal)
    if value.kind == 'arc':
        return g.make_arc_3pt(*value.points)
    return g.make_polyline(list(value.points), closed=value.closed)


def inspect_curve(obj, key, primitive):
    from serpentine3d.core import geometry as g
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line
    shape = obj.shape
    expected = 'arc' if primitive == 'arc_center' else primitive
    value = None
    if expected == 'ellipse' and shape.ShapeType() == TopAbs_WIRE:
        edges = g.edges_of(shape)
        if len(edges) == 1:
            shape = edges[0]
    if expected in ('curve', 'interpcurve'):
        from .spline_native import describe_spline
        value = describe_spline(shape, key, expected)
    if shape.ShapeType() == TopAbs_EDGE:
        edge = TopoDS.Edge_s(shape)
        adaptor = BRepAdaptor_Curve(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        if edge.Orientation() == TopAbs_REVERSED:
            first, last = last, first
        if adaptor.GetType() == GeomAbs_Circle:
            native = adaptor.Circle()
            frame = PlaneValue(g.pnt_tuple(native.Location()), g.pnt_tuple(native.XAxis().Direction()),
                               g.pnt_tuple(native.Axis().Direction()))
            full = abs(abs(last-first)-2*math.pi) < 1e-7
            if full and expected == 'circle':
                value = circle(key, frame.origin, native.Radius(), frame)
            elif full and expected == 'ellipse':
                value = ellipse(key, frame.origin, native.Radius(), native.Radius(), frame)
            elif not full and expected == 'arc':
                if primitive == 'arc_center':
                    start = g.pnt_tuple(adaptor.Value(first))
                    frame = PlaneValue(frame.origin, sub(start, frame.origin), frame.normal)
                    value = arc_center(key, frame.origin, native.Radius(), math.degrees(last-first), frame)
                else:
                    lo, hi = sorted((first, last))
                    seam = math.ceil(lo / math.tau) * math.tau
                    # A Reference edit places the underlying circle seam at
                    # the supplied through-point. With no interior seam use
                    # a canonical point halfway along the native arc.
                    through = seam if lo+1e-9 < seam < hi-1e-9 else (first+last)/2
                    value = arc(key, *(g.pnt_tuple(adaptor.Value(t)) for t in (first, through, last)))
        elif adaptor.GetType() == GeomAbs_Ellipse and expected == 'ellipse':
            if abs(abs(last-first)-2*math.pi) < 1e-7:
                native = adaptor.Ellipse()
                frame = PlaneValue(g.pnt_tuple(native.Location()), g.pnt_tuple(native.XAxis().Direction()),
                                   g.pnt_tuple(native.Axis().Direction()))
                if abs(adaptor.FirstParameter() % (2*math.pi) - 1.5*math.pi) < 1e-8:
                    frame = PlaneValue(frame.origin, sub(g.pnt_tuple(adaptor.Value(adaptor.FirstParameter())),
                                                         frame.origin), frame.normal)
                    value = ellipse(key, frame.origin, native.MinorRadius(), native.MajorRadius(), frame)
                else:
                    value = ellipse(key, frame.origin, native.MajorRadius(), native.MinorRadius(), frame)
        elif adaptor.GetType() == GeomAbs_BSplineCurve and expected == 'ellipse':
            from .ellipse_reference_native import inspect_rational_ellipse
            result = inspect_rational_ellipse(obj.shape)
            if result is not None:
                frame, radii = result
                value = ellipse(key, frame.origin, *radii, frame)
        elif adaptor.GetType() == GeomAbs_Line and expected == 'line':
            value = line(key, g.pnt_tuple(adaptor.Value(first)), g.pnt_tuple(adaptor.Value(last)))
    elif shape.ShapeType() == TopAbs_WIRE and expected in ('rectangle', 'polyline'):
        points, closed = g._wire_points(shape)
        if expected == 'polyline':
            value = polyline(key, points, closed)
        elif closed and len(points) == 4:
            center = tuple(sum(p[k] for p in points)/4 for k in range(3))
            frame = PlaneValue(center, sub(points[1], points[0]), cross(sub(points[1], points[0]), sub(points[2], points[1])))
            value = rectangle(key, math.dist(points[0], points[1]), math.dist(points[1], points[2]), center, frame)
            if any(math.dist(a, b) > 1e-6 for a, b in zip(value.points, points)):
                value = None
    if value is None:
        if expected == 'ellipse':
            raise ValueError('Select complete ellipse or circle objects. Elliptical arcs, other splines and generated compounds are not accepted.')
        raise ValueError('Select native '+expected+' objects only. The source may have changed type; generated compounds and subobjects are not accepted.')
    if len(obj.name) > 1000:
        raise ValueError('Reference name is too long.')
    return {'key': key, 'id': obj.id, 'name': obj.name, 'recipe': value.to_wire()}


class CurveReferences:
    def __init__(self, publisher):
        self.publisher = publisher
        self.inspections = OrderedDict()
        self.grid_inspections = OrderedDict()
        self.surface_inspections = OrderedDict()
        self.latest = {}

    def bound_sources(self, identity, keys, metadata):
        """Resolve captured keys on Qt, rejecting missing or duplicate tags."""
        adapter = self.publisher
        token = adapter._ref_token(identity)
        by_key = {}
        for obj in adapter.ctx.scene.all():
            bindings = adapter._json(obj, metadata, {})
            if isinstance(bindings, dict) and token in bindings:
                by_key.setdefault(bindings[token], []).append(obj)
        sources = []
        for key in keys:
            matches = by_key.get(key, [])
            if len(matches) != 1:
                raise ValueError('A reference is missing or has duplicate binding metadata. Set references again.')
            sources.append((matches[0], key))
        return sources

    def grid_model(self, snapshot, primitive):
        key = snapshot.id, primitive
        cached = self.grid_inspections.get(key)
        if cached is None or cached[0] is not snapshot.shape or cached[1] != snapshot.manifest:
            cached = snapshot.shape, snapshot.manifest, inspect_grid(snapshot.shape, snapshot.manifest, primitive)
            self.grid_inspections[key] = cached
        self.grid_inspections.move_to_end(key)
        if len(self.grid_inspections) > 32:
            self.grid_inspections.popitem(last=False)
        return cached[2]

    def defer_native(self, params, capture):
        """Snapshot source handles on Qt and inspect them on the common OCC worker."""
        from types import SimpleNamespace
        from .solid_native import inspect_solid
        from .scene_points import MODEL
        adapter = self.publisher
        primitive = params['primitive']
        archived = primitive in ARCHIVED_REFERENCE_OPS
        curves = primitive == CURVES
        mesh = primitive == MESH
        label = 'mesh' if mesh else 'curve' if curves else 'surface'
        state = params if archived else normalize_geometry_state(primitive, params)
        identity = adapter.identity(state)
        if archived and state.get('mode') != 'reference':
            raise ValueError('Switch the node to Reference mode.')
        if capture and adapter._busy():
            raise ValueError('Finish the active CAD command before setting references.')
        token = adapter._ref_token(identity)
        grid = primitive in GRID_SPECS
        metadata = GRID_REFERENCES if grid else REFERENCES if curves else SOLID_REFERENCES
        sources = []
        if capture:
            selection = adapter.ctx.window.selection
            if archived and getattr(selection, 'subobjects', ()):
                raise ValueError(f'Select whole {label} objects in Serpentine, then click Set reference.')
            objects = list(selection.objects())
            limit = MAX_REFERENCE_OBJECTS if archived else 10000
            if archived and len(objects) > limit:
                raise ValueError(f'Select up to {limit} {label} objects per node.')
            if not objects or len(objects) > limit or len({o.id for o in objects}) != len(objects):
                raise ValueError('Select one or more matching native primitives first.')
            for obj in objects:
                bindings = adapter._json(obj, metadata, {})
                if not isinstance(bindings, dict):
                    raise ValueError('Invalid geometry binding metadata.')
                sources.append((obj, bindings.get(token) or uuid.uuid4().hex))
        else:
            if archived and (not isinstance(state.get('references'), list)
                            or not 1 <= len(state['references']) <= MAX_REFERENCE_OBJECTS
                            or any(not isinstance(r, dict) or not isinstance(r.get('key'), str)
                                   or not 0 < len(r['key']) <= 256 for r in state['references'])):
                raise ValueError(f'Invalid {label} reference keys.')
            keys = (ref['key'].split('/', 1)[0] if grid else ref['key'] for ref in state['references'])
            sources = self.bound_sources(identity, dict.fromkeys(keys), metadata)
        if len({key for _, key in sources}) != len(sources):
            raise ValueError('Duplicate primitive reference keys.')
        snapshots = [(SimpleNamespace(id=obj.id, name=obj.name, kind=obj.kind, shape=obj._shape, user_text=obj.user_text,
                                     manifest=adapter._json(obj, MODEL) if grid else None), key) for obj, key in sources]
        if any(not isinstance(obj.name, str) or len(obj.name) > 1000 for obj, _ in snapshots):
            raise ValueError('Reference name is too long.')
        previous = adapter.jobs.get(self.latest.get(identity))
        if previous and previous['state'] == 'preparing':
            previous['state'] = 'superseded'
            previous['future'].cancel()
        job_id = uuid.uuid4().hex
        job = {'state': 'preparing', 'reference_job': True, 'capture': capture, 'identity': identity,
               'scene': adapter.ctx.scene, 'document': adapter.ctx.scene.layers,
               'sources': snapshots, 'metadata': metadata, 'token': token,
               'archived': archived, 'primitive': primitive}
        self.latest[identity] = job_id
        adapter.jobs[job_id] = job
        if len(adapter.jobs) > 128:
            for key in list(adapter.jobs):
                if adapter.jobs[key]['state'] != 'preparing':
                    adapter.jobs.pop(key)
                if len(adapter.jobs) <= 64:
                    break
        def inspect():
            records = []
            archive_size = 0
            for obj, key in snapshots:
                if self.latest.get(identity) != job_id:
                    return []
                if grid:
                    records.append(grid_records(self.grid_model(obj, primitive), obj, key))
                elif archived:
                    from .surface_reference_native import inspect_archived_curve, inspect_surface
                    cache_key = obj.id, primitive
                    cached = self.surface_inspections.get(cache_key)
                    if cached is None or cached[0] is not obj.shape:
                        if mesh:
                            from serpentine3d.core.mesh import MeshShape
                            if not isinstance(obj.shape, MeshShape):
                                raise ValueError('Select whole native mesh objects in Serpentine.')
                            if max(len(obj.shape.vertices), len(obj.shape.triangles)) > MAX_MESH_ELEMENTS:
                                raise ValueError(f'Mesh supports up to {MAX_MESH_ELEMENTS:,} vertices and triangles per object.')
                            shape = obj.shape
                            data = {'key': key, 'kind': MESH, 'vertices': shape.vertices.tolist(),
                                    'triangles': shape.triangles.tolist()}
                            if shape.normals is not None and len(shape.normals) == len(shape.vertices):
                                data['normals'] = shape.normals.tolist()
                            value = mesh_from_wire(data)
                        else:
                            value = inspect_archived_curve(obj.shape, key) if curves else inspect_surface(obj.shape, key, primitive)
                        cached = obj.shape, value
                        self.surface_inspections[cache_key] = cached
                    self.surface_inspections.move_to_end(cache_key)
                    while len(self.surface_inspections) > MAX_REFERENCE_OBJECTS:
                        self.surface_inspections.popitem(last=False)
                    recipe = cached[1].to_wire()
                    recipe['key'] = key
                    archive_size += len(json.dumps(recipe)) if mesh else len(recipe['brep'])
                    if archive_size > MAX_REFERENCE_ARCHIVES:
                        raise ValueError(f'{label.title()} reference archives are too large. Capture fewer objects per node.')
                    records.append([{'key': key, 'id': obj.id, 'recipe': recipe}])
                else:
                    records.append([inspect_solid(obj, key, primitive)])
            if grid and not capture:
                if [r['key'] for group in records for r in group] != [r['key'] for r in state['references']]:
                    raise ValueError('The grid slots changed. Set references again.')
            return records
        future = adapter.pool.submit(inspect)
        job['future'] = future
        def ready(_):
            try:
                adapter.prepared.emit(job_id)
            except RuntimeError:
                pass
        future.add_done_callback(ready)
        return {'job_id': job_id}

    def commit_native(self, job_id, job):
        adapter = self.publisher
        if self.latest.get(job['identity']) != job_id or adapter.ctx.scene is not job['scene']:
            job['state'] = 'superseded'
            return
        records = job['future'].result()
        from serpentine3d.core.user_text import value_of, with_value
        from .primitive_shapes import HEIGHT_SIGN_KEYS
        height_sign_key = HEIGHT_SIGN_KEYS.get(job['primitive'])
        changes = []
        if not job['capture']:
            by_key = {}
            for source in adapter.ctx.scene.all():
                bindings = adapter._json(source, job['metadata'], {})
                if isinstance(bindings, dict) and job['token'] in bindings:
                    by_key.setdefault(bindings[job['token']], []).append(source.id)
            if any(by_key.get(key) != [source.id] for source, key in job['sources']):
                raise ValueError('A reference is missing or has duplicate binding metadata. Set references again.')
        for group, (snapshot, key) in zip(records, job['sources']):
            obj = adapter.ctx.scene.get(snapshot.id)
            if obj is None:
                raise ValueError('A referenced primitive is missing.')
            if obj._shape is not snapshot.shape or (
                    height_sign_key and value_of(obj.user_text, height_sign_key) !=
                    value_of(snapshot.user_text, height_sign_key)):
                if job['capture']:
                    raise ValueError('Geometry changed while setting references. Set references again.')
                job['state'] = 'superseded'
                return
            for record in group:
                record['name'] = obj.name
            if not isinstance(obj.name, str) or len(obj.name) > 1000:
                raise ValueError('Reference name is too long.')
            bindings = adapter._json(obj, job['metadata'], {})
            if not isinstance(bindings, dict):
                raise ValueError('Invalid geometry binding metadata.')
            if job['capture']:
                if job['token'] in bindings and bindings[job['token']] != key:
                    raise ValueError('Reference binding changed during capture.')
                if job['token'] not in bindings:
                    changes.append((obj.id, with_value(obj.user_text, job['metadata'], json.dumps({**bindings, job['token']: key}))))
            elif bindings.get(job['token']) != key:
                raise ValueError('Reference binding changed during inspection.')
        flat = [record for group in records for record in group]
        if job['archived']:
            payload_size = sum((len(recipe['brep']) if 'brep' in recipe else len(json.dumps(recipe)))
                               + len(json.dumps(record['name'])) + 512
                               for record in flat for recipe in (record['recipe'],))
            if payload_size > 950_000:
                raise ValueError('Geometry reference response is too large. Capture fewer objects per node.')
        if changes:
            scene = adapter.ctx.scene
            snapshot = scene.snapshot()
            adapter._checkpoint('Set NoodleS geometry references')
            with scene.batched():
                try:
                    for oid, text in changes:
                        scene.update(oid, user_text=text)
                except Exception:
                    scene.restore(snapshot)
                    history = getattr(adapter.ctx.window, 'history', None)
                    if history:
                        history.discard_checkpoint()
                    raise
        job.update(state='complete', references=adapter.with_motion({'references':flat},job['identity'][0])['references'])

    def inspect(self, obj, key, primitive):
        if primitive not in ('curve', 'interpcurve'):
            return inspect_curve(obj, key, primitive)
        # Snapshot topology/poles on Qt; expensive length integration is queued on
        # the same native worker as Generate. Mouse motion replaces queued work.
        from .spline_native import describe_spline
        cache_key = primitive+':'+obj.id
        cached = self.inspections.get(cache_key)
        if cached is None or cached['shape'] is not obj._shape:
            if cached:
                cached['future'].cancel()
            recipe = describe_spline(obj.shape, key, primitive, measure=False).to_wire()
            shape = obj._shape
            future = self.publisher.pool.submit(lambda: describe_spline(shape, key, primitive).to_wire())
            cached = {'shape': shape, 'recipe': recipe, 'future': future}
            self.inspections[cache_key] = cached
            def ready(done):
                try:
                    self.publisher.reference_prepared.emit(cache_key, done)
                except RuntimeError:
                    pass
            future.add_done_callback(ready)
        self.inspections.move_to_end(cache_key)
        while len(self.inspections) > 10000:
            _, expired = self.inspections.popitem(last=False)
            expired['future'].cancel()
        if 'error' in cached:
            raise ValueError(cached['error'])
        return {'key': key, 'id': obj.id, 'name': obj.name,
                'recipe': {**cached['recipe'], 'key': key}}

    def prepared(self, cache_key, future):
        cached = self.inspections.get(cache_key)
        if cached is None or cached['future'] is not future or future.cancelled():
            return
        try:
            cached['recipe'] = future.result()
        except Exception as exc:
            cached['error'] = str(exc)
        self.publisher.references_updated.emit()

    def capture(self, params):
        if params['primitive'] in SOLID_SPECS or params['primitive'] in GRID_SPECS or params['primitive'] in ARCHIVED_REFERENCE_OPS:
            return self.defer_native(params, True)
        adapter = self.publisher
        primitive = params['primitive']
        state=normalize_geometry_state(primitive, params)
        identity = adapter.identity(params)
        if adapter._busy():
            raise ValueError('Finish the active CAD command before setting references.')
        selection = list(adapter.ctx.window.selection.objects())
        if not selection or len(selection) > 10000 or len({o.id for o in selection}) != len(selection):
            raise ValueError('Select one or more matching native curves in Serpentine first.')
        token = adapter._ref_token(identity)
        records, changes = [], []
        from serpentine3d.core.user_text import with_value
        for obj in selection:
            bindings = adapter._json(obj, REFERENCES, {})
            if not isinstance(bindings, dict):
                raise ValueError('Invalid curve binding metadata.')
            key = bindings.get(token) or uuid.uuid4().hex
            records.append(self.inspect(obj, key, primitive))
            if token not in bindings:
                changes.append((obj.id, with_value(obj.user_text, REFERENCES, json.dumps({**bindings, token: key}))))
        if len({r['key'] for r in records}) != len(records):
            raise ValueError('Selected curves have duplicate binding metadata.')
        if changes:
            scene = adapter.ctx.scene
            snapshot = scene.snapshot()
            adapter._checkpoint('Set NoodleS curve references')
            with scene.batched():
                try:
                    for oid, text in changes:
                        scene.update(oid, user_text=text)
                except Exception:
                    scene.restore(snapshot)
                    history = getattr(adapter.ctx.window, 'history', None)
                    if history:
                        history.discard_checkpoint()
                    raise
        return adapter.with_motion({'references':records},state['project_uuid'])

    def read(self, params):
        if params['primitive'] in SOLID_SPECS or params['primitive'] in GRID_SPECS or params['primitive'] in ARCHIVED_REFERENCE_OPS:
            return self.defer_native(params, False)
        adapter = self.publisher
        primitive = params['primitive']
        state = normalize_geometry_state(primitive, params)
        token = adapter._ref_token(adapter.identity(params))
        by_key = {}
        for obj in adapter.ctx.scene.all():
            bindings = adapter._json(obj, REFERENCES, {})
            if isinstance(bindings, dict) and token in bindings:
                by_key.setdefault(bindings[token], []).append(obj)
        records = []
        for ref in state['references']:
            matches = by_key.get(ref['key'], [])
            if len(matches) != 1:
                raise ValueError('A referenced curve is missing or has duplicate binding metadata. Set references again.')
            records.append(self.inspect(matches[0], ref['key'], primitive))
        return adapter.with_motion({'references':records},state['project_uuid'])
