"""Former typed math contract, DataTree, Properties and saved-port migration."""
import copy
import os
from pathlib import Path
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.arithmetic import VectorValue, evaluate_arithmetic
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.point import PointValue
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document
from noodles.window import MainWindow


def run(operation, a, b, **parameters):
    return evaluate_arithmetic(operation, parameters, {"A": a, "B": b})["R"]


class ArithmeticDataTests(unittest.TestCase):
    def test_all_addition_types_and_rejected_number_xyz_pairs(self):
        a, b = VectorValue((1, 2, 3)), VectorValue((4, 5, 6))
        p, q = PointValue("p", (1, 2, 3)), PointValue("q", (4, 5, 6))
        self.assertEqual(run("addition", 2, 3), 5)
        self.assertEqual(run("addition", a, b), VectorValue((5, 7, 9)))
        for left, right in ((p, q), (p, b), (a, q)):
            result = run("addition", left, right)
            self.assertIsInstance(result, PointValue)
            self.assertEqual(result.xyz, (5, 7, 9))
            self.assertNotIn(result.key, (p.key, q.key))
        for left, right in ((2, a), (a, 2), (2, p), (p, 2)):
            with self.subTest(left=left, right=right), self.assertRaisesRegex(ValueError, "Addition requires"):
                run("addition", left, right)

    def test_all_nine_multiplication_type_pairs_scaling_and_dot_products(self):
        a, b = VectorValue((1, 2, 3)), VectorValue((4, 5, 6))
        p, q = PointValue("p", a.xyz), PointValue("q", b.xyz)
        self.assertEqual(run("multiplication", 2, 3), 6)
        for entity in (a, p):
            for left, right in ((entity, -2), (-2, entity)):
                result = run("multiplication", left, right)
                self.assertIsInstance(result, type(entity))
                self.assertEqual(result.xyz, (-2, -4, -6))
        for left, right in ((a, b), (p, q), (a, q), (p, b)):
            self.assertEqual(run("multiplication", left, right), 32)
        self.assertEqual(run("multiplication", VectorValue((0, 0, 0)), a), 0)

    def test_raw_xyz_stays_numeric_list_and_flat_numeric_text_is_compatible(self):
        for values in ([1, 2, 3], (1, 2, 3)):
            self.assertEqual(run("multiplication", values, 2).values(), (2, 4, 6))
            self.assertEqual(run("addition", values, [10, 20]).values(), (11, 22, 23))
        self.assertEqual(run("addition", "2.5", 2), 4.5)
        self.assertEqual(run("multiplication", ["2", "3"], 2).values(), (4, 6))

    def test_typed_trees_preserve_paths_matching_keys_and_point_identity(self):
        vectors = DataTree((Branch((4, 2), (VectorValue((1, 0, 0)), VectorValue((2, 0, 0))), ("a", "b")),
                            Branch((8, 2), (VectorValue((3, 0, 0)),), ("c",))))
        factors = DataTree((Branch((8, 2), (4,)), Branch((4, 2), (2, 3, 5))))
        result = run("multiplication", vectors, factors)
        self.assertEqual(tuple(b.path for b in result.branches), ((4, 2), (8, 2)))
        self.assertEqual(tuple(v.xyz for v in result.values()), ((2, 0, 0), (6, 0, 0), (10, 0, 0), (12, 0, 0)))
        self.assertTrue(result.branches[0].keys[-1].startswith("b|"))
        p = PointValue("source", (1, 2, 3))
        first = run("multiplication", p, 2)
        second = run("multiplication", PointValue("source", (4, 5, 6)), 3)
        self.assertEqual(first.key, second.key)
        self.assertEqual(p.xyz, (1, 2, 3))
        self.assertNotEqual(first.key, run("addition", p, VectorValue((1, 0, 0))).key)

    def test_graft_flatten_empty_and_unsupported_paths(self):
        values = DataTree((Branch((2,), (1, 2)), Branch((4,), (3,))))
        graft = run("addition", values, 10, tree_modes={"A": "graft"})
        self.assertEqual(tuple(b.path for b in graft.branches), ((2, 0), (2, 1), (4, 0)))
        flat = run("addition", values, 10, tree_modes={"A": "flatten"})
        self.assertEqual(flat.branches[0].path, (0,))
        self.assertEqual(flat.values(), (11, 12, 13))
        self.assertEqual(run("multiplication", [], 4).count, 0)
        self.assertEqual(run("addition", DataTree(()), 4).count, 0)
        other = DataTree((Branch((2,), (2,)), Branch((5,), (3,))))
        with self.assertRaisesRegex(ValueError, "paths differ"):
            run("addition", values, other)

    def test_errors_are_atomic_finite_and_reject_native_objects_and_mixed_types(self):
        invalid = (True, float("nan"), float("inf"), {"id": "native-object"},
                   [[1, 2, 3]], [1, VectorValue((1, 2, 3))],
                   DataTree((Branch((0,), ("2",)),)))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                run("multiplication", value, 2)
        with self.assertRaisesRegex(ValueError, "finite"):
            run("multiplication", VectorValue((1e308, 0, 0)), 2)
        for xyz in ((1, 2), (1, 2, True), (1, 2, float("inf"))):
            with self.subTest(xyz=xyz), self.assertRaises(ValueError):
                VectorValue(xyz)
        engine = GraphEngine()
        def graph(factor):
            return [NodeSpec("n", "number", {"value": factor}),
                    NodeSpec("p", "point", {"mode": "generate", "x": 1, "y": 2, "z": 3,
                        "project_uuid": "11111111-1111-4111-8111-111111111111",
                        "node_uuid": "22222222-2222-4222-8222-222222222222"}),
                    NodeSpec("m", "multiplication", inputs={"A": Connection("p", "P"), "B": Connection("n", "Number")}),
                    NodeSpec("w", "watch", inputs={"Value": Connection("m", "R")})]
        self.assertIsNone(engine.evaluate(graph(2)).results["w"].error)
        bad = engine.evaluate(graph(float("nan")))
        self.assertEqual(bad.results["m"].outputs, {})
        self.assertTrue(bad.results["w"].blocked)
        self.assertIsNone(engine.evaluate(graph(3)).results["w"].error)
        self.assertEqual(engine.evaluate(graph(3)).computed, ())


class ArithmeticWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()

    def tearDown(self):
        self.window.graph.undo_stack().setClean()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_point_math_chain_properties_and_undo_preserve_source_geometry(self):
        point = self.window.graph.create_node("NoodleS.Geometry.PointNode")
        point.set_property("x", 1)
        point.set_property("y", 2)
        point.set_property("z", 3)
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 2)
        multiply = self.window.add_node("NoodleS.Math.MultiplicationNode")
        point.outputs()["P"].connect_to(multiply.inputs()["A"])
        number.outputs()["Number"].connect_to(multiply.inputs()["B"])
        self.app.processEvents()
        result = self.window.evaluation.results[multiply.id]
        self.assertEqual(result.outputs["R"].values()[0].xyz, (2, 4, 6))
        self.assertIsNone(result.parametric_object)
        self.assertEqual(self.window.evaluation.results[point.id].parametric_object.points.values()[0].xyz, (1, 2, 3))
        panel = self.window.properties.arithmetic_properties
        self.assertEqual(panel.previews["B"].text(), "2")
        self.assertEqual(list(multiply.outputs()), ["R"])
        for mode, expected in (("graft", {"A": "graft"}), ("flatten", {"A": "flatten"}), ("flatten", {})):
            QTest.mouseClick(panel.modifiers["A"].buttons[mode], QtCore.Qt.LeftButton)
            self.app.processEvents()
            self.assertEqual(multiply.get_property("tree_modes"), expected)
        self.window.graph.undo_stack().undo()
        self.app.processEvents()
        self.assertTrue(panel.modifiers["A"].buttons["flatten"].isChecked())
        multiply.inputs()["B"].clear_connections()
        self.app.processEvents()
        self.assertEqual(panel.previews["B"].text(), "Connect input B.")
        self.assertTrue(self.window.evaluation.results[multiply.id].error)

    def test_old_number_output_migration_and_modifier_round_trip(self):
        fixture = Path(__file__).with_name("fixtures") / "legacy-arithmetic.json"
        clean = read_document(fixture, self.window.node_ports)
        self.window.load_session(clean)
        self.window.evaluate_now()
        watch = next(n for n in self.window.graph.all_nodes() if n.OPERATION == "watch")
        self.assertEqual(self.window.evaluation.results[watch.id].outputs["Value"], 350)
        addition = next(n for n in self.window.graph.all_nodes() if n.OPERATION == "addition")
        addition.set_property("tree_modes", {"A": "graft", "B": "flatten"})
        session = self.window.graph.serialize_session()
        data = {"format": "NoodleS", "schema_version": 1, "session": session}
        clean = validate_document(data, self.window.node_ports)
        self.window.load_session(clean)
        restored = next(n for n in self.window.graph.all_nodes() if n.OPERATION == "addition")
        self.assertEqual(restored.get_property("tree_modes"), {"A": "graft", "B": "flatten"})
        self.assertEqual(list(restored.outputs()), ["R"])
        bad = copy.deepcopy(data)
        bad["session"]["nodes"][addition.id]["custom"]["tree_modes"] = {"X": "graft"}
        with self.assertRaises(DocumentError):
            validate_document(bad, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
