"""Focused Slider interaction tests; no example graph or CAD operations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtWidgets
from noodles.window import MainWindow
from noodles.document import DocumentError, read_document, validate_document, write_document


class SliderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.node = self.window.add_node("NoodleS.Inputs.SliderNode")
        self.widget = self.node.get_widget("value")
        self.stack = self.window.graph.undo_stack()
        self.stack.clear()
        self.app.processEvents()

    def tearDown(self):
        self.stack.setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def drag(self, values):
        self.widget.slider.sliderPressed.emit()
        for value in values:
            self.widget.slider.setValue(value)
            self.app.processEvents()
        self.widget.slider.sliderReleased.emit()

    def test_drag_publishes_live_and_undoes_as_one_edit(self):
        self.widget.slider.sliderPressed.emit()
        for value in range(50, 10001, 50):
            self.widget.slider.setValue(value)
            self.app.processEvents()
            self.assertEqual(self.node.get_property("value"), value / 100)
            self.assertEqual(self.window.evaluation.results[self.node.id].outputs, {"Number": value / 100})
        self.widget.slider.sliderReleased.emit()
        self.assertEqual(self.stack.count(), 1)
        self.assertFalse(self.stack.isClean())
        self.stack.undo()
        self.app.processEvents()
        self.assertEqual(self.node.get_property("value"), 0)
        self.assertEqual(self.widget.slider.value(), 0)
        self.assertEqual(self.widget.spin.value(), 0)
        self.stack.redo()
        self.app.processEvents()
        self.assertEqual(self.widget.slider.value(), 10000)

    def test_separate_drags_and_numeric_edits_stay_separate(self):
        self.drag((100, 200, 300))
        self.drag((400, 500))
        self.widget.spin.setValue(12.5)
        self.app.processEvents()
        self.assertEqual(self.stack.count(), 3)
        self.stack.undo()
        self.assertEqual(self.node.get_property("value"), 5)
        self.stack.undo()
        self.assertEqual(self.node.get_property("value"), 3)
        self.stack.undo()
        self.assertEqual(self.node.get_property("value"), 0)

    def test_returning_to_start_does_not_leave_an_undo_step(self):
        self.drag((100, 500, 250, 0))
        self.assertEqual(self.stack.count(), 0)
        self.assertTrue(self.stack.isClean())

    def test_value_changes_do_not_rebuild_node_layout(self):
        with patch.object(self.node.view, "draw_node", wraps=self.node.view.draw_node) as draw:
            self.drag(range(100, 10001, 100))
            draw.assert_not_called()

    def test_keyboard_steps_do_not_merge_into_previous_drag(self):
        self.drag((200, 300))
        self.widget.slider.setValue(301)
        self.widget.slider.setValue(302)
        self.assertEqual(self.stack.count(), 3)
        self.stack.undo()
        self.assertEqual(self.widget.slider.value(), 301)

    def test_numeric_validation_and_rounding(self):
        for value in (True, "5", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.node.set_property("value", value)
        self.node.set_property("value", 25.126)
        self.assertEqual(self.widget.spin.value(), 25.13)
        self.assertEqual(self.widget.slider.value(), 2513)
        self.node.set_property("value", 200)
        self.assertEqual(self.node.get_property("value"), 100)

    def commit(self, editor, text):
        editor.setText(text)
        editor.editingFinished.emit()
        self.app.processEvents()

    def test_properties_clamp_typed_value_to_current_range(self):
        inspector = self.window.properties
        self.commit(inspector.min_edit, "-20")
        self.commit(inspector.max_edit, "50")
        self.commit(inspector.value_edit, "9999")
        self.assertEqual(self.node.get_property("value"), 50)
        self.assertEqual(inspector.value_edit.text(), "50")
        self.commit(inspector.value_edit, "-9999")
        self.assertEqual(self.node.get_property("value"), -20)
        self.assertEqual(self.widget.spin.value(), -20)
        self.assertEqual(self.widget.slider.value(), 0)
        self.commit(self.widget.spin, "12345")
        self.assertEqual(self.node.get_property("value"), 50)

    def test_reducing_range_clamps_value_in_one_undo_step(self):
        self.node.set_property("value", 75)
        self.stack.clear()
        self.node.set_property("maximum", 25)
        self.app.processEvents()
        self.assertEqual(self.node.get_property("value"), 25)
        self.assertEqual(self.stack.count(), 1)
        self.stack.undo()
        self.assertEqual(self.node.get_property("maximum"), 100)
        self.assertEqual(self.node.get_property("value"), 75)
        self.assertEqual(self.widget.spin.value(), 75)

    def test_crossed_and_equal_bounds_stay_consistent(self):
        self.node.set_property("minimum", 200)
        self.app.processEvents()
        self.assertEqual(self.node.slider_state(), {"mode": "double", "minimum": 200, "maximum": 200, "value": 200})
        self.assertFalse(self.widget.slider.isEnabled())
        self.assertEqual(self.widget.slider.maximum(), 0)
        self.node.set_property("maximum", -10)
        self.assertEqual(self.node.get_property("minimum"), -10)
        self.assertEqual(self.node.get_property("value"), -10)
        self.node.set_property("maximum", 20)
        self.assertTrue(self.widget.slider.isEnabled())

    def test_integer_toggle_rounds_state_and_returns_integer_output(self):
        self.node.set_property("minimum", -2.5)
        self.node.set_property("maximum", 8.5)
        self.node.set_property("value", 2.5)
        before = self.node.slider_state()
        self.stack.clear()
        self.window.properties.integer_button.click()
        self.app.processEvents()
        self.assertEqual(self.node.slider_state(), {"mode": "integer", "minimum": -3, "maximum": 9, "value": 3})
        output = self.window.evaluation.results[self.node.id].outputs["Number"]
        self.assertIs(type(output), int)
        self.assertEqual(self.widget.slider.maximum(), 12)
        self.widget.slider.setValue(0)
        self.app.processEvents()
        self.assertEqual(self.node.get_property("value"), -3)
        self.stack.undo()
        self.stack.undo()
        self.assertEqual(self.node.slider_state(), before)

    def test_double_toggle_restores_decimal_editing(self):
        self.window.properties.integer_button.click()
        self.app.processEvents()
        self.window.properties.double_button.click()
        self.app.processEvents()
        self.commit(self.window.properties.value_edit, "12.3456")
        self.assertEqual(self.node.get_property("value"), 12.35)
        self.assertIs(type(self.window.evaluation.results[self.node.id].outputs["Number"]), float)

    def test_invalid_text_keeps_last_valid_parameter(self):
        self.node.set_property("value", 12.5)
        self.app.processEvents()
        for text in ("", "-", "NaN", "Infinity", "hello"):
            self.commit(self.window.properties.value_edit, text)
            self.assertEqual(self.node.get_property("value"), 12.5)
            self.assertEqual(self.window.properties.value_edit.text(), "12.5")
        for key in ("minimum", "maximum"):
            for value in (True, "x", float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    self.node.set_property(key, value)

    def test_wide_integer_and_narrow_double_ranges(self):
        self.node.set_property("minimum", -1e9)
        self.node.set_property("maximum", 1e9)
        self.node.set_property("mode", "integer")
        self.assertEqual(self.widget.slider.maximum(), 2_000_000_000)
        self.widget.slider.setValue(2_000_000_000)
        self.assertEqual(self.node.get_property("value"), 1_000_000_000)
        self.node.set_property("mode", "double")
        self.node.set_property("maximum", 0.02)
        self.node.set_property("minimum", 0.01)
        self.widget.slider.setValue(0)
        self.assertEqual(self.node.get_property("value"), 0.01)
        self.widget.slider.setValue(1)
        self.assertEqual(self.node.get_property("value"), 0.02)

    def test_round_trip_preserves_configuration_and_out_of_default_value(self):
        self.node.set_property("maximum", 1000)
        self.node.set_property("minimum", 200)
        self.node.set_property("value", 321)
        self.node.set_property("mode", "integer")
        expected = self.node.slider_state()
        output = Path(__file__).resolve().parents[1] / ".test-output"
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as folder:
            path = Path(folder) / "slider.noodles"
            write_document(path, self.window.graph.serialize_session())
            self.window.load_session(read_document(path, self.window.node_ports), path)
        restored = self.window.graph.all_nodes()[0]
        self.assertEqual(restored.slider_state(), expected)
        self.assertEqual(restored.get_widget("value").get_value(), 321)
        self.assertIs(type(restored.get_widget("value").get_value()), int)

    def test_legacy_file_defaults_and_invalid_configuration(self):
        data = {"format": "NoodleS", "schema_version": 1, "session": self.window.graph.serialize_session()}
        record = next(iter(data["session"]["nodes"].values()))
        record["custom"] = {"value": 25.5}
        restored = validate_document(data, self.window.node_ports)
        state = next(iter(restored["nodes"].values()))["custom"]
        self.assertEqual(state, {"mode": "double", "minimum": 0, "maximum": 100, "value": 25.5})
        record["custom"] = {"mode": "double", "minimum": 50, "maximum": 10}
        with self.assertRaises(DocumentError):
            validate_document(data, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
