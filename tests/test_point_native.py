"""Native integration: real OCC, scene, file format, bridge and event stream."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.point import evaluate_point, object_from_outputs
from noodles.bridge import BridgeClient, BridgeRemoteError
from noodles.serpentine_plugin.NoodleSBridge import BridgeServer


class NativePointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        configured_source = os.environ.get("NOODLES_TEST_SERPENTINE_SOURCE")
        if not configured_source:
            raise unittest.SkipTest("Set NOODLES_TEST_SERPENTINE_SOURCE for native CAD tests.")
        source = Path(configured_source).resolve()
        if not (source / "serpentine3d" / "__init__.py").is_file():
            raise RuntimeError("NOODLES_TEST_SERPENTINE_SOURCE must point to the Serpentine3D source root.")
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from serpentine3d import __version__
        from serpentine3d.core import geometry
        from serpentine3d.core.scene import Scene
        from serpentine3d.core.selection import SelectionManager
        from serpentine3d.core.history import History
        cls.geo, cls.Scene, cls.Selection, cls.History = geometry, Scene, SelectionManager, History
        cls.serpentine_version = __version__
        (cls.root / ".test-output").mkdir(exist_ok=True)
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=self.root / ".test-output")
        self.window = QtWidgets.QWidget()
        self.window.scene = self.Scene()
        self.window.selection = self.Selection(self.window.scene)
        self.window.history = self.History(self.window.scene)
        self.window.processor = SimpleNamespace(busy=False)
        self.window.ctx = SimpleNamespace(current_path=None)
        from serpentine3d.plugins import PluginContext
        serpentine_version = self.serpentine_version
        class Context(PluginContext):
            version = serpentine_version
            @property
            def scene(self):
                return self.window.scene
        self.ctx = Context(self.window)
        self.ctx.window = self.window
        self.bridge = BridgeServer(self.ctx, Path(self.folder.name) / "bridge.json")
        self.bridge.start()
        self.client = BridgeClient(self.bridge.descriptor, timeout=1)
        self.parameters = {"mode": "generate", "project_uuid": "af96bbf5-d242-4876-bebb-15d8de7a8991",
                           "node_uuid": "e5c1ed25-f186-4668-842d-b554cc39c95f"}

    def tearDown(self):
        self.bridge.stop()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def call(self, method, params):
        output = {}
        def worker():
            try:
                output["result"] = self.client.call(method, params)["data"]
            except Exception as exc:
                output["error"] = exc
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.wait_for(lambda: not thread.is_alive())
        if "error" in output:
            raise output["error"]
        return output["result"]

    def wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(condition(), "Native operation timed out")

    def model(self, x=0):
        return object_from_outputs(self.parameters, evaluate_point(self.parameters, {"X": x})).to_wire()

    def publish(self, model):
        request = self.call("points.prepare", {"model": model, "name": "Point"})
        self.wait_for(lambda: self.bridge.points.jobs[request["job_id"]]["state"] != "preparing")
        result = self.call("points.job", request)
        self.assertEqual(result["state"], "complete", result)
        return self.window.scene.get(result["object_id"])

    def test_book_cross_reference_builds_point_grid_in_one_owner(self):
        from OCP.BRep import BRep_Tool
        from OCP.TopoDS import TopoDS
        from noodles.backend.grid_reference_native import children
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            series = editor.add_node('NoodleS.Math.SeriesNode')
            cross = editor.add_node('NoodleS.Data.CrossReferenceNode')
            point = editor.add_node('NoodleS.Geometry.PointNode')
            for port, axis in (('A', 'X'), ('B', 'Y')):
                series.outputs()['S'].connect_to(cross.inputs()[port])
                cross.outputs()[port].connect_to(point.inputs()[axis])
            identity = editor.project_uuid, point.point_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None and len(tuple(children(owner().shape))) == 100)
            expected = {(x, y, 0) for x in range(10) for y in range(10)}
            vertices = tuple(children(owner().shape))
            self.assertEqual({BRep_Tool.Pnt_s(TopoDS.Vertex_s(v)).Coord() for v in vertices}, expected)
            self.assertEqual(set(self.window.scene.objects), {owner().id})
            self.assertNotIn(cross.id, editor.point_service.models)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_one_point_publishes_one_compound_parametric_object(self):
        from OCP.TopAbs import TopAbs_COMPOUND
        owner = self.publish(self.model(12))
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(owner.shape.ShapeType(), TopAbs_COMPOUND)
        self.assertTrue(owner.mesh_ready)
        self.assertEqual(len(owner.mesh.points), 1)
        self.assertIn("NoodleS.parametric", owner.user_text)
        self.assertEqual(owner.kind, "point")

    def test_two_hundred_points_keep_owner_and_user_attributes(self):
        owner = self.publish(self.model())
        self.window.scene.update(owner.id, name="My points", color=(.1, .3, .5))
        tree = DataTree((Branch((0,), tuple(range(200))),))
        updated = self.publish(self.model(tree))
        self.assertEqual(owner.id, updated.id)
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(updated.mesh.points), 200)
        self.assertEqual(updated.name, "My points")
        self.assertEqual(updated.color, (.1, .3, .5))

    def test_topology_change_reuses_native_shape_and_mesh(self):
        tree = DataTree((Branch((0,), (1, 2, 3)),))
        first = self.publish(self.model(tree))
        self.parameters["tree_modes"] = {"X": "graft"}
        second = self.publish(self.model(tree))
        self.assertIs(first.shape, second.shape)
        self.assertIs(first._mesh, second._mesh)
        manifest = json.loads(second.user_text["NoodleS.parametric"])
        self.assertEqual(len(manifest["branches"]), 3)

    def test_capture_move_and_reopen_reference_points_individually(self):
        from serpentine3d.fileio.native import save_scene, load_scene
        scene = self.window.scene
        a = scene.add(self.geo.make_point((1, 2, 3)), name="A")
        b = scene.add(self.geo.make_point((4, 5, 6)), name="B")
        self.window.selection.set([a.id, b.id])
        result = self.call("points.capture", self.parameters)
        records = result["references"]
        self.assertEqual(len(scene.objects), 2)
        self.assertTrue(all(o.group_id is None for o in scene.all()))
        self.assertEqual(self.window.selection.ids, [a.id, b.id])
        scene.replace_shape(a.id, self.geo.make_point((10, 2, 3)))
        updated = self.call("points.read", {**self.parameters, "references": records})["references"]
        self.assertEqual(updated[0]["xyz"], [10, 2, 3])
        self.assertEqual(updated[1]["xyz"], [4, 5, 6])
        path = Path(self.folder.name) / "references.serp"
        save_scene(scene, str(path))
        reopened = self.Scene()
        load_scene(reopened, str(path))
        self.window.scene = reopened
        restored = self.call("points.read", {**self.parameters, "references": records})["references"]
        self.assertEqual([r["key"] for r in restored], [r["key"] for r in records])
        self.assertNotEqual([r["id"] for r in restored], [r["id"] for r in records])
        self.assertEqual(restored[0]["xyz"], [10, 2, 3])

    def test_reference_capture_rejects_mixed_selection_without_partial_binding(self):
        scene = self.window.scene
        point = scene.add(self.geo.make_point((0, 0, 0)))
        solid = scene.add(self.geo.make_box((0, 0, 0), 1, 1, 1))
        self.window.selection.set([point.id, solid.id])
        with self.assertRaises(BridgeRemoteError):
            self.call("points.capture", self.parameters)
        self.assertIsNone(scene.get(point.id).user_text)

    def test_reference_drive_keeps_native_identity_attributes_and_fresh_unconnected_axes(self):
        scene = self.window.scene
        point = scene.add(self.geo.make_point((1, 2, 3)), name="Native point")
        scene.update(point.id, color=(0.2, 0.3, 0.4))
        self.window.selection.set([point.id])
        records = self.call("points.capture", self.parameters)["references"]
        text = scene.get(point.id).user_text
        scene.replace_shape(point.id, self.geo.make_point((1, 77, 3)))
        params = {**self.parameters, "references": records, "drive": {
            "axes": ["X"], "updates": [{"key": records[0]["key"], "coordinates": {"X": 59.26}}]}}
        reply = self.call("points.drive", params)
        current = scene.get(point.id)
        self.assertEqual(reply["references"][0]["xyz"], [59.26, 77, 3])
        self.assertEqual(current.user_text, text)
        self.assertEqual(current.name, "Native point")
        self.assertEqual(current.color, (0.2, 0.3, 0.4))
        self.assertIsNone(current.group_id)
        self.assertEqual(len(scene.objects), 1)
        self.window.history.undo()
        self.assertEqual(self.geo.point_coords(scene.get(point.id).shape), (1, 77, 3))

    def test_reference_drive_validates_whole_batch_before_changes(self):
        scene = self.window.scene
        points = [scene.add(self.geo.make_point((i, 0, 0))) for i in range(2)]
        self.window.selection.set([p.id for p in points])
        records = self.call("points.capture", self.parameters)["references"]
        with self.assertRaises(BridgeRemoteError):
            self.call("points.drive", {**self.parameters, "references": records, "drive": {
                "axes": ["X"], "updates": [
                    {"key": records[0]["key"], "coordinates": {"X": 20}},
                    {"key": records[1]["key"], "coordinates": {"X": 1e12}}]}})
        self.assertEqual([self.geo.point_coords(scene.get(p.id).shape)[0] for p in points], [0, 1])
        original = scene.replace_shape
        calls = []
        def fail_second(oid, shape):
            calls.append(oid)
            if len(calls) == 2:
                raise RuntimeError("Injected second-point failure")
            return original(oid, shape)
        with patch.object(scene, "replace_shape", side_effect=fail_second):
            with self.assertRaises(BridgeRemoteError):
                self.call("points.drive", {**self.parameters, "references": records, "drive": {
                    "axes": ["X"], "updates": [
                        {"key": r["key"], "coordinates": {"X": 20}} for r in records]}})
        self.assertEqual([self.geo.point_coords(scene.get(p.id).shape)[0] for p in points], [0, 1])

    def test_two_hundred_reference_moves_publish_one_scene_notification(self):
        scene = self.window.scene
        with scene.batched():
            points = [scene.add(self.geo.make_point((i, 2, 3))) for i in range(200)]
        self.window.selection.set([p.id for p in points])
        records = self.call("points.capture", self.parameters)["references"]
        changes = []
        scene.add_listener(lambda: changes.append(1))
        reply = self.call("points.drive", {**self.parameters, "references": records, "drive": {
            "axes": ["Z"], "updates": [
                {"key": r["key"], "coordinates": {"Z": i / 2}} for i, r in enumerate(records)]}})
        self.assertEqual(changes, [1])
        self.assertEqual([r["id"] for r in reply["references"]], [p.id for p in points])
        self.assertEqual([r["xyz"][2] for r in reply["references"]], [i / 2 for i in range(200)])
        self.assertTrue(all(p.group_id is None for p in scene.all()))

    def test_out_of_range_reference_is_rejected_before_metadata_changes(self):
        scene = self.window.scene
        point = scene.add(self.geo.make_point((1e12, 0, 0)))
        self.window.selection.set([point.id])
        with self.assertRaises(BridgeRemoteError):
            self.call("points.capture", self.parameters)
        self.assertIsNone(scene.get(point.id).user_text)

    def test_missing_or_copied_reference_is_not_guessed(self):
        scene = self.window.scene
        point = scene.add(self.geo.make_point((0, 0, 0)))
        self.window.selection.set([point.id])
        records = self.call("points.capture", self.parameters)["references"]
        scene.add_from(self.geo.make_point((2, 0, 0)), scene.get(point.id))
        with self.assertRaises(BridgeRemoteError):
            self.call("points.read", {**self.parameters, "references": records})

    def test_event_stream_notifies_scene_changes_without_polling_geometry(self):
        stop = threading.Event()
        events = []
        def listen():
            try:
                for event in self.client.events(stop):
                    events.append(event)
            except Exception:
                pass
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
        self.wait_for(lambda: len(events) >= 1)
        count = len(events)
        self.window.scene.add(self.geo.make_point((1, 0, 0)))
        self.wait_for(lambda: any(e.get("event") == "scene_changed" for e in events[count:]))
        stop.set()
        thread.join(1)

    def test_native_undo_restores_geometry_and_manifest_together(self):
        first = self.publish(self.model(1))
        self.publish(self.model(9))
        self.window.history.undo()
        restored = self.window.scene.get(first.id)
        manifest = json.loads(restored.user_text["NoodleS.parametric"])
        self.assertEqual(manifest["branches"][0]["points"][0]["xyz"][0], 1)
        self.assertAlmostEqual(restored.mesh.points[0][0], 1)

    def test_newer_publication_supersedes_queued_result(self):
        first = self.bridge.points.submit({"model": self.model(1)})
        second = self.bridge.points.submit({"model": self.model(2)})
        self.wait_for(lambda: self.bridge.points.jobs[second["job_id"]]["state"] != "preparing")
        self.assertEqual(self.bridge.points.jobs[first["job_id"]]["state"], "superseded")
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertAlmostEqual(self.window.scene.all()[0].mesh.points[0][0], 2)

    def test_graph_open_checks_saved_version_and_document_before_publication(self):
        from noodles.window import MainWindow
        from serpentine3d.fileio.native import load_scene, save_scene

        editor = MainWindow()
        editor.serpentine.client = editor.point_service.client = editor.preview_service.client = self.client
        editor.serpentine.interval = .02
        scene = self.window.scene
        folder = Path(self.folder.name)
        original, latest = folder / 'earlier.noodles', folder / 'latest.noodles'
        model = folder / 'drawing.serp'
        self.window.ctx.current_path = model

        def choose(label, check):
            def prompt(*args):
                def click():
                    dialog = self.app.activeModalWidget()
                    if not isinstance(dialog, QtWidgets.QMessageBox):
                        return
                    observed.append((dialog.informativeText(), editor.path, self.points_x()))
                    button = next((item for item in dialog.buttons() if item.text() == label), None)
                    if button:
                        button.click()
                    else:
                        dialog.reject()
                QtCore.QTimer.singleShot(0, click)
                return real_prompt(*args)

            observed = []
            real_prompt = editor._ask_scene_mismatch
            with patch.object(editor, '_ask_scene_mismatch', side_effect=prompt):
                check()
            self.assertEqual(len(observed), 1)
            return observed[0]

        try:
            editor.serpentine.start()
            self.wait_for(lambda: editor.point_service.active)
            node = editor.add_node('NoodleS.Geometry.PointNode')
            node.set_property('x', 10)
            self.wait_for(lambda: self.points_x() == [10])
            self.assertTrue(editor._save_to(original))
            self.wait_for(lambda: editor.serpentine.info['scene']['graph_link'].get('revision') ==
                          editor._scene_link['revision'])
            node.set_property('x', 20)
            self.wait_for(lambda: self.points_x() == [20])
            self.assertTrue(editor._save_to(latest))
            self.wait_for(lambda: editor.serpentine.info['scene']['graph_link'].get('revision') ==
                          editor._scene_link['revision'])

            body, old_path, old_x = choose('Cancel', lambda: editor.open_document(original))
            self.assertIn('earlier.noodles', body)
            self.assertIn('drawing.serp', body)
            self.assertEqual((old_path, old_x), (latest, [20]))
            self.assertEqual((editor.path, self.points_x()), (latest, [20]))

            save_scene(scene, str(model))
            renamed = folder / 'renamed.serp'
            model.rename(renamed)
            scope = editor._authorized_scene
            load_scene(scene, str(renamed))
            self.window.ctx.current_path = renamed
            with patch.object(editor, '_ask_scene_mismatch', return_value='cancel') as unexpected:
                self.wait_for(lambda: editor.point_service.active and editor._authorized_scene != scope)
                unexpected.assert_not_called()
            with patch.object(QtWidgets.QFileDialog, 'getOpenFileName', return_value=(str(latest), '')) as picker:
                choose('Choose Another Graph…', lambda: editor.open_document(original))
            picker.assert_called_once()
            self.assertEqual((editor.path, self.points_x()), (latest, [20]))

            _, old_path, old_x = choose('Continue Anyway', lambda: editor.open_document(original))
            self.assertEqual((old_path, old_x), (latest, [20]))
            self.wait_for(lambda: self.points_x() == [10])
            self.assertEqual(editor.path, original)

            scene.clear()
            scene.add(self.geo.make_point((98, 0, 0)))
            self.window.ctx.current_path = folder / 'recently-opened.serp'
            self.assertEqual(editor.serpentine.info['scene']['path'], str(renamed))
            body, old_path, old_x = choose('Cancel', lambda: editor.open_document(latest))
            self.assertIn('recently-opened.serp', body)
            self.assertEqual((old_path, old_x), (original, [98]))

            with patch.object(editor, '_ask_scene_mismatch', return_value='cancel') as warning:
                scene.clear()
                scene.add(self.geo.make_point((99, 0, 0)))
                self.window.ctx.current_path = folder / 'other.serp'
                self.wait_for(lambda: warning.called)
                self.assertFalse(editor.point_service.active)
                self.assertEqual(self.points_x(), [99])
                editor.open_document(latest)
                self.assertEqual(warning.call_count, 2)
                self.assertEqual(editor.path, original)
                self.assertEqual(self.points_x(), [99])
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_saving_serpentine_first_keeps_new_and_existing_pairs_linked(self):
        from noodles.window import MainWindow
        from serpentine3d.fileio.native import load_scene, save_scene

        folder = Path(self.folder.name)
        model, graph = folder / 'drawing.serp', folder / 'drawing.noodles'
        scene = self.window.scene
        # Native Save can happen before NoodleS has even opened.
        save_scene(scene, str(model))
        self.window.ctx.current_path = model
        editor = MainWindow()
        editor.serpentine.client = editor.point_service.client = editor.preview_service.client = self.client
        editor.serpentine.interval = .02

        def reopen(expected):
            with patch.object(editor, '_ask_scene_mismatch', return_value='cancel') as warning:
                with scene.batched():
                    load_scene(scene, str(model))
                editor.open_document(graph)
                self.assertTrue(editor.point_service.active)
                self.wait_for(lambda: self.points_x() == [expected])
                warning.assert_not_called()

        def save_graph():
            scene_revision = scene.revision
            self.assertTrue(editor._save_to(graph))
            self.wait_for(lambda: editor.serpentine.info['scene']['graph_link'].get('revision') ==
                          editor._scene_link['revision'])
            self.assertEqual(scene.revision, scene_revision)

        try:
            editor.serpentine.start()
            self.wait_for(lambda: editor.point_service.active)
            editor.add_node('NoodleS.Geometry.PointNode').set_property('x', 10)
            self.wait_for(lambda: self.points_x() == [10])
            save_graph()
            reopen(10)

            # Establish a saved link, then save the new geometry in CAD
            # before the editor records its new graph revision.
            save_graph()
            editor.graph.all_nodes()[0].set_property('x', 20)
            self.wait_for(lambda: self.points_x() == [20])
            save_scene(scene, str(model))
            save_graph()
            editor.graph.all_nodes()[0].set_property('x', 30)
            self.wait_for(lambda: self.points_x() == [30])
            save_graph()
            reopen(30)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_two_document_pairs_keep_independent_connections_and_recover(self):
        from noodles.window import MainWindow
        from serpentine3d.fileio.native import load_scene, save_scene

        folder = Path(self.folder.name)
        cad_a, cad_b = folder / 'Gyroid.serp', folder / 'Honeycomb.serp'
        graph_a, graph_b = folder / 'Gyroid.noodles', folder / 'Honeycomb.noodles'
        self.window.ctx.current_path = cad_a
        other_window = QtWidgets.QWidget()
        other_window.scene = self.Scene()
        other_window.selection = self.Selection(other_window.scene)
        other_window.history = self.History(other_window.scene)
        other_window.ctx = SimpleNamespace(current_path=cad_b)
        other_window.processor = SimpleNamespace(busy=False)
        other_context = type(self.ctx)(other_window)
        other_bridge = BridgeServer(other_context, self.bridge.descriptor)
        editors = []

        def open_editor(session_id=None):
            editor = MainWindow(bridge_session=session_id)
            editors.append(editor)
            client = BridgeClient(self.bridge.descriptor, timeout=0.5, discover=True)
            editor.serpentine.client = editor.point_service.client = editor.preview_service.client = client
            editor.serpentine.interval = 0.02
            editor.serpentine.start()
            self.wait_for(lambda: editor.point_service.active)
            return editor

        def xs(window):
            return [obj.mesh.points[0][0] for obj in window.scene.all()]

        def save_pair(editor, graph_path, window, cad_path):
            self.assertTrue(editor._save_to(graph_path))
            self.wait_for(lambda: editor.serpentine.info and
                          editor.serpentine.info['scene']['graph_link'].get('revision') == editor._scene_link['revision'])
            save_scene(window.scene, str(cad_path))

        restarted = None
        try:
            editor_a = open_editor()
            a = editor_a.add_node('NoodleS.Geometry.PointNode')
            a.set_property('x', 11)
            self.wait_for(lambda: xs(self.window) == [11])
            save_pair(editor_a, graph_a, self.window, cad_a)

            with patch.object(editor_a, '_ask_scene_mismatch', return_value='cancel') as warning:
                other_bridge.start()
                editor_b = open_editor(other_bridge.session_id)
                b = editor_b.add_node('NoodleS.Geometry.PointNode')
                b.set_property('x', 22)
                self.wait_for(lambda: xs(other_window) == [22])
                save_pair(editor_b, graph_b, other_window, cad_b)
                a.set_property('x', 13)
                b.set_property('x', 24)
                self.wait_for(lambda: (xs(self.window), xs(other_window)) == ([13], [24]))
                self.assertEqual(editor_a.serpentine.info['session_id'], self.bridge.session_id)
                self.assertEqual(editor_b.serpentine.info['session_id'], other_bridge.session_id)
                warning.assert_not_called()

                self.bridge.stop()
                self.wait_for(lambda: editor_a.serpentine.state == 'disconnected')
                self.assertEqual(editor_b.serpentine.state, 'connected')
                load_scene(self.window.scene, str(cad_a))
                restarted = BridgeServer(self.ctx, self.bridge.descriptor)
                restarted.start()
                self.wait_for(lambda: editor_a.point_service.active and
                              editor_a.serpentine.info['session_id'] == restarted.session_id)
                a.set_property('x', 15)
                self.wait_for(lambda: (xs(self.window), xs(other_window)) == ([15], [24]))
                warning.assert_not_called()

            # A graph opened from another CAD instance finds its saved peer.
            editor_a.graph.undo_stack().setClean()
            editor_a.close()
            editor_b.graph.undo_stack().setClean()
            with patch.object(editor_b, '_ask_scene_mismatch', return_value='cancel') as warning:
                editor_b.open_document(graph_a)
                self.assertEqual(editor_b.path, graph_a)
                self.assertEqual(editor_b.serpentine.info['session_id'], restarted.session_id)
                self.wait_for(lambda: xs(self.window) == [11])
                self.assertEqual(xs(other_window), [24])
                warning.assert_not_called()
        finally:
            for editor in editors:
                editor.graph.undo_stack().setClean()
                editor.close()
                editor.deleteLater()
            if restarted:
                restarted.stop()
            other_bridge.stop()
            other_window.deleteLater()
            self.app.processEvents()

    def points_x(self):
        return [obj.mesh.points[0][0] for obj in self.window.scene.all()]

    def test_document_switch_rejects_late_requests_and_queued_native_publication(self):
        scene = self.window.scene
        token = self.bridge.summary()['scene']['token']
        stale = self.client.for_scene((self.bridge.session_id, token))
        self.window.processor.busy = True
        job_id = self.call('points.prepare', {'model': self.model(10)})['job_id']
        scene.clear()
        scene.add(self.geo.make_point((90, 0, 0)))
        try:
            with patch.object(self, 'client', stale), self.assertRaisesRegex(BridgeRemoteError, 'document changed'):
                self.call('points.prepare', {'model': self.model(20)})
        finally:
            self.window.processor.busy = False
        self.wait_for(lambda: self.bridge.points.jobs[job_id]['state'] != 'preparing')
        self.assertEqual(self.bridge.points.jobs[job_id]['state'], 'superseded')
        self.assertEqual(self.points_x(), [90])

    def test_real_noodles_reference_button_and_native_move(self):
        from noodles.window import MainWindow
        editor = MainWindow()
        editor.point_service.client = self.client
        try:
            node = editor.add_node("NoodleS.Geometry.PointNode")
            self.app.processEvents()

            editor.point_service.start()
            self.wait_for(lambda: len(self.window.scene.objects) == 1)
            node.set_property("mode", "reference")
            self.app.processEvents()
            self.wait_for(lambda: len(self.window.scene.objects) == 0)
            a = self.window.scene.add(self.geo.make_point((1, 2, 3)), name="A")
            b = self.window.scene.add(self.geo.make_point((4, 5, 6)), name="B")
            self.window.selection.set([a.id, b.id])
            editor._inspect_node(node)
            editor.properties.point_properties.capture.click()
            self.wait_for(lambda: len(node.get_property("references")) == 2)
            self.app.processEvents()
            self.assertEqual(editor.evaluation.results[node.id].outputs["P"].count, 2)
            self.window.scene.replace_shape(a.id, self.geo.make_point((100, 2, 3)))
            self.wait_for(lambda: node.get_property("references")[0]["xyz"][0] == 100)
            self.app.processEvents()
            self.assertEqual(editor.evaluation.results[node.id].outputs["X"].values(), (100, 4))
            self.assertEqual(len(self.window.scene.objects), 2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_installed_adapter_refresh_preserves_scene_and_reuses_owner(self):
        from noodles.install_bridge import install
        owner = self.publish(self.model(12))
        plugin_dir = Path(self.folder.name) / "plugins"
        plugin_dir.mkdir()
        custom = plugin_dir / 'my_tools.py'
        custom.write_text('# custom')
        bridge_path = install(plugin_dir)
        self.assertEqual({p.name for p in plugin_dir.glob('*.py')}, {bridge_path.name, custom.name})
        self.window._noodles_bridge = self.bridge
        self.bridge.code_digest = "old"
        spec = importlib.util.spec_from_file_location("noodles_test_refresh", bridge_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        old_session = self.bridge.session_id
        module.refresh(self.ctx)
        self.bridge = self.window._noodles_bridge
        self.client = BridgeClient(self.bridge.descriptor, timeout=1)
        self.assertNotEqual(self.bridge.session_id, old_session)
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(self.window.scene.get(owner.id).id, owner.id)
        result = self.publish(self.model(12))
        self.assertEqual(result.id, owner.id)

    def test_reference_slider_mouse_undo_and_busy_latest_value(self):
        from noodles.window import MainWindow
        scene = self.window.scene
        a = scene.add(self.geo.make_point((1, 2, 3)), name="A")
        b = scene.add(self.geo.make_point((4, 5, 6)), name="B")
        editor = MainWindow()
        editor.point_service.client = self.client
        try:
            node = editor.add_node("NoodleS.Geometry.PointNode")
            node.set_property("mode", "reference")
            slider = editor.add_node("NoodleS.Inputs.SliderNode")
            slider.set_property("value", 9)
            slider.output(0).connect_to(node.input(0))
            self.app.processEvents()
            editor.point_service.start()
            self.window.selection.set([a.id, b.id])
            editor._inspect_node(node)
            editor.properties.point_properties.capture.click()
            self.wait_for(lambda: self.geo.point_coords(scene.get(a.id).shape)[0] == 9)
            self.wait_for(lambda: node.get_property("references")[0]["xyz"][0] == 9)
            self.assertEqual(self.geo.point_coords(scene.get(b.id).shape), (9, 5, 6))

            slider.get_widget("value").slider.setValue(3400)
            self.wait_for(lambda: self.geo.point_coords(scene.get(a.id).shape)[0] == 34)
            self.wait_for(lambda: node.get_property("references")[0]["xyz"][0] == 34)
            with patch.object(self.bridge.points, "drive", wraps=self.bridge.points.drive) as driving:
                scene.replace_shape(a.id, self.geo.make_point((101, 77, 3)))
                self.wait_for(lambda: editor.evaluation.results[node.id].outputs["X"].values() == (101, 34))
                self.assertEqual(driving.call_count, 0)
                self.assertEqual(self.geo.point_coords(scene.get(a.id).shape), (101, 77, 3))

            slider.set_property("value", 35)
            self.wait_for(lambda: self.geo.point_coords(scene.get(a.id).shape)[0] == 35)
            self.assertEqual(self.geo.point_coords(scene.get(a.id).shape), (35, 77, 3))
            editor.graph.undo_stack().undo()
            self.wait_for(lambda: self.geo.point_coords(scene.get(a.id).shape)[0] == 34)

            self.window.processor.busy = True
            slider.set_property("value", 50)
            self.wait_for(lambda: bool(editor.point_service.pending_drives))
            slider.set_property("value", 60)
            self.app.processEvents()
            slider.set_property("value", 70)
            self.app.processEvents()
            self.assertEqual(self.geo.point_coords(scene.get(a.id).shape)[0], 34)
            self.window.processor.busy = False
            self.wait_for(lambda: self.geo.point_coords(scene.get(a.id).shape)[0] == 70)
            self.wait_for(lambda: node.get_property("references")[0]["xyz"][0] == 70)
            node.input(0).clear_connections()
            self.app.processEvents()
            scene.replace_shape(a.id, self.geo.make_point((202, 77, 3)))
            self.wait_for(lambda: editor.evaluation.results[node.id].outputs["X"].values() == (202, 70))
            self.assertEqual(len(scene.objects), 2)
            self.assertEqual(scene.get(a.id).name, "A")
            self.assertTrue(all(obj.group_id is None for obj in scene.all()))
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
