"""Focused Number input tests, including the shared Double/Integer control."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtGui, QtWidgets
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.window import MainWindow


class NumberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.node = self.window.add_node("NoodleS.Inputs.NumberNode")
        self.widget = self.node.get_widget("value")
        self.inspector = self.window.properties
        self.stack = self.window.graph.undo_stack()
        self.stack.clear()
        self.app.processEvents()

    def tearDown(self):
        self.stack.setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def commit(self, editor, text):
        editor.setText(text)
        editor.editingFinished.emit()
        self.app.processEvents()

    def output(self):
        return self.window.evaluation.results[self.node.id].outputs["Number"]

    def test_default_double_and_properties(self):
        self.assertEqual(self.node.get_property("mode"), "double")
        self.assertTrue(self.inspector.double_button.isChecked())
        self.assertFalse(self.inspector.mode_switch.isHidden())
        self.assertTrue(self.inspector.min_section.isHidden())
        self.assertTrue(self.inspector.max_section.isHidden())
        self.commit(self.inspector.value_edit, "12.3456")
        self.assertEqual(self.widget.get_value(), 12.3456)
        self.assertIs(type(self.output()), float)

    def test_integer_rounding_from_both_editors(self):
        self.inspector.integer_button.click()
        self.app.processEvents()
        for text, expected in (("12.7", 13), ("12.2", 12), ("2.5", 3), ("-2.5", -3), ("-12.7", -13)):
            for editor in (self.inspector.value_edit, self.widget.spin):
                self.commit(editor, text)
                self.assertEqual(self.node.get_property("value"), expected)
                self.assertEqual(self.widget.get_value(), expected)
                self.assertIs(type(self.output()), int)
                self.assertEqual(self.inspector.value_edit.text(), str(expected))

    def test_mode_change_and_rounding_undo_together(self):
        self.node.set_property("value", -7.5)
        self.stack.clear()
        self.inspector.integer_button.click()
        self.app.processEvents()
        self.assertEqual(self.node.number_state(), {"mode": "integer", "value": -8})
        self.assertEqual(self.stack.count(), 1)
        self.stack.undo()
        self.app.processEvents()
        self.assertEqual(self.node.number_state(), {"mode": "double", "value": -7.5})
        self.assertEqual(self.widget.get_value(), -7.5)
        self.assertTrue(self.inspector.double_button.isChecked())
        self.stack.redo()
        self.app.processEvents()
        self.assertEqual(self.widget.get_value(), -8)

    def test_switch_back_to_double_accepts_decimal_value(self):
        self.inspector.integer_button.click()
        self.app.processEvents()
        self.inspector.double_button.click()
        self.app.processEvents()
        self.commit(self.widget.spin, "0.125")
        self.assertEqual(self.output(), 0.125)
        self.assertIs(type(self.output()), float)

    def test_invalid_input_keeps_previous_number(self):
        self.node.set_property("value", 8.25)
        self.app.processEvents()
        for text in ("", "-", "NaN", "Infinity", "abc"):
            self.commit(self.inspector.value_edit, text)
            self.assertEqual(self.node.get_property("value"), 8.25)
        for value in (True, "x", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.node.set_property("value", value)
        with self.assertRaises(ValueError):
            self.node.set_property("mode", "unknown")

    def test_numeric_edits_do_not_rebuild_node_layout(self):
        with patch.object(self.node.view, "draw_node", wraps=self.node.view.draw_node) as draw:
            self.commit(self.widget.spin, "3.25")
            self.inspector.integer_button.click()
            self.app.processEvents()
            draw.assert_not_called()

    def test_arrow_buttons_use_mode_step_and_support_undo(self):
        up, down = self.widget.spin._step_buttons
        self.node.set_property("value", 2.25)
        self.stack.clear()
        up.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 2.35)
        self.stack.undo()
        self.app.processEvents()
        self.assertEqual(self.output(), 2.25)
        down.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 2.15)
        self.inspector.integer_button.click()
        self.app.processEvents()
        up.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 3)
        self.assertIs(type(self.output()), int)
        down.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 2)

    def test_arrow_buttons_commit_text_and_clamp_at_bounds(self):
        field = self.widget.spin
        up, down = field._step_buttons
        field.setText("1.25")
        up.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 1.35)
        self.node.set_property("value", 1_000_000_000)
        up.click()
        self.app.processEvents()
        self.assertEqual(self.output(), 1_000_000_000)
        self.node.set_property("value", -1_000_000_000)
        down.click()
        self.app.processEvents()
        self.assertEqual(self.output(), -1_000_000_000)
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Up, QtCore.Qt.NoModifier)
        field.keyPressEvent(event)
        self.app.processEvents()
        self.assertEqual(self.output(), -999_999_999.9)

    def test_number_container_fits_editor_without_default_blank_width(self):
        self.window.show()
        self.app.processEvents()
        group = self.widget.widget()
        self.assertLessEqual(group.width(), self.widget.spin.width() + 8)
        original = self.node.view.boundingRect().size()
        self.inspector.integer_button.click()
        self.widget.spin._step_buttons[0].click()
        self.app.processEvents()
        self.assertEqual(self.node.view.boundingRect().size(), original)

    def test_round_trip_preserves_integer_mode(self):
        self.node.set_property("value", 45.6)
        self.node.set_property("mode", "integer")
        output = Path(__file__).resolve().parents[1] / ".test-output"
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as folder:
            path = Path(folder) / "number.noodles"
            write_document(path, self.window.graph.serialize_session())
            self.window.load_session(read_document(path, self.window.node_ports), path)
        restored = self.window.graph.all_nodes()[0]
        self.assertEqual(restored.number_state(), {"mode": "integer", "value": 46})
        self.assertIs(type(restored.get_widget("value").get_value()), int)

    def test_old_files_default_to_double(self):
        data = {"format": "NoodleS", "schema_version": 1, "session": self.window.graph.serialize_session()}
        record = next(iter(data["session"]["nodes"].values()))
        record["custom"] = {"value": 2.75}
        session = validate_document(data, self.window.node_ports)
        state = next(iter(session["nodes"].values()))["custom"]
        self.assertEqual(state, {"mode": "double", "value": 2.75})
        record["custom"] = {"value": 2, "mode": "invalid"}
        with self.assertRaises(DocumentError):
            validate_document(data, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
