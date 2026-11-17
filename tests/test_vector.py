"""Real Vector producer, typed arithmetic, tree alignment and UI persistence."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.math_nodes import evaluate_math
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import read_document, write_document
from noodles.window import MainWindow


class VectorDataTests(unittest.TestCase):
    def test_zero_default_scalar_and_magnitude(self):
        self.assertEqual(evaluate_math("vector", {}, {}), {"Vector": VectorValue((0, 0, 0)), "Length": 0})
        result = evaluate_math("vector", {"x": 3, "y": -4, "z": 12}, {})
        self.assertEqual(result, {"Vector": VectorValue((3, -4, 12)), "Length": 13})
        self.assertEqual(evaluate_math("vector", {}, {"X": -2})["Length"], 2)

    def test_coordinate_trees_paths_lengths_keys_and_graft(self):
        x = DataTree((Branch((4,), (3, 6), ("a", "b")), Branch((9,), (0,), ("c",))))
        y = DataTree((Branch((9,), (5,)), Branch((4,), (4,))))
        result = evaluate_math("vector", {}, {"X": x, "Y": y})
        self.assertEqual(tuple(b.path for b in result["Vector"].branches), ((4,), (9,)))
        self.assertEqual(tuple(v.xyz for v in result["Vector"].values()), ((3, 4, 0), (6, 4, 0), (0, 5, 0)))
        self.assertEqual(result["Length"].values()[0], 5)
        self.assertEqual(tuple(b.keys for b in result["Vector"].branches), tuple(b.keys for b in result["Length"].branches))
        grid = evaluate_math("vector", {"tree_modes": {"Y": "graft"}}, {"X": [0, 1, 2], "Y": [10, 20]})
        self.assertEqual(tuple(b.path for b in grid["Vector"].branches), ((0, 0), (0, 1)))
        self.assertEqual(grid["Vector"].count, 6)
        self.assertEqual(tuple(v.xyz for v in grid["Vector"].branches[1].items), ((0, 20, 0), (1, 20, 0), (2, 20, 0)))

    def test_legacy_flat_slot_assignment_and_single_item_list_cardinality(self):
        x = DataTree((Branch((4,), (1, 2)), Branch((9,), (3, 4))))
        result = evaluate_math("vector", {}, {"X": x, "Y": [10, 20, 30, 40]})
        self.assertEqual(tuple(v.xyz for v in result["Vector"].values()), ((1, 10, 0), (2, 20, 0), (3, 30, 0), (4, 40, 0)))
        one = evaluate_math("vector", {}, {"X": [3], "Y": [4]})
        self.assertIsInstance(one["Vector"], DataTree)
        self.assertEqual(one["Length"].values(), (5,))
        with self.assertRaisesRegex(ValueError, "ambiguous flat"):
            evaluate_math("vector", {}, {"X": x, "Y": [1, 2, 3]})

    def test_empty_invalid_coordinates_nonfinite_length_and_paths(self):
        for incoming in ({"X": []}, {"Y": DataTree(())}):
            result = evaluate_math("vector", {}, incoming)
            self.assertEqual(result["Vector"].count, 0)
            self.assertEqual(result["Length"].count, 0)
        for value in (True, float("nan"), float("inf"), VectorValue((1, 2, 3)), {"id": "native"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_math("vector", {}, {"X": value})
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_math("vector", {}, {"X": 1.7e308, "Y": 1.7e308})
        with self.assertRaisesRegex(ValueError, "paths differ"):
            evaluate_math("vector", {}, {"X": DataTree((Branch((1,), (1,)), Branch((2,), (2,)))),
                                         "Y": DataTree((Branch((4,), (1,)), Branch((5,), (2,))))})

    def test_actual_vector_sources_feed_all_typed_operations_and_clear_failures(self):
        engine = GraphEngine()
        def graph(disabled=False):
            return [NodeSpec("a", "vector", {"x": 1, "y": 2, "z": 3}, disabled=disabled),
                    NodeSpec("b", "vector", {"x": 4, "y": 5, "z": 6}),
                    *[NodeSpec(op, op, inputs={"A": Connection("a", "Vector"), "B": Connection("b", "Vector")})
                      for op in ("addition", "subtraction", "multiplication")],
                    NodeSpec("square", "square", inputs={"X": Connection("a", "Length")})]
        result = engine.evaluate(graph())
        self.assertEqual(result.results["addition"].outputs["R"], VectorValue((5, 7, 9)))
        self.assertEqual(result.results["subtraction"].outputs["R"], VectorValue((-3, -3, -3)))
        self.assertEqual(result.results["multiplication"].outputs["R"], 32)
        self.assertAlmostEqual(result.results["square"].outputs["Y"], 14)
        self.assertIsNone(result.results["a"].parametric_object)
        failed = engine.evaluate(graph(True))
        for key in ("addition", "subtraction", "multiplication", "square"):
            self.assertTrue(failed.results[key].blocked)
            self.assertEqual(failed.results[key].outputs, {})
        self.assertEqual(engine.evaluate(graph()).results["multiplication"].outputs["R"], 32)


class VectorWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.node = self.window.add_node("NoodleS.Math.VectorNode")
        self.window.show()
        self.settle()

    def settle(self):
        self.app.processEvents()
        self.window.grab()
        QTest.qWait(30)

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_real_coordinate_typing_undo_length_and_preview_disconnect(self):
        panel = self.window.properties.math_properties
        self.assertEqual(list(self.node.inputs()), ["X", "Y", "Z"])
        self.assertEqual(list(self.node.outputs()), ["Vector", "Length"])
        editor = panel.editors["x"]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, "3")
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[self.node.id].outputs["Length"], 3)
        self.assertIn("Length · 3", self.window.properties.output.text())
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(editor.value(), 0)
        self.node.set_property("x", 7)
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 4)
        number.outputs()["Number"].connect_to(self.node.inputs()["X"])
        self.window.graph.clear_selection()
        self.node.set_selected(True)
        self.settle()
        self.assertEqual(panel.previews["X"].text(), "4")
        self.assertIs(panel.stacks["X"].currentWidget(), panel.previews["X"])
        self.node.inputs()["X"].clear_connections()
        self.settle()
        self.assertEqual(panel.editors["x"].value(), 7)

    def test_save_reload_vector_parameters_modifiers_and_both_output_connections(self):
        self.node.set_property("x", 3)
        self.node.set_property("y", 4)
        self.node.set_property("tree_modes", {"X": "graft"})
        for port in ("Vector", "Length"):
            watch = self.window.graph.create_node("NoodleS.Data.WatchNode")
            self.node.outputs()[port].connect_to(watch.inputs()["Value"])
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / "vector.noodles"
            write_document(path, self.window.graph.serialize_session())
            clean = read_document(path, self.window.node_ports)
        self.window.load_session(clean)
        self.window.evaluate_now()
        node = next(n for n in self.window.graph.all_nodes() if n.OPERATION == "vector")
        self.assertEqual(node.math_state(), {"x": 3, "y": 4, "z": 0, "tree_modes": {"X": "graft"}})
        self.assertEqual(self.window.evaluation.results[node.id].outputs["Length"].values(), (5,))
        self.assertTrue(all(len(p.connected_ports()) == 1 for p in node.output_ports()))


if __name__ == "__main__":
    unittest.main()
