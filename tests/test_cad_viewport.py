"""CAD display stays separate from model geometry and graph evaluation."""
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_point_native import NativePointTests as NativeFixture
from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.cad_viewport import CadViewport, Quality, build_mesh, register_commands
from noodles.backend.viewport_acceleration import install_classification
from noodles.window import MainWindow


class CadViewportTests(unittest.TestCase):
    setUpClass = classmethod(NativeFixture.setUpClass.__func__)
    setUp = NativeFixture.setUp
    tearDown = NativeFixture.tearDown
    wait_for = NativeFixture.wait_for

    def test_cad_modes_preserve_native_annotations(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus
        from serpentine3d.core.hatch import HatchShape
        from serpentine3d.core.text_object import TextShape

        scene = self.window.scene
        text = TextShape("NoodleS", 2, "sans")
        rectangle = self.geo.make_rectangle((0, 0, 0), (10, 10, 0))
        annotations = [
            scene.add(text),
            scene.add(HatchShape(self.geo.planar_face(rectangle), pattern="solid")),
        ]
        if find_spec("serpentine3d.core.dimension") is not None:
            from serpentine3d.core.dimension import DimensionShape
            annotations.append(scene.add(DimensionShape((0, 0, 0), (10, 0, 0), (0, 3, 0))))

        original_meshes = [obj.mesh for obj in annotations]
        if hasattr(TextShape, "fill"):
            self.assertGreater(len(original_meshes[0].triangles), 0)
        circle = scene.add(self.geo.make_circle((0., 0., 0.), 3.))
        torus = scene.add(BRepPrimAPI_MakeTorus(20., 6.).Shape())
        circle_mesh, torus_mesh = circle.mesh, torus.mesh
        revision = scene.revision

        self.window.viewport = SimpleNamespace(_visible_layers=lambda: (), _on_tess_done=lambda: None)
        adapter = self.bridge.cad_viewport = CadViewport(self.ctx)
        adapter.set_enabled(True)
        self.wait_for(lambda: circle.mesh is not circle_mesh)
        for obj, original in zip(annotations, original_meshes):
            self.assertIs(obj.mesh, original)
            self.assertNotIn(obj.id, adapter.applied)

        adapter.set_high_smooth(True)
        self.wait_for(lambda: torus.mesh is not torus_mesh)
        for obj, original in zip(annotations, original_meshes):
            self.assertIs(obj.mesh, original)
            self.assertNotIn(obj.id, adapter.applied)

        adapter.set_enabled(False)
        self.assertIs(circle.mesh, circle_mesh)
        self.assertIs(torus.mesh, torus_mesh)
        self.assertEqual(scene.revision, revision)

    def test_refresh_restores_native_hatch_classification_on_open(self):
        from serpentine3d.core.hatch import HatchShape
        from serpentine3d.fileio.native import load_scene, save_scene

        rectangle = self.geo.make_rectangle((0, 0, 0), (10, 10, 0))
        hatch = HatchShape(self.geo.planar_face(rectangle), pattern="solid")
        path = str(Path(self.folder.name) / "hatch.serp")
        original = getattr(self.geo.shape_kind, "_noodles_original", self.geo.shape_kind)

        def old_fast(shape):
            return "surface" if isinstance(shape, HatchShape) else original(shape)

        old_fast._noodles_fast = True
        old_fast._noodles_original = original
        with patch.object(self.geo, "shape_kind", old_fast), patch.object(self.geo, "free_points"):
            scene = self.window.scene
            self.assertEqual(scene.add(hatch).kind, "surface")
            save_scene(scene, path)

            install_classification()
            current = self.geo.shape_kind
            self.assertEqual(current(hatch), "hatch")
            self.assertEqual(current(rectangle), "curve")
            self.assertIs(current._noodles_original, original)
            install_classification()
            self.assertIs(self.geo.shape_kind, current)

            reopened = self.Scene()
            load_scene(reopened, path)
            self.assertEqual([obj.kind for obj in reopened.all()], ["hatch"])

    def test_imported_dxf_hatch_remains_editable_and_exports_as_hatch(self):
        if find_spec("ezdxf") is None:
            self.skipTest("The native DXF runtime (ezdxf) is not installed.")
        import ezdxf
        from serpentine3d.fileio.dxf import export_dxf, import_dxf
        from serpentine3d.ui.properties import PropertiesPanel

        source = str(Path(self.folder.name) / "original.dxf")
        result = str(Path(self.folder.name) / "exported.dxf")
        document = ezdxf.new()
        hatch = document.modelspace().add_hatch()
        hatch.set_pattern_fill("ANSI31")
        hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
        document.saveas(source)

        scene = self.window.scene
        with patch.object(self.geo, "shape_kind", self.geo.shape_kind), patch.object(
                self.geo, "free_points", self.geo.free_points):
            install_classification()
            self.assertEqual(import_dxf(scene, source), 1)
            obj, = scene.all()
            self.assertEqual(obj.kind, "hatch")
            selection = self.window.selection
            panel = PropertiesPanel(scene, selection, self.window.history, self.window)
            selection.set([obj.id])
            panel.refresh()
            self.assertTrue(panel.form.isRowVisible(panel.hatch_angle))
            panel.hatch_angle.setValue(25)
            self.assertEqual(scene.get(obj.id).shape.angle, 25.)
            export_dxf(scene, result)

        exported, = ezdxf.readfile(result).modelspace().query("HATCH")
        self.assertAlmostEqual(exported.dxf.pattern_angle, 25.)

    def test_only_cad_view_has_toolbar_context_menu_and_high_smooth_uses_defaults(self):
        from serpentine3d.commands import base

        self.window.viewport = SimpleNamespace(_visible_layers=lambda: (), _on_tess_done=lambda: None)
        adapter = self.bridge.cad_viewport = CadViewport(self.ctx)
        register_commands(self.ctx, adapter)
        editor = MainWindow()
        editor.serpentine.client = self.client
        editor.serpentine.interval = .02
        editor.show()
        editor.serpentine.start()
        menu = editor.cad_view_menu
        action = editor.high_smooth_action
        button = editor.cad_view_button

        def right_click(widget):
            pos = widget.rect().center()
            QTest.mouseClick(widget, QtCore.Qt.RightButton, pos=pos)
            event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, widget.mapToGlobal(pos))
            self.app.sendEvent(widget, event)
            self.app.processEvents()

        try:
            self.wait_for(button.isEnabled)
            for widget in (editor.toolbar, *editor.s3d_panel_buttons.values(),
                           editor.library_button, editor.properties_button):
                right_click(widget)
                self.assertIsNone(self.app.activePopupWidget())
                self.assertTrue(editor.toolbar.isVisible())

            adapter.set_enabled(True, Quality(8., .5, 14., .5, 72))
            self.wait_for(action.isChecked)
            right_click(button)
            self.assertTrue(menu.isVisible())
            self.assertEqual(menu.actions(), [action])
            self.assertEqual(action.text(), 'High Smooth')
            self.assertTrue(action.isCheckable())
            checked = menu.grab().toImage()
            action_rect = menu.actionGeometry(action)
            dpr = checked.devicePixelRatio()
            mark = lambda: [checked.pixelColor(x, y) for x in range(round(8 * dpr), round(34 * dpr))
                            for y in range(round(action_rect.top() * dpr), round(action_rect.bottom() * dpr))]
            self.assertTrue(any(color.name() == '#d9efe5' for color in mark()))
            QTest.mouseClick(menu, QtCore.Qt.LeftButton, pos=action_rect.center())
            self.wait_for(lambda: action.isEnabled() and not action.isChecked())
            self.assertTrue(adapter.enabled)
            self.assertFalse(adapter.refine_surfaces)
            self.assertTrue(button.isChecked())
            self.assertFalse(menu.isVisible())

            context = SimpleNamespace(echo=lambda _: None)
            list(base.resolve('cvn').fn(context))
            self.wait_for(lambda: not button.isChecked())
            right_click(button)
            self.assertTrue(menu.isVisible())
            QTest.mouseClick(menu, QtCore.Qt.LeftButton, pos=menu.actionGeometry(action).center())
            self.wait_for(lambda: action.isEnabled() and action.isChecked())
            self.assertTrue(button.isChecked())
            self.assertTrue(adapter.refine_surfaces)
            self.assertEqual(adapter.quality, Quality())
            self.assertTrue(editor.graph.undo_stack().isClean())
        finally:
            menu.hide()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_zoom_refines_visible_occ_curves_without_rebuilding_torus(self):
        import math
        import numpy as np
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus
        from serpentine3d.ui.camera import Camera

        scene = self.window.scene
        circle = scene.add(self.geo.make_circle((0., 0., 0.), 20.))
        spline = scene.add(self.geo.make_interp_curve([
            (-21., 0., 0.), (-10., 11., 0.), (0., -12., 0.), (10., 13., 0.), (20., 0., 0.)]))
        outside = scene.add(self.geo.make_circle((10000., 0., 0.), 20.))
        torus = scene.add(BRepPrimAPI_MakeTorus(20., 6.).Shape())
        native = [obj.mesh for obj in (circle, spline, outside, torus)]
        shapes = [obj._shape for obj in (circle, spline, outside, torus)]
        revision = scene.revision
        camera = Camera()
        camera.set_standard_view('top')
        camera.distance = 350.
        dpr = 1.
        self.window.viewport = SimpleNamespace(
            camera=camera, space='model', display_mode='shaded', isVisible=lambda: True,
            width=lambda: 1000, height=lambda: 700, devicePixelRatioF=lambda: dpr,
            _visible_layers=lambda: (), _on_tess_done=lambda: None)
        adapter = self.bridge.cad_viewport = CadViewport(self.ctx)
        adapter.set_enabled(True)
        self.wait_for(lambda: all(obj.id in adapter.applied for obj in (circle, spline)))
        baseline = circle.mesh, spline.mesh, torus.mesh

        camera.distance = 20.
        self.wait_for(lambda: circle.mesh is not baseline[0] and spline.mesh is not baseline[1])
        self.assertGreater(len(circle.mesh.local_edges), len(baseline[0].local_edges))
        self.assertGreater(len(spline.mesh.local_edges), len(baseline[1].local_edges))
        mids = circle.mesh.edge_segments.astype(float).mean(axis=1)
        magnification = 350. / (camera.distance * math.tan(math.radians(camera.fov) / 2))
        error = (20. - np.linalg.norm(mids, axis=1).min()) * magnification
        self.assertLessEqual(error, .5)
        np.testing.assert_array_equal(np.unique(circle.mesh.edge_of_segment),
                                      np.unique(native[0].edge_of_segment))
        self.assertIs(torus.mesh, baseline[2])
        self.assertIs(torus.mesh, native[3])
        self.assertIs(outside.mesh, native[2])

        zoomed = circle.mesh
        dpr = 2.
        self.wait_for(lambda: circle.mesh is not zoomed)
        self.assertGreater(len(circle.mesh.local_edges), len(zoomed.local_edges))
        camera.distance = 350.
        self.wait_for(lambda: len(circle.mesh.local_edges) == len(baseline[0].local_edges))
        self.assertEqual(scene.revision, revision)
        self.assertEqual(shapes, [obj._shape for obj in (circle, spline, outside, torus)])
        adapter.set_enabled(False)
        for obj, original in zip((circle, spline, outside, torus), native):
            self.assertIs(obj.mesh, original)

    def test_torus_uses_analytic_normals_without_touching_native_cache(self):
        import numpy as np
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus
        from serpentine3d.core import tessellate as native

        torus = BRepPrimAPI_MakeTorus(20., 6.).Shape()
        obj = self.window.scene.add(torus)
        original = obj.mesh
        mesh = build_mesh(torus, Quality())
        self.assertIs(obj._shape, torus)
        self.assertIs(obj.mesh, original)
        self.assertGreater(len(mesh.triangles), len(original.triangles))
        self.assertEqual(set(mesh.face_of_triangle), set(original.face_of_triangle))
        self.assertEqual(set(mesh.edge_of_segment), set(original.edge_of_segment))
        normals = mesh.vertices.copy()
        normals[:, :2] *= (1 - 20. / np.linalg.norm(normals[:, :2], axis=1))[:, None]
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        np.testing.assert_allclose(mesh.normals, normals, atol=2e-6)
        self.assertEqual(native._ISO_SAMPLES, 48)

    def test_toolbar_commands_and_legacy_node_share_session_state(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus
        from serpentine3d.commands import base

        scene = self.window.scene
        torus = BRepPrimAPI_MakeTorus(20., 6.).Shape()
        obj = scene.add(torus)
        mesh, revision = obj.mesh, scene.revision
        repaints = []
        self.window.viewport = SimpleNamespace(_visible_layers=lambda: (), _on_tess_done=lambda: repaints.append(1))
        adapter = self.bridge.cad_viewport = CadViewport(self.ctx)
        register_commands(self.ctx, adapter)
        context = SimpleNamespace(echo=lambda _: None)
        list(base.resolve('cv').fn(context))
        self.assertTrue(adapter.enabled)
        self.assertFalse(adapter.refine_surfaces)
        self.assertIs(obj.mesh, mesh)

        editor = MainWindow()
        editor.serpentine.client = self.client
        editor.serpentine.interval = .02
        editor.show()
        try:
            toolbar_button = editor.cad_view_button
            self.assertEqual(toolbar_button.text(), 'CAD View')
            self.assertFalse(toolbar_button.isEnabled())
            self.assertFalse(any(kind == 'NoodleS.VisualHelpers.CadViewportNode'
                                 for _, kind, _ in editor.palette.node_entries()))
            editor._show_node_search(editor.graph)
            QTest.keyClicks(editor.node_search.query, 'CadViewport')
            self.assertEqual(editor.node_search.results.count(), 0)
            editor.node_search.hide()

            node = editor.add_node('NoodleS.VisualHelpers.CadViewportNode')
            self.assertFalse(node.input_ports())
            self.assertFalse(node.output_ports())
            self.assertFalse(editor.snapshot())
            editor.serpentine.start()
            self.wait_for(lambda: editor.point_service.active)
            path = Path(self.folder.name) / 'cad-view.noodles'
            self.assertTrue(editor._save_to(path))
            editor.open_document(path)
            node, = editor.graph.all_nodes()
            editor.graph.center_on([node])
            widget = node.get_widget('cad_view_button')
            button = widget.button
            self.wait_for(lambda: button.text() == 'Disable CAD View' and toolbar_button.isEnabled())
            actions = editor.toolbar.actions()
            cad_position = next(index for index, action in enumerate(actions)
                                if editor.toolbar.widgetForAction(action) is toolbar_button)
            self.assertIs(editor.toolbar.widgetForAction(actions[cad_position + 1]),
                          editor.s3d_panel_buttons['properties'])
            self.assertTrue(toolbar_button.isChecked())
            active_render = toolbar_button.grab().toImage()
            dpr = active_render.devicePixelRatio()
            self.assertEqual(active_render.pixelColor(round(8 * dpr), active_render.height() // 2).name(),
                             '#5c3921')
            QTest.mouseClick(toolbar_button, QtCore.Qt.LeftButton)
            self.wait_for(lambda: toolbar_button.isEnabled() and not toolbar_button.isChecked())
            self.assertFalse(adapter.enabled)
            self.assertEqual(button.text(), 'Enable CAD View')
            inactive_render = toolbar_button.grab().toImage()
            self.assertEqual(inactive_render.pixelColor(0, inactive_render.height() // 2),
                             inactive_render.pixelColor(round(8 * dpr), inactive_render.height() // 2))
            list(base.resolve('cv').fn(context))
            self.wait_for(lambda: toolbar_button.isChecked() and button.text() == 'Disable CAD View')
            button_origin = QtCore.QPointF(button.pos())
            origin_in_node = widget.mapToItem(node.view, button_origin)
            self.assertEqual(origin_in_node.y() - (node.view._header_height + 1),
                             node.view.height - 1 - (origin_in_node.y() + button.height()))
            self.assertEqual(origin_in_node.x(), node.view.width - origin_in_node.x() - button.width())

            def rendered_colors():
                scene_origin = widget.mapToScene(button_origin)
                area = QtCore.QRectF(scene_origin.x() - 3, scene_origin.y(), button.width() + 3, button.height())
                image = QtGui.QImage(int(area.width()) * 4, int(area.height()) * 4, QtGui.QImage.Format_RGB32)
                painter = QtGui.QPainter(image)
                widget.scene().render(painter, QtCore.QRectF(image.rect()), area)
                painter.end()
                return (image.pixelColor((3 + button.width() // 2) * 4, 12).name(),
                        image.pixelColor(6, 12).name(),
                        image.pixelColor(14, button.height() * 2).name())

            self.assertEqual(rendered_colors()[0], '#5c3921')
            stack = editor.graph.undo_stack()
            stack.setClean()
            view = editor.graph.viewer()
            local = button.mapTo(widget.widget(), button.rect().center())
            pos = view.mapFromScene(widget.mapToScene(QtCore.QPointF(local)))
            QTest.mouseClick(view.viewport(), QtCore.Qt.LeftButton, pos=pos)
            self.wait_for(lambda: button.text() == 'Enable CAD View' and button.isEnabled())
            self.assertFalse(toolbar_button.isChecked())
            self.assertTrue(toolbar_button.isEnabled())
            fill, body, border = rendered_colors()
            self.assertEqual(fill, body)
            self.assertNotEqual(border, body)
            self.assertTrue(stack.isClean())
            self.assertFalse(adapter.enabled)
            self.assertIs(obj.mesh, mesh)

            command = base.resolve('cadq').fn(context)
            next(command)
            for value in (8., .5, 14., .5):
                command.send(value)
            with self.assertRaises(StopIteration):
                command.send(72)
            self.wait_for(lambda: button.text() == 'Disable CAD View' and obj.mesh is not mesh)
            self.assertEqual(adapter.quality.iso_samples, 72)
            self.assertTrue(adapter.refine_surfaces)
            list(base.resolve('cv').fn(context))
            self.assertIs(obj.mesh, mesh)
            self.assertFalse(adapter.refine_surfaces)
            adapter.set_enabled(True, adapter.quality)
            self.wait_for(lambda: obj.mesh is not mesh)
            self.window.history.checkpoint('Before changing the torus')
            scene.update(obj.id, name='Edited torus')
            list(base.resolve('cvn').fn(context))
            self.wait_for(lambda: button.text() == 'Enable CAD View')
            self.assertIs(scene.get(obj.id).mesh, mesh)
            self.window.history.undo()
            obj = scene.get(obj.id)
            self.assertIs(obj.mesh, mesh)
            self.assertIs(obj._shape, torus)
            self.assertGreater(scene.revision, revision)
            self.assertGreaterEqual(len(repaints), 2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()
