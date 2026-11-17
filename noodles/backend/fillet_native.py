"""Fillet closed solids using Serpentine's native blend and edge selection."""
import math

from .fillet_edges import MAX_PICKS, MAX_SLOTS, SAMPLE_COUNT, target_key


def _solid(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from serpentine3d.core import geometry as g

    solid = g.unwrap_compound(shape)
    if solid.ShapeType() != TopAbs_SOLID:
        raise ValueError('Fillet Edge needs one closed solid per item.')
    return solid


def _edge_samples(solid, edges):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBndLib import BRepBndLib
    from serpentine3d.core import geometry as g

    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(solid, bounds, False, False)
    x, y, z, xmax, ymax, zmax = bounds.Get()
    low, spans = (x, y, z), (xmax - x, ymax - y, zmax - z)
    result = []
    for edge in edges:
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        coords = [g.pnt_tuple(curve.Value(first + (last - first) * i / (SAMPLE_COUNT - 1)))
                  for i in range(SAMPLE_COUNT)]
        result.append(tuple(tuple((v - origin) / width if width > 1e-10 else 0.5
                                  for v, origin, width in zip(point, low, spans)) for point in coords))
    return result


def _rematch(solid, edges, saved):
    count, marks = saved
    if len(edges) != count:
        raise ValueError('The solid topology changed. Select the edges again.')
    samples = _edge_samples(solid, edges)
    chosen = []
    for mark in marks:
        matches = [i for i, candidate in enumerate(samples)
                   if any(max(math.dist(a, b) for a, b in zip(mark, oriented)) <= 1e-4
                          for oriented in (candidate, candidate[::-1]))]
        if len(matches) != 1 or matches[0] in chosen:
            raise ValueError('A saved edge could not be uniquely matched. Select the edges again.')
        chosen.append(matches[0])
    return [edges[i] for i in chosen]


def _nearest(edges, points):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from serpentine3d.core import geometry as g

    if len(edges) * len(points) > 200_000:
        raise ValueError('Too many Edge Point comparisons. Use Set Edges or fewer points.')
    chosen = {}
    for i, point in enumerate(points, 1):
        vertex = g.make_point(point)
        distances = []
        for index, edge in enumerate(edges):
            distance = BRepExtrema_DistShapeShape(vertex, edge)
            if distance.IsDone() and distance.NbSolution():
                distances.append((distance.Value(), index))
        distances.sort()
        if not distances:
            raise ValueError(f'No measurable edge near Edge Point {i}.')
        if len(distances) > 1 and distances[1][0] - distances[0][0] <= 1e-7:
            raise ValueError(f'Edge Point {i} is equally near multiple edges. Move it toward the middle of the intended edge.')
        index = distances[0][1]
        chosen[index] = edges[index]
    return list(chosen.values())


def fillet_shape(shape, radius, points=(), saved=None):
    from serpentine3d.core import geometry as g
    from .operation_native import checked

    solid = g.copy_shape(_solid(shape))
    edges = None
    if saved is not None or points:
        candidates = g.edges_of(solid)
        edges = _rematch(solid, candidates, saved) if saved is not None else _nearest(candidates, points)
    return checked(_solid(g.fillet_edges(solid, radius, edges=edges))) if radius else solid


def submit_capture(adapter, params):
    from .move_native import reference_tags
    from .scene_points import MODEL, OWNER

    if adapter._busy():
        raise ValueError('Finish the active Serpentine command before setting edges.')
    targets = params.get('fillet_targets')
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_SLOTS:
        raise ValueError('Connect one or more solid sources before setting edges.')
    scene = adapter.ctx.scene
    picks = {}
    for obj_id, kind, index in adapter.ctx.window.selection.subobjects:
        if kind == 'edge':
            picks.setdefault(obj_id, set()).add(index)
    if not picks:
        raise ValueError('Select edges in Serpentine with Ctrl+Shift+click, then click Set Edges.')
    if sum(map(len, picks.values())) > 1000:
        raise ValueError('Set Edges supports up to 1000 selected edges.')
    requests = []
    for target in targets:
        identity = adapter.identity(target)
        part, reference = target['key'], target['reference']
        if not isinstance(part, str) or not 0 < len(part) <= 256 or type(reference) is not bool:
            raise ValueError('Invalid Fillet Edge source.')
        requests.append((identity, part, reference, target_key(target)))
    owners, references = {}, {}
    owner_keys = {identity for identity, _, reference, _ in requests if not reference}
    reference_keys = {(adapter._ref_token(identity), part) for identity, part, reference, _ in requests if reference}
    for obj in scene.all():
        owner = adapter._json(obj, OWNER) if owner_keys else None
        if owner:
            identity = owner['project_uuid'], owner['node_uuid'], owner['output_index']
            if identity in owner_keys:
                owners.setdefault(identity, []).append(obj)
        if reference_keys:
            for tag in set(reference_tags(adapter, obj)) & reference_keys:
                references.setdefault(tag, []).append(obj)
    objects = {}
    for source, part, reference, token in requests:
        if reference:
            matches = references.get((adapter._ref_token(source), part), ())
        else:
            matches = owners.get(source, ())
            if adapter.jobs.get(adapter.latest.get(source), {}).get('state') == 'preparing':
                raise ValueError('Wait for the solid source to finish publishing.')
        obj = matches[0] if len(matches) == 1 else None
        if obj is None or not obj.shape_ready or obj.id not in picks:
            raise ValueError('Select edges on every connected solid source in Serpentine.')
        if obj.id not in objects:
            model = adapter._json(obj, MODEL, {}) if not reference else {}
            parts = tuple(p['key'] for b in model.get('branches', ()) for p in b.get('parts', ()))
            objects[obj.id] = obj._shape, parts, {}
        _, parts, bindings = objects[obj.id]
        if (not reference and part not in parts or reference and parts or part in bindings):
            raise ValueError('Set Edges needs distinct, whole solid parts.')
        bindings[part] = token
    if set(picks) != set(objects):
        raise ValueError('The selection contains edges outside the connected solid sources.')

    def prepare(current):
        result = {}
        for obj_id, (shape, parts, bindings) in objects.items():
            if not current():
                return {}
            result.update(_capture_parts(shape, parts, bindings, picks[obj_id]))
        return result

    return adapter._submit_worker(('fillet_capture', *adapter.identity(params)), prepare, measurement=True,
                                  fillet_sources={oid: obj[0] for oid, obj in objects.items()},
                                  fillet_document=scene.layers)


def _capture_parts(shape, parts, bindings, indices):
    from OCP.TopAbs import TopAbs_COMPOUND
    from serpentine3d.core import geometry as g
    from .grid_reference_native import children

    all_edges = g.edges_of(shape)
    if any(type(i) is not int or not 0 <= i < len(all_edges) for i in indices):
        raise ValueError('The native edge selection is stale. Select the edges again.')
    selected = {hash(all_edges[i]): all_edges[i] for i in indices}
    if parts:
        if shape.ShapeType() != TopAbs_COMPOUND:
            raise ValueError('The published solid assembly has changed. Select the edges again.')
        shapes = tuple(children(shape))
        if len(shapes) != len(parts):
            raise ValueError('The published solid assembly has changed. Select the edges again.')
        part_shapes = dict(zip(parts, shapes))
    else:
        part_shapes = dict.fromkeys(bindings, shape)
    used, records = set(), {}
    for part, key in bindings.items():
        solid = _solid(part_shapes[part])
        edges = g.edges_of(solid)
        matching = [e for e in edges if hash(e) in selected and e.IsSame(selected[hash(e)])]
        if not 1 <= len(matching) <= MAX_PICKS:
            raise ValueError('Select 1–256 edges on each connected solid part.')
        hashes = {hash(edge) for edge in matching}
        if used & hashes:
            raise ValueError('A selected edge belongs to multiple connected solid parts.')
        used.update(hashes)
        records[key] = len(edges), _edge_samples(solid, matching)
        _rematch(solid, edges, records[key])
    if used != set(selected):
        raise ValueError('The selection contains edges outside the connected solid parts.')
    return records
