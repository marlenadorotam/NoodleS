"""Prepare exact placed solids and combine their native display buffers."""
from collections import OrderedDict
from dataclasses import replace
import math
import time


_POSITION_FIELDS = ('local', 'local_edges', 'local_isos')
_MESH_FIELDS = (*_POSITION_FIELDS, 'normals', 'triangles', 'curvature',
                'face_of_triangle', 'edge_of_segment')


class SolidDisplayCache:
    """Worker-owned cache shared across generated solid publications."""

    def __init__(self):
        self.templates = OrderedDict()
        self.meshes = OrderedDict()
        self.mesh_bytes = 0

    def prepare(self, values, wanted):
        import numpy as np
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
        from OCP.TopLoc import TopLoc_Location
        from OCP.gp import gp_Trsf, gp_Vec
        from serpentine3d.core import geometry, tessellate
        from .primitive_shapes import materialize

        parts, bounds, placements = [], [], []
        used = set()
        deadline = time.perf_counter()

        def yield_to_ui():
            nonlocal deadline
            if not wanted():
                raise ValueError('Publication superseded.')
            if time.perf_counter() >= deadline:
                time.sleep(.001)
                deadline = time.perf_counter() + .004

        for value in values:
            yield_to_ui()
            origin = value.frame.origin
            key = (value.kind, value.dimensions, value.solid, value.frame.axis_x, value.frame.normal)
            template = self.templates.get(key)
            if template is None:
                shape = materialize(replace(value, frame=replace(value.frame, origin=(0., 0., 0.))))
                template = self.templates[key] = (shape, np.asarray(geometry.bbox(shape)))
            self.templates.move_to_end(key)
            if len(self.templates) > 1024:
                self.templates.popitem(last=False)
            shape, box = template
            # Coincident parts still own separate topology and selection indices.
            if (key, origin) in used:
                shape = BRepBuilderAPI_Copy(shape, False, False).Shape()
            used.add((key, origin))
            if any(origin):
                transform = gp_Trsf()
                transform.SetTranslation(gp_Vec(*origin))
                shape = shape.Moved(TopLoc_Location(transform))
            parts.append(shape)
            bounds.append(box + origin)
            placements.append((key, template[0], origin))

        boxes = np.asarray(bounds)
        bounds = tuple(map(tuple, (boxes[:, 0].min(axis=0), boxes[:, 1].max(axis=0))))
        # Round toward finer detail. Tiny edits to the aggregate bounds
        # should keep the same tolerance and reuse unaffected samples.
        native_deflection = max(math.dist(*bounds) * .002, 1e-4)
        deflection = 2 ** (math.floor(4 * math.log2(native_deflection)) / 4)
        curvature = tessellate.curvature_enabled()
        prepared = {}
        meshes = []
        for key, shape, origin in placements:
            yield_to_ui()
            mesh = prepared.get(key)
            if mesh is None:
                mesh = prepared[key] = self._mesh(tessellate, key, shape, deflection, curvature)
            meshes.append((mesh, origin))
        shape = geometry.make_compound(parts)
        return shape, _combine(tessellate, meshes, bounds, curvature, yield_to_ui), bounds

    def _mesh(self, native, key, shape, deflection, curvature):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

        key = (key, deflection, curvature)
        if key in self.meshes:
            self.meshes.move_to_end(key)
            return self.meshes[key][0]
        # OCC's triangulation writes into the topology. Keep published
        # templates free of those mutable caches.
        mesh = native.tessellate(BRepBuilderAPI_Copy(shape, True, False).Shape(), deflection)
        template = (mesh, len(native.geometry.faces_of(shape)), len(native.geometry.edges_of(shape)))
        size = sum(getattr(mesh, name).nbytes for name in _MESH_FIELDS)
        if size <= 64 * 1024**2:
            self.meshes[key] = (template, size)
            self.mesh_bytes += size
            while self.mesh_bytes > 64 * 1024**2 or len(self.meshes) > 1024:
                _, (_, expired) = self.meshes.popitem(last=False)
                self.mesh_bytes -= expired
        return template


def _combine(native, parts, bounds, curvature, yield_to_ui):
    import numpy as np
    from serpentine3d.utils.math3d import origin_between

    mesh = native.DisplayMesh()
    origin = origin_between(*map(np.asarray, bounds))
    if origin is not None:
        mesh.origin = origin
        mesh._far = True
    for field in _MESH_FIELDS:
        empty = getattr(mesh, field)
        count = sum(len(getattr(template[0], field)) for template, _ in parts)
        setattr(mesh, field, np.empty((count, *empty.shape[1:]), dtype=empty.dtype))
    offsets = dict.fromkeys(_MESH_FIELDS, 0)
    face_offset = edge_offset = 0
    for (source, face_count, edge_count), placement in parts:
        yield_to_ui()
        translation = np.asarray(placement) + source.origin - mesh.origin
        vertex_offset = offsets['local']
        for field in _MESH_FIELDS:
            start = offsets[field]
            data = getattr(source, field)
            stop = start + len(data)
            dest = getattr(mesh, field)[start:stop]
            if field in _POSITION_FIELDS:
                np.add(data, translation, out=dest)
            elif field == 'triangles':
                np.add(data, vertex_offset, out=dest)
            elif field == 'face_of_triangle':
                np.add(data, face_offset, out=dest)
            elif field == 'edge_of_segment':
                np.add(data, edge_offset, out=dest)
            else:
                dest[:] = data
            offsets[field] = stop
        face_offset += face_count
        edge_offset += edge_count
    mesh.has_curvature = curvature
    return mesh
