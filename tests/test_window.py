"""Integration tests against real NodeGraphQt and PySide6, without a desktop."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.window import MainWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.output = Path(__file__).resolve().parents[1] / ".test-output"
        cls.output.mkdir(exist_ok=True)

    def setUp(self):
        self.window = MainWindow(example=True)
        self.app.processEvents()

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def node(self, operation):
        return next(n for n in self.window.graph.all_nodes() if n.OPERATION == operation)

    def result(self):
        watch = self.node("watch")
        return self.window.evaluation.results[watch.id]

    def test_frame_graph_brings_all_nodes_into_view_with_a_selection(self):
        self.window.show()
        graph = self.window.graph
        viewer = graph.viewer()
        viewport = viewer.viewport()
        slider, watch = self.node("slider"), self.node("watch")
        slider.set_pos(-1800, -200)
        watch.set_pos(1800, 250)
        graph.clear_selection()
        slider.set_selected(True)
        self.app.processEvents()
        viewport.setFocus()
        action = next(a for a in self.window.application_menu.actions() if a.text() == "Frame graph")
        undo_index = graph.undo_stack().index()

        def check_graph_fits():
            visible = viewer.mapToScene(viewport.rect()).boundingRect()
            for item in (*viewer.all_nodes(), *viewer.all_pipes()):
                self.assertTrue(visible.contains(item.sceneBoundingRect()))
            self.assertEqual(graph.selected_nodes(), [slider])
            self.assertEqual(graph.undo_stack().index(), undo_index)

        for frame in (lambda: QTest.keyClick(viewport, QtCore.Qt.Key_F), action.trigger):
            graph.set_zoom(0)
            graph.center_on([slider])
            scale = viewer.transform().m11()
            far_rect = viewer.mapToScene(viewport.rect()).boundingRect()
            self.assertFalse(far_rect.contains(watch.view.sceneBoundingRect()))
            frame()
            self.app.processEvents()
            check_graph_fits()
            self.assertLess(viewer.transform().m11(), scale)

        frame_rect = QtCore.QRectF(*viewer.scene_rect())
        frame_rect.setSize(frame_rect.size() * 1.5)
        viewer.set_scene_rect(frame_rect.getRect())
        scale = viewer.transform().m11()
        action.trigger()
        self.app.processEvents()
        check_graph_fits()
        self.assertAlmostEqual(viewer.transform().m11(), scale)

    def test_live_edit_and_undo_redo(self):
        self.assertEqual(self.result().outputs, {"Value": 350})
        slider = self.node("slider")
        slider.set_property("value", 50.0)
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 600})
        self.assertFalse(self.window.graph.undo_stack().isClean())
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(slider.get_widget("value").get_value(), 25)
        self.assertEqual(self.result().outputs, {"Value": 350})
        self.window.graph.undo_stack().redo()
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 600})

    def test_widget_change_reaches_engine(self):
        self.node("slider").get_widget("value").slider.setValue(4000)
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 500})
        self.node("number").get_widget("value").spin.setValue(5)
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 225})

    def test_embedded_slider_keeps_inspector_on_selected_point(self):
        graph = self.window.graph
        graph.clear_session()
        slider = self.window.add_node("NoodleS.Inputs.SliderNode")
        point = self.window.add_node("NoodleS.Geometry.PointNode")
        slider.output(0).connect_to(point.input(0))
        slider.set_pos(-200, 0)
        point.set_pos(180, 0)
        self.window.show()
        graph.set_zoom(0)
        graph.center_on([slider, point])
        QTest.qWait(20)
        self.assertEqual(self.window.properties.node_id, point.id)
        viewer = graph.viewer()
        proxy = slider.get_widget("value")
        control = proxy.slider
        option = QtWidgets.QStyleOptionSlider()
        control.initStyleOption(option)
        handle = control.style().subControlRect(QtWidgets.QStyle.CC_Slider, option,
                                               QtWidgets.QStyle.SC_SliderHandle, control)
        position = viewer.mapFromScene(proxy.mapToScene(QtCore.QPointF(
            control.mapTo(proxy.widget(), handle.center()))))
        inspected, pressed = [], []
        graph.node_selected.connect(lambda node: pressed.append(node.id))
        original = self.window.properties.show_node
        def record(node, *args, **kwargs):
            inspected.append(node.id if node else None)
            return original(node, *args, **kwargs)
        with patch.object(self.window.properties, "show_node", side_effect=record):
            QTest.mousePress(viewer.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, position)
            self.assertTrue(control.isSliderDown())
            for value in (1000, 2000, 3000):
                control.setValue(value)
                self.app.processEvents()
            QTest.mouseRelease(viewer.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, position)
            self.app.processEvents()
        self.assertIn(slider.id, pressed)  # Reproduce NodeGraphQt's misleading press signal.
        self.assertNotIn(slider.id, inspected)
        self.assertEqual([n.id for n in graph.selected_nodes()], [point.id])
        self.assertEqual(self.window.properties.node_id, point.id)
        self.assertEqual(self.window.properties.point_properties.previews["X"].text(), "30")
        # A real selection change must still switch the inspector normally.
        header = viewer.mapFromScene(slider.view.text_item.sceneBoundingRect().center())
        QTest.mouseClick(viewer.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, header)
        self.app.processEvents()
        self.assertEqual(self.window.properties.node_id, slider.id)
        empty = viewer.viewport().rect().bottomRight() - QtCore.QPoint(15, 15)
        QTest.mouseClick(viewer.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, empty)
        self.app.processEvents()
        self.assertIsNone(self.window.properties.node_id)

    def test_disconnect_undo_and_delete_undo(self):
        addition = self.node("addition")
        addition.input(0).clear_connections()
        self.app.processEvents()
        self.assertTrue(self.result().blocked)
        self.assertNotIn("350", self.node("watch").get_widget("display").get_value())
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 350})
        self.window.graph.delete_node(self.node("slider"))
        self.app.processEvents()
        self.assertTrue(self.result().blocked)
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 350})

    def test_round_trip_parameters_names_positions_and_connections(self):
        slider = self.node("slider")
        slider.set_name("Promień")
        slider.set_pos(-550, 200)
        slider.set_property("value", 12.5)
        self.app.processEvents()
        with tempfile.TemporaryDirectory(dir=self.output) as folder:
            path = Path(folder) / "próba.noodles"
            self.assertTrue(self.window._save_to(path))
            session = read_document(path, self.window.node_ports)
            self.window.load_session(session, path)
            self.app.processEvents()
            loaded = self.node("slider")
            self.assertEqual(loaded.name(), "Promień")
            self.assertEqual(loaded.pos(), [-550, 200])
            self.assertEqual(loaded.get_property("value"), 12.5)
            self.assertEqual(self.result().outputs, {"Value": 225})
            self.assertTrue(self.window.graph.undo_stack().isClean())

    def test_rejected_open_keeps_current_graph(self):
        with tempfile.TemporaryDirectory(dir=self.output) as folder:
            path = Path(folder) / "broken.noodles"
            path.write_text('{"format":"NoodleS","schema_version":99}', encoding="utf-8")
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(path), "")), \
                 patch.object(self.window, "_error") as error:
                self.window.open_document()
            error.assert_called_once()
            self.assertEqual(self.result().outputs, {"Value": 350})
            self.assertEqual(len(self.window.graph.all_nodes()), 5)

    def test_invalid_connection_and_duplicate_input_rejected(self):
        data = {"format": "NoodleS", "schema_version": 1,
                "session": self.window.graph.serialize_session()}
        broken = copy.deepcopy(data)
        broken["session"]["connections"][0]["in"][1] = "MissingPort"
        with self.assertRaises(DocumentError):
            validate_document(broken, self.window.node_ports)
        broken = copy.deepcopy(data)
        broken["session"]["connections"].append(broken["session"]["connections"][0])
        with self.assertRaises(DocumentError):
            validate_document(broken, self.window.node_ports)

    def test_save_failure_keeps_existing_file(self):
        with tempfile.TemporaryDirectory(dir=self.output) as folder:
            path = Path(folder) / "saved.noodles"
            write_document(path, self.window.graph.serialize_session())
            before = path.read_bytes()
            with patch("noodles.document.os.replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    write_document(path, {"nodes": {}})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_window_shell_and_all_components(self):
        expected_count = len(self.window.graph.all_nodes()) + len(self.window.node_ports)
        for kind in self.window.node_ports:
            self.window.graph.create_node(kind)
        self.app.processEvents()
        self.assertEqual(len(self.window.graph.all_nodes()), expected_count)
        data = {"format": "NoodleS", "schema_version": 1,
                "session": self.window.graph.serialize_session()}
        session = validate_document(json.loads(json.dumps(data)), self.window.node_ports)
        self.window.load_session(session)
        self.app.processEvents()
        self.assertEqual(len(self.window.graph.all_nodes()), expected_count)
        self.window.new_document()
        self.assertEqual(len(self.window.graph.all_nodes()), 0)

    def test_inspector_edit_undo_and_selection(self):
        node = self.node("number")
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.window.evaluate_now()
        inspector = self.window.properties
        self.assertEqual(inspector.node_id, node.id)
        self.assertEqual(inspector.value_edit.value(), 10)
        inspector.value_edit.setText("12")
        inspector.value_edit.editingFinished.emit()
        self.app.processEvents()
        self.assertEqual(self.result().outputs, {"Value": 444})
        self.assertEqual(node.get_widget("value").get_value(), 12)
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(inspector.value_edit.value(), 10)
        self.assertEqual(self.result().outputs, {"Value": 350})
        inspector.name_edit.setText("Liczba bazowa")
        inspector.name_edit.editingFinished.emit()
        self.app.processEvents()
        self.assertEqual(node.name(), "Liczba bazowa")
        self.window.graph.clear_selection()
        self.window.evaluate_now()
        self.assertIsNone(inspector.node_id)
        self.assertEqual(inspector.stack.currentIndex(), 0)

    def test_workbench_columns_align_after_resize(self):
        self.window.show()
        for width, height in ((1360, 860), (1080, 650), (1600, 960)):
            self.window.resize(width, height)
            self.app.processEvents()
            panels = (self.window.library_panel, self.window.canvas_panel, self.window.properties_panel)
            self.assertEqual(len({panel.geometry().top() for panel in panels}), 1)
            self.assertEqual(len({panel.geometry().bottom() for panel in panels}), 1)

    def test_library_search_and_add_result(self):
        self.window.library_search.setText("multi")
        self.app.processEvents()
        visible = []
        for index in range(self.window.palette.topLevelItemCount()):
            category = self.window.palette.topLevelItem(index)
            if not category.isHidden():
                visible.extend(category.child(i).text(0) for i in range(category.childCount())
                               if not category.child(i).isHidden())
        self.assertEqual(visible, ["Multiplication"])
        count = len(self.window.graph.all_nodes())
        self.window.library_search.returnPressed.emit()
        self.app.processEvents()
        self.assertEqual(len(self.window.graph.all_nodes()), count + 1)
        self.assertEqual(self.window.graph.selected_nodes()[0].OPERATION, "multiplication")


if __name__ == "__main__":
    unittest.main()
