"""Inclusive Range lists, topology, limits and real Qt Properties edits."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.datatree import Branch, DataTree, MAX_ITEMS
from noodles.backend.domain import DomainValue
from noodles.backend.range import evaluate_range
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.window import MainWindow


class RangeDataTests(unittest.TestCase):
    def test_default_segments_and_inclusive_exact_endpoints(self):
        default = evaluate_range({}, {})
        self.assertEqual(default["Count"], 11)
        self.assertEqual(default["R"].values(), tuple(i / 10 for i in range(11)))
        self.assertEqual(default["R"], default["Flat"])
        output = evaluate_range({}, {"D": DomainValue(0.1, 0.3), "N": 3})
        self.assertEqual(output["R"].values()[0], 0.1)
        self.assertEqual(output["R"].values()[-1], 0.3)
        self.assertEqual(output["Count"], 4)
        self.assertEqual(evaluate_range({}, {"D": DomainValue(8, -2), "N": 1})["R"].values(), (8, -2))
        self.assertEqual(evaluate_range({}, {"D": DomainValue(8, -2), "N": 2})["R"].values(), (8, 3, -2))

    def test_multiple_lists_keep_branches_and_flat_preserves_keys(self):
        domains = DataTree((Branch((2,), (DomainValue(0, 2), DomainValue(10, 14)), ("a", "b")),))
        output = evaluate_range({}, {"D": domains, "N": [2, 1]})
        self.assertEqual(tuple(b.path for b in output["R"].branches), ((2, 0), (2, 1)))
        self.assertEqual(tuple(b.items for b in output["R"].branches), ((0, 1, 2), (10, 14)))
        self.assertEqual(output["Count"], 5)
        self.assertEqual(output["Flat"].branches[0].path, (0,))
        self.assertEqual(output["Flat"].values(), (0, 1, 2, 10, 14))
        self.assertEqual(output["Flat"].branches[0].keys, tuple(k for b in output["R"].branches for k in b.keys))

    def test_branch_paths_matching_repeat_last_and_no_path_collisions(self):
        domains = DataTree((Branch((3,), (DomainValue(0, 2), DomainValue(4, 8))),
                            Branch((3, 0), (DomainValue(10, 12),))))
        counts = DataTree((Branch((3,), (2,)), Branch((3, 0), (1,))))
        output = evaluate_range({}, {"D": domains, "N": counts})
        self.assertEqual(tuple(b.path for b in output["R"].branches), ((3, 0), (3, 1), (3, 0, 0)))
        self.assertEqual(tuple(b.items for b in output["R"].branches), ((0, 1, 2), (4, 6, 8), (10, 12)))
        singletons = DataTree((Branch((6,), (DomainValue(0, 2),)), Branch((9,), (DomainValue(4, 8),))))
        self.assertEqual(tuple(b.path for b in evaluate_range({}, {"D": singletons, "N": 2})["R"].branches), ((6,), (9,)))
        mismatch = DataTree((Branch((6,), (2,)), Branch((8,), (2,))))
        with self.assertRaisesRegex(ValueError, "paths differ"):
            evaluate_range({}, {"D": singletons, "N": mismatch})

    def test_graft_flatten_and_empty_inputs_never_create_default_ranges(self):
        graft = evaluate_range({"tree_modes": {"N": "graft"}}, {"N": [1, 2]})
        self.assertEqual(tuple(b.path for b in graft["R"].branches), ((0, 0), (0, 1)))
        self.assertEqual(tuple(b.items for b in graft["R"].branches), ((0, 1), (0, 0.5, 1)))
        for inputs in ({"D": []}, {"N": []}, {"D": DataTree(())}, {"N": DataTree(())}):
            output = evaluate_range({}, inputs)
            self.assertEqual(output["Count"], 0)
            self.assertEqual(output["R"].count, 0)
            self.assertEqual(output["Flat"].count, 0)
        counts = DataTree((Branch((4,), (1,)), Branch((9,), (2,))))
        flat = evaluate_range({"tree_modes": {"N": "flatten"}}, {"N": counts})
        self.assertEqual(tuple(b.path for b in flat["R"].branches), ((0, 0), (0, 1)))

    def test_output_limit_is_preflighted_before_allocating_any_range(self):
        self.assertEqual(evaluate_range({"steps": MAX_ITEMS - 1}, {})["Count"], MAX_ITEMS)
        with patch("noodles.backend.range.Branch") as output_branch:
            with self.assertRaisesRegex(ValueError, "output value limit"):
                evaluate_range({}, {"N": [MAX_ITEMS - 1, 1]})
            output_branch.assert_not_called()
        for value in (True, 0, -1, 2.5, MAX_ITEMS, "3", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_range({}, {"N": value})
        for value in (3, [0, 1], {"start": 0, "end": 1}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "requires a Domain"):
                evaluate_range({}, {"D": value})

    def test_failed_input_clears_dependent_outputs_and_valid_edit_recovers(self):
        engine = GraphEngine()
        def graph(steps):
            return [NodeSpec("n", "number", {"value": steps}),
                    NodeSpec("r", "range", inputs={"N": Connection("n", "Number")}),
                    NodeSpec("w", "watch", inputs={"Value": Connection("r", "R")})]
        self.assertEqual(engine.evaluate(graph(3)).results["r"].outputs["Count"], 4)
        bad = engine.evaluate(graph(3.5))
        self.assertTrue(bad.results["r"].error)
        self.assertEqual(bad.results["r"].outputs, {})
        self.assertTrue(bad.results["w"].blocked)
        self.assertEqual(engine.evaluate(graph(1)).results["w"].outputs["Value"].values(), (0, 1))
        self.assertEqual(engine.evaluate(graph(1)).computed, ())


class RangeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.node = self.window.add_node("NoodleS.Math.RangeNode")
        self.window.show()
        self.app.processEvents()
        self.panel = self.window.properties.range_properties

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def edit(self, key, value):
        editor = self.panel.editors[key]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, value)
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.app.processEvents()

    def test_real_properties_steps_clamp_round_undo_and_topology_toggle(self):
        self.edit("steps", "2.6")
        self.assertEqual(self.node.get_property("steps"), 3)
        self.assertEqual(self.window.evaluation.results[self.node.id].outputs["Count"], 4)
        self.edit("steps", "0")
        self.assertEqual(self.node.get_property("steps"), 1)
        self.edit("steps", "99999")
        self.assertEqual(self.node.get_property("steps"), MAX_ITEMS - 1)
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertEqual(self.panel.editors["steps"].value(), 1)
        for mode, expected in (("graft", {"N": "graft"}), ("flatten", {"N": "flatten"}), ("flatten", {})):
            QTest.mouseClick(self.panel.modifiers["N"].buttons[mode], QtCore.Qt.LeftButton)
            self.app.processEvents()
            self.assertEqual(self.node.get_property("tree_modes"), expected)

    def test_domain_and_number_live_previews_then_disconnect_restore_defaults(self):
        self.node.set_property("start", -5)
        source = self.window.graph.create_node("NoodleS.Math.DomainNode")
        source.set_property("end", 8)
        source.outputs()["D"].connect_to(self.node.inputs()["D"])
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 2)
        number.outputs()["Number"].connect_to(self.node.inputs()["N"])
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.app.processEvents()
        self.assertEqual(self.panel.previews["D"].text(), "[0 → 8]")
        self.assertEqual(self.panel.previews["N"].text(), "2")
        self.assertIs(self.panel.stacks["D"].currentWidget(), self.panel.previews["D"])
        source.set_property("end", 12)
        self.app.processEvents()
        self.assertEqual(self.panel.previews["D"].text(), "[0 → 12]")
        self.assertEqual(self.window.evaluation.results[self.node.id].outputs["R"].values(), (0, 6, 12))
        number.set_property("value", 2.5)
        self.app.processEvents()
        self.assertEqual(self.panel.previews["N"].text(), "No valid input")
        self.assertTrue(self.window.evaluation.results[self.node.id].error)
        self.node.inputs()["N"].clear_connections()
        self.node.inputs()["D"].clear_connections()
        self.app.processEvents()
        self.assertEqual(self.panel.editors["start"].value(), -5)
        self.assertEqual(self.panel.editors["steps"].value(), 10)
        self.assertIs(self.panel.stacks["D"].currentWidget(), self.panel.stacks["D"].widget(0))

    def test_domain_range_point_chain_generates_one_parametric_object(self):
        domain = self.window.graph.create_node("NoodleS.Math.DomainNode")
        domain.set_property("end", 200)
        domain.outputs()["D"].connect_to(self.node.inputs()["D"])
        self.node.set_property("steps", 199)
        point = self.window.graph.create_node("NoodleS.Geometry.PointNode")
        self.node.outputs()["R"].connect_to(point.inputs()["X"])
        self.window.evaluate_now()
        result = self.window.evaluation.results[point.id]
        self.assertIsNone(result.error)
        self.assertEqual(result.parametric_object.points.count, 200)
        self.assertEqual(result.parametric_object.points.values()[-1].xyz, (200, 0, 0))

    def test_save_reload_all_outputs_defaults_and_modifier_validation(self):
        self.node.set_property("start", 10)
        self.node.set_property("end", -10)
        self.node.set_property("steps", 4)
        self.node.set_property("tree_modes", {"D": "graft"})
        for port in ("R", "Flat", "Count"):
            watch = self.window.graph.create_node("NoodleS.Data.WatchNode")
            self.node.outputs()[port].connect_to(watch.inputs()["Value"])
        self.window.evaluate_now()
        session = self.window.graph.serialize_session()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as directory:
            path = Path(directory) / "range.noodles"
            write_document(path, session)
            clean = read_document(path, self.window.node_ports)
        self.window.graph.deserialize_session(clean, clear_session=True)
        self.window.evaluate_now()
        restored = next(n for n in self.window.graph.all_nodes() if n.OPERATION == "range")
        self.assertEqual(restored.range_state(), {"start": 10, "end": -10, "steps": 4, "tree_modes": {"D": "graft"}})
        self.assertTrue(all(len(p.connected_ports()) == 1 for p in restored.output_ports()))
        self.assertEqual(self.window.evaluation.results[restored.id].outputs["R"].values(), (10, 5, 0, -5, -10))
        for invalid in ({"steps": 0}, {"steps": 3.5}, {"start": float("nan")}, {"tree_modes": {"A": "graft"}}):
            data = {"format": "NoodleS", "schema_version": 1, "session": copy.deepcopy(session)}
            data["session"]["nodes"][self.node.id]["custom"].update(invalid)
            with self.subTest(invalid=invalid), self.assertRaises(DocumentError):
                validate_document(data, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
