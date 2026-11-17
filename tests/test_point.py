"""Point recipes, topology, real Properties controls and document persistence."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
import uuid

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.datatree import Branch, DataTree, aligned, topology
from noodles.backend.point import evaluate_point, object_from_outputs, object_from_wire, reference_drive
from noodles.core import compute
from noodles.document import read_document, validate_document, write_document, DocumentError
from noodles.window import MainWindow
from noodles.point_properties import input_preview


def state(**kwargs):
    return {"mode": "generate", "project_uuid": str(uuid.uuid4()), "node_uuid": str(uuid.uuid4()), **kwargs}


class PointDataTests(unittest.TestCase):
    def test_one_point_is_a_deferred_parametric_object(self):
        params = state(x=12, y=-3, z=0.25)
        output = evaluate_point(params, {})
        obj = object_from_outputs(params, output)
        self.assertEqual(obj.points.count, 1)
        self.assertEqual(obj.points.values()[0].xyz, (12, -3, 0.25))
        self.assertEqual(object_from_wire(obj.to_wire()), obj)
        self.assertEqual(set(output), {"P", "X", "Y", "Z"})

    def test_two_hundred_distinct_heights_in_one_object(self):
        params = state()
        original = DataTree((Branch((0,), tuple(range(100))), Branch((1,), tuple(range(100, 200)))))
        output = evaluate_point(params, {"X": original, "Z": original})
        obj = object_from_outputs(params, output)
        self.assertEqual(obj.points.count, 200)
        self.assertEqual(tuple(b.path for b in obj.points.branches), ((0,), (1,)))
        self.assertEqual(output["Z"].values(), tuple(range(200)))
        self.assertEqual(len({p.key for p in obj.points.values()}), 200)
        self.assertEqual(len(obj.to_wire()["branches"]), 2)

    def test_modifiers_preserve_sources_and_point_keys(self):
        x = DataTree((Branch((0,), (1, 2, 3)),))
        before = copy.deepcopy(x)
        params = state()
        first = evaluate_point(params, {"X": x})
        second = evaluate_point({**params, "tree_modes": {"X": "graft"}}, {"X": x})
        self.assertEqual(x, before)
        self.assertEqual(first["P"].values(), second["P"].values())
        self.assertEqual(len(second["P"].branches), 3)
        restored = evaluate_point(params, {"X": x})
        self.assertEqual(restored, first)

    def test_graft_changes_matching_without_silently_flattening(self):
        x = DataTree((Branch((0,), (1, 2, 3)),))
        params = state(tree_modes={"X": "graft"})
        self.assertEqual(evaluate_point(params, {"X": x, "Y": x})["P"].count, 9)
        params["tree_modes"]["Y"] = "graft"
        self.assertEqual(evaluate_point(params, {"X": x, "Y": x})["P"].count, 3)
        with self.assertRaises(ValueError):
            tuple(aligned(DataTree((Branch((0,), (1,)), Branch((1,), (2,)))),
                          DataTree((Branch((4,), (1,)), Branch((5,), (2,))))))

    def test_tree_math_and_watch_preserve_paths_and_integer_values(self):
        tree = DataTree((Branch((2, 3), (2, 4)),))
        result = compute("addition", {}, {"A": tree, "B": 10})["R"]
        self.assertEqual(result.branches[0].path, (2, 3))
        self.assertEqual(result.values(), (12, 14))
        self.assertEqual(compute("watch", {}, {"Value": tree})["Value"], tree)
        self.assertIs(type(topology(tree, "graft").values()[0]), int)

    def test_reference_coordinates_and_paths(self):
        refs = [{"key": "a", "id": "1", "name": "A", "xyz": [1, 2, 3]},
                {"key": "b", "id": "2", "name": "B", "xyz": [4, 5, 6]}]
        params = state(mode="reference", references=refs, tree_modes={"Points": "graft"})
        output = evaluate_point(params, {"X": 999})
        self.assertEqual(output["X"].values(), (1, 4))
        self.assertEqual(len(output["P"].branches), 2)
        self.assertEqual(output["P"].values()[1].key, "b")

    def test_empty_branch_produces_no_fabricated_points(self):
        output = evaluate_point(state(), {"X": DataTree((Branch((0,), ()),))})
        self.assertEqual(output["P"].count, 0)
        self.assertEqual(output["X"].branches[0].items, ())

    def test_reference_axis_drive_preserves_keys_and_only_patches_connected_axes(self):
        refs = [{"key": "a", "id": "1", "name": "A", "xyz": [1, 2, 3]},
                {"key": "b", "id": "2", "name": "B", "xyz": [4, 5, 6]}]
        params = state(mode="reference", references=refs)
        drive = reference_drive(params, {"X": 9, "Z": [10, 20]})
        self.assertEqual(drive["updates"], [
            {"key": "a", "coordinates": {"X": 9, "Z": 10}},
            {"key": "b", "coordinates": {"X": 9, "Z": 20}}])
        self.assertEqual(evaluate_point(params, {"X": 9})["X"].values(), (1, 4))
        self.assertEqual(reference_drive(params, {})["updates"], [])

    def test_reference_tree_drive_rejects_conflicting_positions_for_one_object(self):
        refs = [{"key": "a", "id": "1", "name": "A", "xyz": [1, 2, 3]}]
        params = state(mode="reference", references=refs)
        with self.assertRaisesRegex(ValueError, "multiple positions"):
            reference_drive(params, {"X": [9, 10]})
        refs.append({"key": "b", "id": "2", "name": "B", "xyz": [4, 5, 6]})
        params["tree_modes"] = {"Points": "graft", "X": "graft"}
        drive = reference_drive(params, {"X": [9, 10]})
        self.assertEqual([u["coordinates"] for u in drive["updates"]], [{"X": 9}, {"X": 10}])


class PointWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.node = self.window.add_node("NoodleS.Geometry.PointNode")
        self.app.processEvents()
        self.panel = self.window.properties.point_properties
        self.stack = self.window.graph.undo_stack()
        self.stack.clear()

    def tearDown(self):
        self.stack.setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def output(self):
        return self.window.evaluation.results[self.node.id].outputs["P"]

    def test_point_replaces_xyz_and_uses_one_item_by_default(self):
        self.assertEqual(self.node.name(), "Point")
        self.assertEqual(list(self.node.outputs()), ["P", "X", "Y", "Z"])
        self.assertEqual(self.output().values()[0].xyz, (0, 0, 0))
        self.assertIsNotNone(self.node.parametric_object)
        self.assertEqual(self.node.parametric_object.mode, "generate")
        self.assertEqual(self.node.get_property("project_uuid"), self.window.project_uuid)
        self.assertEqual(self.node.get_property("tree_modes"), {})

    def test_publication_status_does_not_flicker_during_fast_updates(self):
        published = "Published · one ParametricObject"
        preparing = "Preparing native geometry…"
        self.node.scene_status = published
        self.panel.reset_status()
        self.window._inspect_node(self.node)
        for _ in range(10):
            self.window._point_event(self.node.id, "publishing", preparing)
            QTest.qWait(10)
            self.assertEqual(self.panel.status.text(), published)
            self.window._point_event(self.node.id, "published", {"object_id": "native"})
            QTest.qWait(10)
            self.assertEqual(self.panel.status.text(), published)
        self.window._point_event(self.node.id, "publishing", preparing)
        QTest.qWait(220)
        self.assertEqual(self.panel.status.text(), preparing)
        self.window._point_event(self.node.id, "error", "Native operation failed")
        self.assertEqual(self.panel.status.text(), "Native operation failed")
        self.window._point_event(self.node.id, "publishing", preparing)
        other = self.window.add_node("NoodleS.Geometry.PointNode")
        self.window._inspect_node(other)
        QTest.qWait(220)
        self.assertEqual(self.panel.status.text(), "Not published")

    def test_source_buttons_cannot_leave_mode_unselected(self):
        self.panel.sources["generate"].click()
        self.assertTrue(self.panel.sources["generate"].isChecked())
        self.panel.sources["reference"].click()
        self.app.processEvents()
        self.assertEqual(self.node.get_property("mode"), "reference")
        self.assertTrue(self.panel.reference.isVisibleTo(self.panel))
        self.assertTrue(self.panel.generate.isVisibleTo(self.panel))

    def test_graft_toggle_switch_and_undo(self):
        control = self.panel.modifiers["X"]
        control.buttons["graft"].click()
        self.app.processEvents()
        self.assertEqual(self.node.get_property("tree_modes"), {"X": "graft"})
        control.buttons["flatten"].click()
        self.app.processEvents()
        self.assertEqual(self.node.get_property("tree_modes"), {"X": "flatten"})
        self.stack.undo()
        self.app.processEvents()
        self.assertTrue(control.buttons["graft"].isChecked())
        control.buttons["graft"].click()
        self.app.processEvents()
        self.assertEqual(self.node.get_property("tree_modes"), {})
        self.assertFalse(any(b.isChecked() for b in control.buttons.values()))

    def test_coordinate_editor_and_connected_input(self):
        self.panel.editors["X"].setText("12.75")
        self.panel.editors["X"].editingFinished.emit()
        self.app.processEvents()
        self.assertEqual(self.output().values()[0].xyz[0], 12.75)
        number = self.window.add_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 9)
        number.output(0).connect_to(self.node.input(0))
        self.app.processEvents()
        self.window._inspect_node(self.node)
        self.assertEqual(self.output().values()[0].xyz[0], 9)
        self.assertFalse(self.panel.editors["X"].isEnabled())
        self.assertEqual(self.panel.previews["X"].text(), "9")
        self.assertIsInstance(self.panel.previews["X"], QtWidgets.QLabel)
        self.assertEqual(self.node.get_property("x"), 12.75)
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.window._inspect_node(self.node)
        before = self.stack.index()
        number.get_widget("value").spin.setValue(11.11)
        self.app.processEvents()
        self.assertEqual(self.panel.previews["X"].text(), "11.11")
        self.assertEqual(self.stack.index(), before + 1)
        self.assertEqual(self.node.get_property("x"), 12.75)
        self.stack.undo()
        self.app.processEvents()
        self.assertEqual(self.panel.previews["X"].text(), "9")
        self.node.input(0).clear_connections()
        self.app.processEvents()
        self.assertTrue(self.panel.editors["X"].isEnabled())
        self.assertIs(self.panel.input_stacks["X"].currentWidget(), self.panel.editors["X"])
        self.assertEqual(self.panel.editors["X"].value(), 12.75)
        self.stack.undo()
        self.app.processEvents()
        self.assertEqual(self.panel.previews["X"].text(), "9")

    def test_connected_coordinate_previews_tree_structure_and_modifiers(self):
        source = self.window.add_node("NoodleS.Geometry.PointNode")
        source.set_property("mode", "reference")
        refs = [{"key": str(i), "id": str(i), "name": "Point", "xyz": [i, 0, 0]}
                for i in range(1, 5)]
        self.window._point_event(source.id, "capture", {
            "references": refs, "node_uuid": source.get_property("node_uuid")})
        source.outputs()["X"].connect_to(self.node.inputs()["X"])
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.app.processEvents()
        self.window._inspect_node(self.node)
        preview = self.panel.previews["X"]
        self.assertIs(self.panel.input_stacks["X"].currentWidget(), preview)
        self.assertIn("4 item(s) · 1 branch(es)", preview.text())
        self.assertIn("{0}: 1, 2, 3 …", preview.text())
        self.panel.modifiers["X"].buttons["graft"].click()
        self.app.processEvents()
        self.assertIn("4 branch(es)", preview.text())
        self.assertIn("{0;0}: 1", preview.text())
        self.panel.modifiers["X"].buttons["flatten"].click()
        self.app.processEvents()
        self.assertIn("1 branch(es)", preview.text())
        self.assertEqual(self.node.get_property("x"), 0)
        source.set_property("disabled", True)
        self.app.processEvents()
        self.assertEqual(preview.text(), "No valid input")
        self.assertIn("Node disabled", preview.toolTip())
        self.stack.undo()
        self.app.processEvents()
        self.assertIn("4 item(s)", preview.text())

    def test_connected_small_coordinate_is_not_rounded_by_default_editor(self):
        number = self.window.add_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 0.0001)
        product = self.window.add_node("NoodleS.Math.MultiplicationNode")
        number.output(0).connect_to(product.input(0))
        number.output(0).connect_to(product.input(1))
        product.output(0).connect_to(self.node.input(0))
        self.app.processEvents()
        self.window._inspect_node(self.node)
        self.assertEqual(float(self.panel.previews["X"].text()), 1e-8)
        self.assertEqual(self.node.get_property("x"), 0)

    def test_hover_shows_all_grafted_range_items_and_stays_open_for_scrolling(self):
        source = self.window.add_node("NoodleS.Math.RangeNode")
        source.set_property("steps", 31)
        source.outputs()["R"].connect_to(self.node.inputs()["Y"])
        self.node.set_property("tree_modes", {"Y": "graft"})
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.window.show()
        QTest.qWait(30)
        preview = self.panel.previews["Y"]
        self.assertIn("32 branch(es)", preview.text())
        self.assertNotIn("{0;31}", preview.text())
        scroll = self.window.properties.findChild(QtWidgets.QScrollArea, "InspectorScroll")
        scroll.ensureWidgetVisible(preview)
        QTest.mouseMove(self.window.canvas_panel)
        QTest.mouseMove(preview, preview.rect().center())
        QTest.qWait(520)
        popup = preview._popup
        self.assertIsNotNone(popup)
        self.assertTrue(popup.isVisible())
        contents = popup.findChild(QtWidgets.QPlainTextEdit)
        self.assertTrue(contents.isReadOnly())
        self.assertEqual(contents.toPlainText().splitlines()[-1], "{0;31}: 1")
        self.assertEqual(contents.toPlainText().count("{0;"), 32)
        QTest.mouseMove(contents.viewport(), contents.viewport().rect().center())
        QTest.qWait(180)
        self.assertTrue(popup.isVisible())
        self.assertGreater(contents.verticalScrollBar().maximum(), 0)
        view = contents.viewport()
        pos = view.rect().center()
        wheel = QtGui.QWheelEvent(pos, view.mapToGlobal(pos), QtCore.QPoint(), QtCore.QPoint(0, -120),
                                  QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        self.app.sendEvent(view, wheel)
        self.assertGreater(contents.verticalScrollBar().value(), 0)
        self.node.set_property("tree_modes", {"Y": "flatten"})
        QTest.qWait(180)
        self.assertTrue(popup.isVisible())
        path, values = contents.toPlainText().split(": ", 1)
        self.assertEqual(path, "{0}")
        self.assertEqual(tuple(map(float, values.split(", "))),
                         self.window.evaluation.results[source.id].outputs["R"].values())
        source.outputs()["R"].disconnect_from(self.node.inputs()["Y"])
        self.app.processEvents()
        self.assertFalse(popup.isVisible())

    def test_input_preview_handles_empty_and_single_nonroot_branch(self):
        scalar, preview = input_preview(DataTree((Branch((3, 7), (0.125,)),)), "none")
        self.assertIsNone(scalar)
        self.assertIn("{3;7}: 0.125", preview)
        scalar, preview = input_preview(DataTree((Branch((0,), ()),)), "none")
        self.assertIsNone(scalar)
        self.assertIn("0 item(s)", preview)
        self.assertIn("(empty)", preview)

    def test_reference_capture_and_live_updates_keep_identity_and_ignore_xyz(self):
        self.node.set_property("mode", "reference")
        refs = [{"key": "stable", "id": "native", "name": "Point", "xyz": [1, 2, 3]}]
        data = {"references": refs, "node_uuid": self.node.get_property("node_uuid")}
        self.window._point_event(self.node.id, "capture", data)
        self.app.processEvents()
        self.assertEqual(self.output().values()[0].xyz, (1, 2, 3))
        self.assertEqual(self.node.parametric_object.mode, "reference")
        self.assertEqual(self.node.parametric_object.source_refs, (("stable", "native"),))
        clean_count = self.stack.count()
        refs[0] = {**refs[0], "xyz": [1, 2, 30]}
        self.window._point_event(self.node.id, "references", {**data, "references": refs})
        self.app.processEvents()
        self.assertEqual(self.output().values()[0].xyz, (1, 2, 30))
        self.assertEqual(self.output().values()[0].key, "stable")
        self.assertEqual(self.stack.count(), clean_count)

    def test_point_document_round_trip_and_legacy_port_migration(self):
        self.node.set_property("x", 1.25)
        self.node.set_property("tree_modes", {"Z": "graft"})
        expected = self.node.point_state()
        output = Path(__file__).resolve().parents[1] / ".test-output"
        with tempfile.TemporaryDirectory(dir=output) as folder:
            path = Path(folder) / "point.noodles"
            write_document(path, self.window.graph.serialize_session())
            self.window.load_session(read_document(path, self.window.node_ports), path)
        restored = self.window.graph.all_nodes()[0]
        self.assertEqual(restored.point_state(), expected)
        watch = self.window.add_node("NoodleS.Data.WatchNode")
        restored.output(0).connect_to(watch.input(0))
        session = self.window.graph.serialize_session()
        session["connections"][0]["out"][1] = "Point"
        session["nodes"][restored.id]["name"] = "Point XYZ"
        clean = validate_document({"format": "NoodleS", "schema_version": 1, "session": session}, self.window.node_ports)
        self.assertEqual(clean["connections"][0]["out"][1], "P")
        self.assertEqual(clean["nodes"][restored.id]["name"], "Point")

    def test_copied_node_gets_independent_identity(self):
        other = self.window.add_node("NoodleS.Geometry.PointNode")
        other.model.set_property("node_uuid", self.node.get_property("node_uuid"))
        self.window.evaluate_now()
        self.assertNotEqual(other.get_property("node_uuid"), self.node.get_property("node_uuid"))

    def test_invalid_saved_point_parameters_are_rejected(self):
        base = {"format": "NoodleS", "schema_version": 1,
                "session": self.window.graph.serialize_session()}
        for value in ({"mode": "input"}, {"tree_modes": {"X": "other"}}, {"x": True},
                      {"x": 10**500}, {"node_uuid": "invalid"}):
            data = copy.deepcopy(base)
            next(iter(data["session"]["nodes"].values()))["custom"].update(value)
            with self.assertRaises(DocumentError):
                validate_document(data, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
