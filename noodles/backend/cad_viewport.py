"""CAD display meshes, prepared off-thread without modifying scene geometry."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
import math
from types import FunctionType
import weakref

from PySide6 import QtCore

from .cad_curve_lod import PIXEL_ERROR, CurveView, deflection_for, level_for
from .viewport_acceleration import plain_brep_types


LOG = logging.getLogger(__name__)


def _minimum_curve_deflection(base_deflection):
    # Bound subdivision at pathological zoom levels or near the eye plane.
    return max(1e-7, base_deflection * 2.5e-4)


@dataclass(frozen=True)
class Quality:
    curve_angle: float = 6.
    curve_scale: float = .35
    surface_angle: float = 12.
    surface_scale: float = .45
    iso_samples: int = 64


def build_mesh(shape, quality, curvature=False, curve_deflection=None):
    import numpy as np
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape
    from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from serpentine3d.core import tessellate as native

    # OCC's mesher and normal calculator both write into the topology's caches.
    # Work on a private copy so the scene and other workers can use the original.
    display_shape = BRepBuilderAPI_Copy(shape, True, False).Shape()
    mesh_occt = native.BRepMesh_IncrementalMesh
    curve_angle = math.radians(quality.curve_angle)
    surface_angle = math.radians(quality.surface_angle)
    base_deflection = native.default_deflection(shape)

    def mesh_faces(shape, deflection, relative, angle, parallel):
        return mesh_occt(shape, deflection * quality.surface_scale, relative, surface_angle, False)

    def edge_polyline(edge, deflection):
        try:
            curve = native.occ.edge_adaptor(edge)
            tolerance = deflection * quality.curve_scale
            if curve_deflection is not None:
                tolerance = min(tolerance, max(_minimum_curve_deflection(base_deflection), curve_deflection))
            sampler = native.GCPnts_TangentialDeflection(curve, curve_angle, tolerance, 2)
            return np.asarray([sampler.Value(i).Coord() for i in range(1, sampler.NbPoints() + 1)])
        except Exception:
            return native._edge_polyline(edge, deflection)

    def face_mesh(face):
        loc = native.TopLoc_Location()
        tri = native.occ.triangulation(face, loc)
        if tri is None or not tri.NbTriangles():
            return None
        trsf = loc.Transformation()
        n = tri.NbNodes()
        verts = np.asarray([tri.Node(i).Transformed(trsf).Coord() for i in range(1, n + 1)])
        indices = np.asarray([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], np.uint32) - 1
        reversed_face = face.Orientation() == TopAbs_REVERSED
        if reversed_face:
            indices = indices[:, ::-1].copy()
        try:
            local_face = TopoDS.Face_s(face.Located(native.TopLoc_Location()).Oriented(TopAbs_FORWARD))
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(local_face, tri)
            normals = np.asarray([tri.Normal(i).Transformed(trsf).Coord() for i in range(1, n + 1)], np.float32)
            if reversed_face:
                normals *= -1
        except Exception:
            normals = native._smooth_normals(verts, indices)
        curv = native._vertex_curvature(face, tri, n, reversed_face) if curvature else np.zeros(n, np.float32)
        return verts, normals, indices, curv

    # Reuse Serpentine's assembly and trim rules with a private namespace.
    # The native tessellator and its settings stay available to the other workers.
    functions = vars(native).copy()
    functions['_ISO_SAMPLES'] = quality.iso_samples
    functions['_CURVATURE'] = curvature
    functions['_face_isocurves'] = FunctionType(native._face_isocurves.__code__, functions)
    functions.update(BRepMesh_IncrementalMesh=mesh_faces, _face_mesh=face_mesh, _edge_polyline=edge_polyline)
    render = FunctionType(native.tessellate.__code__, functions)
    return render(display_shape, base_deflection)


@dataclass
class DisplayVersion:
    shape: object
    mesh: object
    revision: int
    curvature: bool
    level: int | None


class CadViewport(QtCore.QObject):
    finished = QtCore.Signal(object)

    def __init__(self, ctx):
        super().__init__(ctx.window)
        self.ctx = ctx
        self.enabled = False
        self.quality = Quality()
        self.refine_surfaces = False
        self.revision = 0
        self.scene = ctx.scene
        self.watched_scenes = weakref.WeakSet()
        self.queue_key = None
        self.queue = deque()
        self.curves = ()
        self.curves_pending = ()
        self.curve_queue = deque()
        self.curve_views = None
        self.curve_targets = {}
        self.applied = {}
        self.running = False
        self.stopped = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='NoodleS-CAD-Display')
        self.timer = QtCore.QTimer(self, interval=60)
        self.timer.timeout.connect(self._poll)
        self.repaint_timer = QtCore.QTimer(self, interval=16, singleShot=True)
        self.repaint_timer.timeout.connect(self._repaint)
        self.finished.connect(self._deliver, QtCore.Qt.QueuedConnection)
        self._watch_scene(self.scene)

    def state(self):
        return {'enabled': self.enabled, 'high_smooth': self.refine_surfaces, 'revision': self.revision}

    def set_high_smooth(self, enabled):
        self.set_enabled(True, Quality() if enabled else None)

    def set_enabled(self, enabled, quality=None):
        refine_surfaces = enabled and quality is not None
        quality = self.quality if quality is None else quality
        if (enabled, quality, refine_surfaces) == (self.enabled, self.quality, self.refine_surfaces):
            return
        if enabled and self.refine_surfaces and not refine_surfaces:
            self._restore_meshes(self.scene, surfaces_only=True)
        self.enabled, self.quality = enabled, quality
        self.refine_surfaces = refine_surfaces
        self.revision += 1
        if enabled:
            self.timer.start()
            QtCore.QTimer.singleShot(0, self._poll)
        else:
            self.timer.stop()
            self.repaint_timer.stop()
            self.queue.clear()
            self._restore()

    def stop(self):
        if self.stopped:
            return
        self.set_enabled(False)
        self.stopped = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.deleteLater()

    def _panes(self):
        window = self.ctx.window
        return (window.viewport, *getattr(window, 'aux_viewports', ()), *getattr(window, 'dock_viewports', ()))

    def _repaint(self):
        for pane in self._panes():
            try:
                pane._on_tess_done()  # Native GPU-cache epoch, independent of the CAD revision.
            except RuntimeError:
                pass  # A closed auxiliary pane may still have a Python wrapper.

    def _watch_scene(self, scene):
        if scene in self.watched_scenes:
            return
        self.watched_scenes.add(scene)
        owner, watched = weakref.ref(self), weakref.ref(scene)

        def restored():
            adapter, scene = owner(), watched()
            if adapter is not None and scene is not None and not adapter.refine_surfaces and not adapter.stopped:
                adapter._restore_meshes(scene, surfaces_only=adapter.enabled)

        # Scene.restore emits "all". Regular edits and object publications
        # emit "objects" and do not need to scan the meshes from older snapshots.
        scene.add_listener(restored, ('layouts',))

    def _restore_meshes(self, scene, *, surfaces_only=False):
        changed = False
        for key in getattr(scene, '_noodles_cad_mesh_keys', ()):
            obj = scene.get(key)
            if surfaces_only and (obj is None or obj.kind == 'curve'):
                continue
            original = getattr(obj._mesh, '_noodles_native_mesh', None) if obj is not None else None
            if original is not None:
                obj._mesh = original
                changed = True
        if changed and scene is self.ctx.scene:
            self._repaint()

    def _restore(self):
        self._restore_meshes(self.scene)
        self.applied.clear()
        self.queue_key = None
        self.curves = self.curves_pending = ()
        self.curve_queue.clear()
        self.curve_views = None
        self.curve_targets.clear()

    def _poll(self):
        if not self.enabled:
            return
        from serpentine3d.core import tessellate as native

        scene = self.ctx.scene
        if scene is not self.scene:
            self._restore()
            self.scene = scene
            self._watch_scene(scene)
        curvature = native.curvature_enabled()
        key = (scene.revision, self.ctx.window.viewport._visible_layers(), self.revision, curvature)
        panes = self._panes()
        views = tuple(view for pane in panes if (view := CurveView.from_pane(pane)) is not None)
        if not views and any(getattr(pane, 'camera', None) is not None for pane in panes):
            views = None  # There is a native viewport, but no eligible model pane is visible.
        if key != self.queue_key:
            self.queue_key = key
            self.curve_views = None
            for obj_id, version in tuple(self.applied.items()):
                obj = scene.get(obj_id)
                if obj is None or obj._shape is not version.shape or obj._mesh is not version.mesh:
                    del self.applied[obj_id]
            # Native annotations may look like BREP compounds but carry their
            # own rendering data, which an OCC copy would discard.
            brep_types = plain_brep_types()
            shown = tuple(obj for obj in scene.visible_objects()
                          if not obj.shape_ready or type(obj._shape) in brep_types)
            self.curves = tuple(obj for obj in shown if obj.kind == 'curve')
            self.queue = deque((obj.id, None) for obj in shown
                               if self.refine_surfaces and obj.kind in ('surface', 'solid', 'compound'))
        if views != self.curve_views or any(obj.mesh_ready for obj in self.curves_pending):
            self._queue_curves(views)
        self._next()

    def _queue_curves(self, views):
        import numpy as np

        self.curve_views = views
        self.curve_queue.clear()
        self.curve_targets.clear()
        self.curves_pending = ()
        if views is None:
            return
        self.curves_pending = tuple(obj for obj in self.curves if not obj.mesh_ready)
        if not views:
            # A host without a readable model camera uses the fixed CAD preset.
            self.curve_targets.update((obj.id, None) for obj in self.curves if obj.mesh_ready)
            self.curve_queue.extend(self.curve_targets.items())
            return
        ready = []
        boxes = []
        for obj in self.curves:
            if not obj.mesh_ready:
                continue
            # Use a stable source bound even when the current polyline changes.
            original = getattr(obj._mesh, '_noodles_native_mesh', obj._mesh)
            bound = original.bounds()
            if bound is not None:
                ready.append(obj)
                boxes.append(bound)
        if not boxes:
            return
        low, high = np.asarray(boxes, dtype=float).transpose(1, 0, 2)
        center, radius = (low + high) * .5, (high - low) * .5
        # The native tessellation bounds can underestimate exact curve bounds
        # by its model-space deflection. Include it when culling.
        base = np.maximum(.002 * np.linalg.norm(high - low, axis=1), 1e-4)
        radius += base[:, None]
        scales = np.maximum.reduce([view.visible_scales(center, radius) for view in views])
        for obj, scale, deflection in zip(ready, scales, base):
            if not scale:
                continue
            cached = self.applied.get(obj.id)
            floor = _minimum_curve_deflection(deflection)
            scale = min(scale, PIXEL_ERROR / floor)
            level = level_for(scale, cached.level if cached else None)
            if deflection_for(level) >= deflection * self.quality.curve_scale:
                level = None
            self.curve_targets[obj.id] = level
            if not cached or (cached.revision, cached.curvature, cached.level) != (
                    self.revision, self.queue_key[-1], level):
                self.curve_queue.append((obj.id, level))

    def _next(self):
        if self.running or not self.enabled or self.ctx.scene is not self.scene:
            return

        curvature = self.queue_key[-1]
        for queue in (self.curve_queue, self.queue):
            if self._submit_next(queue, curvature):
                return

    def _submit_next(self, queue, curvature):
        brep_types = plain_brep_types()

        for _ in range(len(queue)):
            obj_id, level = queue.popleft()
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            if obj._shape is None or not obj.mesh_ready:
                queue.append((obj_id, level))  # The native viewport prepares the first mesh.
                continue
            if type(obj._shape) not in brep_types:
                continue
            cached = self.applied.get(obj.id)
            if cached and (cached.revision, cached.curvature, cached.level) == (self.revision, curvature, level):
                continue
            request = (self.scene, obj.id, obj._shape, obj._mesh, self.revision, curvature, level)
            self.running = True
            future = self.pool.submit(build_mesh, obj._shape, self.quality, curvature, deflection_for(level))
            future.add_done_callback(lambda done: self._emit(request, done))
            return True
        return False

    def _emit(self, request, future):
        try:
            self.finished.emit((request, future))
        except RuntimeError:
            pass  # The native window closed while a build was running.

    def _deliver(self, result):
        self.running = False
        (scene, key, shape, previous, revision, curvature, level), future = result
        if not self.enabled or revision != self.revision or scene is not self.ctx.scene:
            return
        obj = scene.get(key)
        if obj is None or obj._shape is not shape or obj._mesh is not previous:
            return
        if obj.kind == 'curve' and (key not in self.curve_targets or self.curve_targets[key] != level):
            self._next()
            return
        try:
            display = future.result()
        except Exception:
            LOG.exception('CAD View could not prepare the display mesh')
            return
        display._noodles_native_mesh = getattr(previous, '_noodles_native_mesh', previous)
        if not hasattr(scene, '_noodles_cad_mesh_keys'):
            scene._noodles_cad_mesh_keys = set()
        scene._noodles_cad_mesh_keys.add(key)
        self.applied[key] = DisplayVersion(shape, display, revision, curvature, level)
        obj._mesh = display
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()
        self._next()


def register_commands(ctx, viewport):
    @ctx.command('cadview', aliases=('cv',), label='CAD View', mutates=False)
    def enable(c):
        viewport.set_enabled(True)
        c.echo('CAD View enabled with adaptive curves.')
        if False:
            yield

    @ctx.command('cadnative', aliases=('cvn',), label='CAD View Native', mutates=False)
    def disable(c):
        viewport.set_enabled(False)
        c.echo('Native Serpentine3D viewport restored.')
        if False:
            yield

    @ctx.command('cadquality', aliases=('cadq',), label='CAD Quality', mutates=False)
    def quality(c):
        q = viewport.quality
        req = ctx.requests().NumberReq
        ca = yield req('Curve angular deflection in degrees', default=q.curve_angle, minimum=.05)
        cl = yield req('Curve linear deflection scale', default=q.curve_scale, minimum=.01)
        sa = yield req('Surface angular deflection in degrees', default=q.surface_angle, minimum=.1)
        sl = yield req('Surface linear deflection scale', default=q.surface_scale, minimum=.005)
        iso = yield req('Surface isocurve samples', default=q.iso_samples, minimum=12)
        if not all(map(math.isfinite, (ca, cl, sa, sl, iso))) or ca > 180 or sa > 180 or iso > 512:
            c.echo('Use finite quality settings, angles up to 180° and up to 512 isocurve samples.')
            return
        viewport.set_enabled(True, Quality(ca, cl, sa, sl, int(iso)))
        c.echo('CAD View quality updated. Preparing refined surfaces.')
