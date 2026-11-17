"""Remaining Ryven numeric contracts and their Qt/document integration."""
import copy
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch, DataTree, MAX_ITEMS
from noodles.backend.domain import DomainValue, evaluate_domain
from noodles.backend.math_nodes import MATH_SPECS, evaluate_math
from noodles.backend.point import PointValue
from noodles.backend.range import evaluate_range
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.window import MainWindow


class MathDataTests(unittest.TestCase):
    def test_equality_returns_complementary_masks_with_shared_default(self):
        tree = DataTree((Branch((4,), (2, 0, 1, 2)), Branch((8,), ())))
        result = evaluate_math('equality', {'b': 2}, {'A': tree})
        self.assertEqual(result['='].values(), (True, False, False, True))
        self.assertEqual(result['≠'].values(), (False, True, True, False))
        self.assertEqual([b.path for b in result['='].branches], [(4,), (8,)])
        self.assertEqual(result['='].branches[-1].items, ())
        self.assertEqual(evaluate_math('equality', {}, {'A': 1, 'B': 1.0}), {'=': True, '≠': False})

    def test_deconstruct_domain_keeps_order_and_accepts_degenerate_bounds(self):
        bounds = evaluate_math('bounds', {}, {'N': [4]})['I']
        self.assertEqual(evaluate_math('deconstruct_domain', {}, {'I': bounds}), {'S': 4, 'E': 4})
        domains = DataTree((Branch((7,), (DomainValue(5, 2), DomainValue(-1, 8)), ('a', 'b')),
                            Branch((9,), ())))
        result = evaluate_math('deconstruct_domain', {}, {'I': domains})
        self.assertEqual(result['S'].branches, (Branch((7,), (5, -1), ('a', 'b')), Branch((9,), ())))
        self.assertEqual(result['E'].branches, (Branch((7,), (2, 8), ('a', 'b')), Branch((9,), ())))

    def test_subtraction_vector_order_zero_numeric_compatibility_and_invalid_pairs(self):
        a, b = VectorValue((8, -2, 4)), VectorValue((3, 5, -1))
        self.assertEqual(evaluate_math("subtraction", {}, {"A": a, "B": b})["R"], VectorValue((5, -7, 5)))
        self.assertEqual(evaluate_math("subtraction", {}, {"A": b, "B": a})["R"], VectorValue((-5, 7, -5)))
        self.assertEqual(evaluate_math("subtraction", {}, {"A": a, "B": a})["R"], VectorValue((0, 0, 0)))
        self.assertEqual(evaluate_math("subtraction", {}, {"A": [8, -2, 4], "B": 3})["R"].values(), (5, -5, 1))
        for left, right in ((a, 2), (2, a), (PointValue("a", (1, 2, 3)), PointValue("b", (4, 5, 6)))):
            with self.subTest(left=left, right=right), self.assertRaisesRegex(ValueError, "Number − Number or Vector − Vector"):
                evaluate_math("subtraction", {}, {"A": left, "B": right})
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_math("subtraction", {}, {"A": VectorValue((1e308, 0, 0)), "B": VectorValue((-1e308, 0, 0))})

    def test_subtraction_vector_trees_keep_paths_keys_repeat_last_and_modifiers(self):
        a = DataTree((Branch((4,), (VectorValue((8, 2, 1)), VectorValue((6, 4, 2))), ("a", "b")),
                      Branch((9,), (VectorValue((5, 6, 7)),), ("c",))))
        b = DataTree((Branch((9,), (VectorValue((1, 2, 3)),), ("d",)),
                      Branch((4,), (VectorValue((2, 1, 0)),), ("e",))))
        result = evaluate_math("subtraction", {}, {"A": a, "B": b})["R"]
        self.assertEqual(tuple(branch.path for branch in result.branches), ((4,), (9,)))
        self.assertEqual(tuple(v.xyz for v in result.values()), ((6, 1, 1), (4, 3, 2), (4, 4, 4)))
        self.assertEqual(result.branches[0].keys, ("a|e", "b|e"))
        graft = evaluate_math("subtraction", {"tree_modes": {"A": "graft"}}, {"A": a, "B": VectorValue((1, 1, 1))})["R"]
        self.assertEqual(tuple(branch.path for branch in graft.branches), ((4, 0), (4, 1), (9, 0)))
        flat = evaluate_math("subtraction", {"tree_modes": {"A": "flatten"}}, {"A": a, "B": VectorValue((1, 1, 1))})["R"]
        self.assertEqual(flat.branches[0].path, (0,))
        self.assertEqual(tuple(v.xyz for v in flat.values()), ((7, 1, 0), (5, 3, 1), (4, 5, 6)))
        self.assertEqual(evaluate_math("subtraction", {}, {"A": DataTree(()), "B": VectorValue((1, 2, 3))})["R"].count, 0)

    def test_binary_numeric_legacy_rules_and_scalar_list_cardinality(self):
        self.assertEqual(evaluate_math("subtraction", {}, {"A": 7, "B": 3})["R"], 4)
        self.assertEqual(evaluate_math("division", {}, {"A": [10, 20, 30], "B": [2, 4]})["R"].values(), (5, 5, 7.5))
        self.assertEqual(evaluate_math("minimum", {}, {"A": [4, -1, 9], "B": 2})["R"].values(), (2, -1, 2))
        self.assertIsInstance(evaluate_math("subtraction", {}, {"A": [7], "B": 3})["R"], DataTree)
        with self.assertRaisesRegex(ValueError, "zero"):
            evaluate_math("division", {}, {"A": [10, 20], "B": [2, 0]})

    def test_minimum_flat_slot_assignment_and_ambiguous_list_rejection(self):
        tree = DataTree((Branch((4,), (2, 4)), Branch((9,), (6, 8))))
        result = evaluate_math("minimum", {}, {"A": tree, "B": [10, 3, 2, 9]})["R"]
        self.assertEqual(tuple(b.path for b in result.branches), ((4,), (9,)))
        self.assertEqual(result.values(), (2, 3, 2, 8))
        with self.assertRaisesRegex(ValueError, "ambiguous flat"):
            evaluate_math("minimum", {}, {"A": tree, "B": [1, 2, 3]})
        self.assertEqual(evaluate_math("minimum", {}, {"A": tree, "B": [3, 5]})["R"].values(), (2, 4, 3, 5))

    def test_sine_radians_square_and_tree_paths_keys(self):
        self.assertAlmostEqual(evaluate_math("sine", {}, {"X": math.pi / 2})["Y"], 1)
        self.assertAlmostEqual(evaluate_math("sine", {}, {"X": 90})["Y"], math.sin(90))
        self.assertEqual(evaluate_math("square", {}, {"X": -3})["Y"], 9)
        tree = DataTree((Branch((7, 1), (-2, 3), ("a", "b")),))
        output = evaluate_math("square", {}, {"X": tree})["Y"]
        self.assertEqual(output.branches[0].path, (7, 1))
        self.assertEqual(output.branches[0].keys, ("a", "b"))
        self.assertEqual(output.values(), (4, 9))
        self.assertIsInstance(evaluate_math("square", {}, {"X": [3]})["Y"], DataTree)
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_math("square", {}, {"X": 1e308})

    def test_series_defaults_negative_zero_steps_and_exact_count(self):
        default = evaluate_math("series", {}, {})
        self.assertEqual(default["S"].values(), tuple(range(10)))
        self.assertEqual(default["Count"], 10)
        output = evaluate_math("series", {"start": 1, "step": -0.25, "count": 5}, {})
        self.assertEqual(output["S"].values(), (1, 0.75, 0.5, 0.25, 0))
        self.assertEqual(evaluate_math("series", {}, {"S": 2, "N": 0, "C": 3})["S"].values(), (2, 2, 2))
        self.assertEqual(evaluate_math("series", {"count": 1}, {})["S"].values(), (0,))

    def test_series_lists_have_separate_paths_and_strict_cardinality(self):
        result = evaluate_math("series", {}, {"S": [0, 10], "N": 2, "C": [3, 2]})
        self.assertEqual(tuple(b.path for b in result["S"].branches), ((0, 0), (0, 1)))
        self.assertEqual(tuple(b.items for b in result["S"].branches), ((0, 2, 4), (10, 12)))
        self.assertEqual(result["Count"], 5)
        with self.assertRaisesRegex(ValueError, "equal item counts"):
            evaluate_math("series", {}, {"S": [0, 10], "N": [1, 2, 3]})
        start = DataTree((Branch((2,), (0, 10)), Branch((2, 0), (20,))))
        output = evaluate_math("series", {}, {"S": start, "C": 2})["S"]
        self.assertEqual(tuple(b.path for b in output.branches), ((2, 0), (2, 1), (2, 0, 0)))

    def test_series_preflights_total_limit_and_rejects_invalid_count(self):
        self.assertEqual(evaluate_math("series", {"count": MAX_ITEMS}, {})["Count"], MAX_ITEMS)
        with patch("noodles.backend.math_nodes.Branch") as output_branch:
            with self.assertRaisesRegex(ValueError, "limit"):
                evaluate_math("series", {}, {"S": [0, 1], "C": MAX_ITEMS})
            output_branch.assert_not_called()
        for value in (True, 0, -1, 2.5, MAX_ITEMS + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_math("series", {}, {"C": value})

    def test_bounds_is_one_global_interval_and_preserves_equal_data(self):
        tree = DataTree((Branch((3,), (9, -4)), Branch((8,), (20, 2))))
        self.assertEqual(evaluate_math("bounds", {}, {"N": tree})["I"], DomainValue(-4, 20))
        singleton = evaluate_math("bounds", {}, {"N": [3, 3, 3]})["I"]
        self.assertEqual(singleton, DomainValue(3, 3))
        self.assertEqual(singleton.length, 0)
        with self.assertRaisesRegex(ValueError, "cannot be equal"):
            evaluate_domain({}, {"A": 3, "B": 3})
        with self.assertRaisesRegex(ValueError, "nonzero"):
            evaluate_range({}, {"D": singleton})
        with self.assertRaisesRegex(ValueError, "at least one"):
            evaluate_math("bounds", {}, {"N": []})

    def test_remap_extrapolation_clipping_reverse_domains_and_flat_outputs(self):
        result = evaluate_math("remap_numbers", {}, {"V": [-5, 0, 5, 10, 15],
            "S": DomainValue(0, 10), "T": DomainValue(10, 20)})
        self.assertEqual(result["R"].values(), (5, 10, 15, 20, 25))
        self.assertEqual(result["C"].values(), (10, 10, 15, 20, 20))
        self.assertEqual(result["Flat R"].values(), result["R"].values())
        reverse = evaluate_math("remap_numbers", {}, {"V": 2.5, "S": DomainValue(10, 0), "T": DomainValue(20, 10)})
        self.assertEqual(reverse["R"], 12.5)
        self.assertEqual(evaluate_math("remap_numbers", {}, {"V": 0.25})["R"], 0.25)
        for port in ("S", "T"):
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, "nonzero"):
                evaluate_math("remap_numbers", {}, {"V": 2, port: DomainValue(1, 1)})

    def test_remap_domain_trees_and_numeric_modifiers_preserve_paths(self):
        values = DataTree((Branch((4,), (0, 5)), Branch((9,), (10, 20))))
        domains = DataTree((Branch((4,), (DomainValue(0, 10),)), Branch((9,), (DomainValue(10, 20),))))
        output = evaluate_math("remap_numbers", {}, {"V": values, "S": domains})
        self.assertEqual(tuple(b.path for b in output["R"].branches), ((4,), (9,)))
        self.assertEqual(output["R"].values(), (0, 0.5, 0, 1))
        self.assertEqual(output["Flat C"].branches[0].path, (0,))
        graft = evaluate_math("subtraction", {"tree_modes": {"A": "graft"}}, {"A": [1, 2], "B": 1})["R"]
        self.assertEqual(tuple(b.path for b in graft.branches), ((0, 0), (0, 1)))
        self.assertEqual(graft.values(), (0, 1))

    def test_unsupported_types_and_empty_semantics(self):
        for operation, spec in MATH_SPECS.items():
            if spec["inputs"][0].kind not in ("number", "number_or_vector"):
                continue  # Typed Point/Vector ports have separate vector-family regressions.
            port = spec["inputs"][0].port
            for value in (VectorValue((1, 2, 3)), PointValue("p", (1, 2, 3)), True, float("nan")):
                incoming = {port: value}
                if operation in ("subtraction", "division", "minimum"):
                    incoming["B"] = 2
                with self.subTest(operation=operation, value=value), self.assertRaises(ValueError):
                    evaluate_math(operation, {}, incoming)
        self.assertEqual(evaluate_math("square", {}, {"X": []})["Y"].count, 0)
        self.assertEqual(evaluate_math("series", {}, {"S": DataTree(())})["Count"], 0)
        self.assertEqual(evaluate_math("remap_numbers", {}, {"V": []})["R"].count, 0)

    def test_graph_failure_clears_all_downstream_values_and_recovers(self):
        engine = GraphEngine()
        def graph(divisor):
            return [NodeSpec("n", "number", {"value": 6}), NodeSpec("d", "number", {"value": divisor}),
                    NodeSpec("m", "division", inputs={"A": Connection("n", "Number"), "B": Connection("d", "Number")}),
                    NodeSpec("w", "watch", inputs={"Value": Connection("m", "R")})]
        self.assertEqual(engine.evaluate(graph(2)).results["w"].outputs["Value"], 3)
        bad = engine.evaluate(graph(0))
        self.assertEqual(bad.results["m"].outputs, {})
        self.assertTrue(bad.results["w"].blocked)
        self.assertEqual(engine.evaluate(graph(3)).results["w"].outputs["Value"], 2)
        self.assertEqual(engine.evaluate(graph(3)).computed, ())


class MathWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()

    def settle(self):
        self.app.processEvents()
        self.window.grab()
        QTest.qWait(30)

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_subtraction_vector_previews_output_graft_undo_and_failed_pair(self):
        a = self.window.graph.create_node("NoodleS.Math.VectorNode")
        b = self.window.graph.create_node("NoodleS.Math.VectorNode")
        for node, value in ((a, 8), (b, 3)):
            for key, coordinate in zip(("x", "y", "z"), (value, 2 * value, -value)):
                node.set_property(key, coordinate)
        subtract = self.window.add_node("NoodleS.Math.SubtractionNode")
        a.outputs()["Vector"].connect_to(subtract.inputs()["A"])
        b.outputs()["Vector"].connect_to(subtract.inputs()["B"])
        watch = self.window.graph.create_node("NoodleS.Data.WatchNode", selected=False)
        subtract.outputs()["R"].connect_to(watch.inputs()["Value"])
        self.window.graph.clear_selection()
        subtract.set_selected(True)
        self.settle()
        panel = self.window.properties.math_properties
        self.assertEqual(panel.previews["A"].text(), "Vector(8, 16, -8)")
        self.assertEqual(panel.previews["B"].text(), "Vector(3, 6, -3)")
        self.assertEqual(self.window.evaluation.results[watch.id].outputs["Value"], VectorValue((5, 10, -5)))
        QTest.mouseClick(panel.modifiers["A"].buttons["graft"], QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(self.window.evaluation.results[subtract.id].outputs["R"].branches[0].path, (0, 0))
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertFalse(panel.modifiers["A"].buttons["graft"].isChecked())
        subtract.inputs()["B"].clear_connections()
        self.settle()
        self.assertEqual(self.window.evaluation.results[subtract.id].outputs, {})
        self.assertTrue(self.window.evaluation.results[watch.id].blocked)

    def test_every_node_real_properties_switch_required_ports_and_no_reserved_space(self):
        for operation, spec in MATH_SPECS.items():
            with self.subTest(operation=operation):
                node = self.window.add_node("NoodleS.Math." + spec["class"])
                self.settle()
                self.assertEqual(list(node.inputs()), [i.port for i in spec["inputs"]])
                self.assertEqual(list(node.outputs()), list(spec["outputs"]))
                panel = self.window.properties.math_properties
                self.assertTrue(panel.isVisible())
                self.assertEqual(set(panel.modifiers), set(node.inputs()))
                self.assertEqual(set(panel.editors), set(spec["defaults"]))
                self.assertFalse(any(b.isChecked() for m in panel.modifiers.values() for b in m.buttons.values()))
                for descriptor in spec["inputs"]:
                    if not descriptor.defaults:
                        self.assertEqual(panel.previews[descriptor.port].text(), "Connect input " + descriptor.port + ".")

    def test_series_typing_clamp_undo_graft_click_and_connected_read_only_preview(self):
        node = self.window.add_node("NoodleS.Math.SeriesNode")
        self.settle()
        panel = self.window.properties.math_properties
        editor = panel.editors["count"]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, "3.6")
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property("count"), 4)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(editor.value(), 10)
        for mode, expected in (("graft", {"S": "graft"}), ("flatten", {"S": "flatten"}), ("flatten", {})):
            QTest.mouseClick(panel.modifiers["S"].buttons[mode], QtCore.Qt.LeftButton)
            self.settle()
            self.assertEqual(node.get_property("tree_modes"), expected)
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 7)
        number.outputs()["Number"].connect_to(node.inputs()["C"])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        self.assertEqual(panel.previews["C"].text(), "7")
        self.assertIs(panel.stacks["C"].currentWidget(), panel.previews["C"])
        node.inputs()["C"].clear_connections()
        self.settle()
        self.assertEqual(panel.editors["count"].value(), 10)

    def test_range_bounds_remap_series_and_point_chain(self):
        series = self.window.graph.create_node("NoodleS.Math.SeriesNode")
        series.set_property("start", 10)
        series.set_property("step", 2)
        series.set_property("count", 3)
        bounds = self.window.graph.create_node("NoodleS.Math.BoundsNode")
        remap = self.window.graph.create_node("NoodleS.Math.RemapNumbersNode")
        point = self.window.graph.create_node("NoodleS.Geometry.PointNode")
        series.outputs()["S"].connect_to(bounds.inputs()["N"])
        series.outputs()["S"].connect_to(remap.inputs()["V"])
        bounds.outputs()["I"].connect_to(remap.inputs()["S"])
        remap.outputs()["R"].connect_to(point.inputs()["X"])
        self.window.evaluate_now()
        self.assertEqual(self.window.evaluation.results[remap.id].outputs["R"].values(), (0, 0.5, 1))
        result = self.window.evaluation.results[point.id]
        self.assertEqual(tuple(p.xyz for p in result.parametric_object.points.values()), ((0, 0, 0), (0.5, 0, 0), (1, 0, 0)))

    def test_all_math_save_reload_defaults_modifiers_outputs_and_validation(self):
        for operation, spec in MATH_SPECS.items():
            node = self.window.graph.create_node("NoodleS.Math." + spec["class"])
            node.set_property("tree_modes", {spec["inputs"][0].port: "graft"})
            for port in node.output_ports():
                watch = self.window.graph.create_node("NoodleS.Data.WatchNode")
                port.connect_to(watch.inputs()["Value"])
        session = self.window.graph.serialize_session()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / "math.noodles"
            write_document(path, session)
            clean = read_document(path, self.window.node_ports)
        self.window.load_session(clean)
        self.window.evaluate_now()
        for operation, spec in MATH_SPECS.items():
            node = next(n for n in self.window.graph.all_nodes() if n.OPERATION == operation)
            self.assertEqual(node.get_property("tree_modes"), {spec["inputs"][0].port: "graft"})
            self.assertTrue(all(len(port.connected_ports()) == 1 for port in node.output_ports()))
        for node_id, record in session["nodes"].items():
            if record["type_"].endswith(".SeriesNode"):
                bad = {"format": "NoodleS", "schema_version": 1, "session": copy.deepcopy(session)}
                bad["session"]["nodes"][node_id]["custom"]["count"] = 0
                with self.assertRaises(DocumentError):
                    validate_document(bad, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
