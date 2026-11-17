"""Legacy Domain semantics, tree matching, inspector interaction and files."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue, evaluate_domain
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.nodes import DomainNode
from noodles.window import MainWindow


class DomainDataTests(unittest.TestCase):
    def test_defaults_and_reversed_interval_keep_legacy_contract(self):
        outputs = evaluate_domain({}, {})
        self.assertEqual(outputs["D"].values(), (DomainValue(0, 1),))
        self.assertEqual(outputs["L"].values(), (1,))
        reversed_domain = evaluate_domain({}, {"A": 8, "B": -2})
        domain = reversed_domain["D"].values()[0]
        self.assertEqual(domain.to_wire(), {"type": "serpentine_domain", "start": 8, "end": -2})
        self.assertEqual(reversed_domain["L"].values(), (10,))

    def test_matching_paths_repeat_last_and_preserve_keys_for_length(self):
        start = DataTree((Branch((2, 0), (0, 3), ("a", "b")), Branch((5, 0), (10,), ("c",))))
        outputs = evaluate_domain({}, {"A": start, "B": [20, 30, 40]})
        self.assertEqual(tuple(b.path for b in outputs["D"].branches), ((2, 0), (5, 0)))
        self.assertEqual(outputs["L"].values(), (20, 27, 37, 10, 20, 30))
        self.assertEqual(tuple(b.keys for b in outputs["D"].branches), tuple(b.keys for b in outputs["L"].branches))
        self.assertTrue(all(isinstance(item, DomainValue) for item in outputs["D"].values()))

    def test_topology_controls_and_empty_inputs(self):
        a = DataTree((Branch((4,), (0, 1)), Branch((8,), (2,))))
        graft = evaluate_domain({"tree_modes": {"A": "graft"}}, {"A": a, "B": 10})
        self.assertEqual(tuple(b.path for b in graft["D"].branches), ((4, 0), (4, 1), (8, 0)))
        flat = evaluate_domain({"tree_modes": {"A": "flatten"}}, {"A": a, "B": 10})
        self.assertEqual(tuple(b.path for b in flat["D"].branches), ((0,),))
        self.assertEqual(evaluate_domain({}, {"A": []})["D"].count, 0)
        self.assertEqual(evaluate_domain({}, {"A": DataTree(())})["L"].count, 0)
        b = DataTree((Branch((1,), (10,)), Branch((9,), (20,))))
        with self.assertRaisesRegex(ValueError, "paths differ"):
            evaluate_domain({}, {"A": a, "B": b})

    def test_errors_clear_downstream_and_recover_without_stale_domain(self):
        engine = GraphEngine()
        def graph(value):
            return [NodeSpec("a", "number", {"value": value}),
                    NodeSpec("d", "domain", {"end": 5}, {"A": Connection("a", "Number")}),
                    NodeSpec("w", "watch", inputs={"Value": Connection("d", "D")})]
        self.assertFalse(engine.evaluate(graph(2)).results["w"].error)
        invalid = engine.evaluate(graph(5))
        self.assertIn("cannot be equal", invalid.results["d"].error)
        self.assertEqual(invalid.results["d"].outputs, {})
        self.assertTrue(invalid.results["w"].blocked)
        self.assertEqual(engine.evaluate(graph(7)).results["w"].outputs["Value"].values(), (DomainValue(7, 5),))
        self.assertEqual(engine.evaluate(graph(7)).computed, ())
        for value in (True, "3", float("nan"), float("inf"), 1e10, DomainValue(0, 1)):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                evaluate_domain({}, {"A": value})


class DomainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.domain = self.window.graph.create_node("NoodleS.Math.DomainNode")
        self.window._inspect_node(self.domain)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_real_properties_typing_topology_click_toggle_and_undo(self):
        panel = self.window.properties.domain_properties
        self.assertTrue(panel.isVisible())
        panel.editors["A"].setFocus()
        QTest.keyClick(panel.editors["A"], QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(panel.editors["A"], "-4.25")
        QTest.keyClick(panel.editors["A"], QtCore.Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.domain.get_property("start"), -4.25)
        self.assertEqual(self.window.evaluation.results[self.domain.id].outputs["L"].values(), (5.25,))
        for button, expected in (("graft", {"A": "graft"}), ("graft", {}), ("flatten", {"A": "flatten"})):
            QTest.mouseClick(panel.modifiers["A"].buttons[button], QtCore.Qt.LeftButton)
            self.app.processEvents()
            self.assertEqual(self.domain.get_property("tree_modes"), expected)
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(self.domain.get_property("tree_modes"), {})
        self.assertFalse(panel.modifiers["A"].buttons["flatten"].isChecked())

    def test_connected_input_preview_live_updates_disconnect_restores_default(self):
        self.domain.set_property("start", -5)
        slider = self.window.graph.create_node("NoodleS.Inputs.SliderNode")
        slider.set_property("value", 12.5)
        slider.outputs()["Number"].connect_to(self.domain.inputs()["A"])
        self.window.graph.clear_selection()
        self.domain.set_selected(True)
        self.app.processEvents()
        panel = self.window.properties.domain_properties
        self.assertIs(panel.stacks["A"].currentWidget(), panel.previews["A"])
        self.assertEqual(panel.previews["A"].text(), "12.5")
        self.assertFalse(panel.editors["A"].isEnabled())
        slider.set_property("value", 21.25)
        self.app.processEvents()
        self.assertEqual(panel.previews["A"].text(), "21.25")
        self.assertEqual(self.domain.get_property("start"), -5)
        self.assertEqual(self.window.properties.node_id, self.domain.id)
        slider.outputs()["Number"].disconnect_from(self.domain.inputs()["A"])
        self.app.processEvents()
        self.assertIs(panel.stacks["A"].currentWidget(), panel.editors["A"])
        self.assertEqual(panel.editors["A"].value(), -5)
        self.assertEqual(self.window.evaluation.results[self.domain.id].outputs["L"].values(), (6,))

    def test_invalid_connected_domain_is_text_not_an_editable_number(self):
        source = self.window.graph.create_node("NoodleS.Math.DomainNode")
        source.outputs()["D"].connect_to(self.domain.inputs()["A"])
        self.window.graph.clear_selection()
        self.domain.set_selected(True)
        self.app.processEvents()
        panel = self.window.properties.domain_properties
        self.assertEqual(panel.previews["A"].text(), "No valid input")
        self.assertIs(panel.stacks["A"].currentWidget(), panel.previews["A"])
        self.assertTrue(self.window.evaluation.results[self.domain.id].error)

    def test_save_reload_validates_defaults_modifiers_and_both_output_connections(self):
        self.domain.set_property("start", 9)
        self.domain.set_property("end", -2)
        self.domain.set_property("tree_modes", {"B": "graft"})
        for output in ("D", "L"):
            watch = self.window.graph.create_node("NoodleS.Data.WatchNode")
            self.domain.outputs()[output].connect_to(watch.inputs()["Value"])
        self.window.evaluate_now()
        session = self.window.graph.serialize_session()
        output = Path(__file__).resolve().parents[1] / ".test-output"
        with tempfile.TemporaryDirectory(dir=output) as directory:
            path = Path(directory) / "domain.noodles"
            write_document(path, session)
            clean = read_document(path, self.window.node_ports)
        self.window.graph.deserialize_session(clean, clear_session=True)
        self.window.evaluate_now()
        restored = next(n for n in self.window.graph.all_nodes() if isinstance(n, DomainNode))
        self.assertEqual(restored.domain_state(), {"start": 9, "end": -2, "tree_modes": {"B": "graft"}})
        self.assertEqual(len(restored.outputs()["D"].connected_ports()), 1)
        self.assertEqual(len(restored.outputs()["L"].connected_ports()), 1)
        self.assertEqual(self.window.evaluation.results[restored.id].outputs["L"].values(), (11,))
        for invalid in ({"start": float("nan")}, {"tree_modes": {"X": "graft"}}, {"tree_modes": {"A": "sort"}}):
            data = {"format": "NoodleS", "schema_version": 1, "session": copy.deepcopy(session)}
            data["session"]["nodes"][self.domain.id]["custom"].update(invalid)
            with self.subTest(invalid=invalid), self.assertRaises(DocumentError):
                validate_document(data, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
