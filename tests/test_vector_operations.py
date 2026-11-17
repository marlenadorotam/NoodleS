"""Ryven vector-family behavior, topology, actual Qt controls and persistence."""
import math
import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch, DataTree, aligned
from noodles.backend.math_nodes import MATH_SPECS, evaluate_math, normalize_math_state
from noodles.backend.point import PointValue
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.document import DocumentError, read_document, validate_document, write_document
from noodles.window import MainWindow


OPERATIONS = ("vector_2pt", "unit_vector", "unit_x", "unit_y", "unit_z", "amplitude", "reverse_vector")


def point(x=0, y=0, z=0):
    return PointValue(f"point:{x}:{y}:{z}", (x, y, z))


def inputs_for(operation):
    if operation == "vector_2pt":
        return {"A": point(), "B": point(3, 4)}
    if operation.startswith("unit_") and operation != "unit_vector":
        return {}
    return {"V": VectorValue((3, 4, 0))}


class VectorOperationDataTests(unittest.TestCase):
    def test_two_points_unitize_keeps_original_distance_and_coincident_points(self):
        values = {"A": point(1, 2, 3), "B": point(4, 6, 3)}
        self.assertEqual(evaluate_math("vector_2pt", {}, values), {"V": VectorValue((3, 4, 0)), "L": 5})
        self.assertEqual(evaluate_math("vector_2pt", {"unitize": True}, values),
                         {"V": VectorValue((0.6, 0.8, 0)), "L": 5})
        self.assertEqual(evaluate_math("vector_2pt", {"unitize": True}, {"A": point(), "B": point()}),
                         {"V": VectorValue((0, 0, 0)), "L": 0})
        result = evaluate_math("vector_2pt", {}, {"A": [point()], "B": [point(0, 0, 2), point(0, 0, -4)]})
        self.assertEqual(result["L"].values(), (2, 4))
        self.assertEqual(tuple(v.xyz for v in result["V"].values()), ((0, 0, 2), (0, 0, -4)))

    def test_unitize_boolean_flags_validation_and_tree_matching(self):
        for flag in (True, 1, 1.0, "YES", "on", "true", "1"):
            result = evaluate_math("vector_2pt", {}, {**inputs_for("vector_2pt"), "U": flag})
            self.assertEqual(result["V"], VectorValue((0.6, 0.8, 0)))
        for flag in (False, 0, "OFF", "no", "0", "false"):
            self.assertEqual(evaluate_math("vector_2pt", {}, {**inputs_for("vector_2pt"), "U": flag})["L"], 5)
        for flag in (None, 2, -1, float("nan"), "maybe", VectorValue((1, 0, 0))):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                evaluate_math("vector_2pt", {}, {**inputs_for("vector_2pt"), "U": flag})
        result = evaluate_math("vector_2pt", {}, {**inputs_for("vector_2pt"), "U": [False, True]})
        self.assertEqual(result["V"].values(), (VectorValue((3, 4, 0)), VectorValue((0.6, 0.8, 0))))
        with self.assertRaises(ValueError):
            normalize_math_state("vector_2pt", {"unitize": "maybe"})

    def test_two_point_slots_keys_graft_flatten_and_ambiguous_flat_list(self):
        starts = DataTree((Branch((4,), (point(), point(1)), ("a", "b")),
                           Branch((9,), (point(2), point(3)), ("c", "d"))))
        ends = [point(10), point(20), point(30), point(40)]
        result = evaluate_math("vector_2pt", {}, {"A": starts, "B": ends})
        self.assertEqual(result["L"].values(), (10, 19, 28, 37))
        self.assertEqual(tuple(b.path for b in result["V"].branches), ((4,), (9,)))
        self.assertEqual(tuple(b.keys for b in result["V"].branches), tuple(b.keys for b in result["L"].branches))
        self.assertEqual(evaluate_math("vector_2pt", {}, {"A": starts, "B": ends})["V"], result["V"])
        with self.assertRaisesRegex(ValueError, "ambiguous flat"):
            evaluate_math("vector_2pt", {}, {"A": starts, "B": ends[:3]})
        flat = evaluate_math("vector_2pt", {"tree_modes": {"A": "flatten"}}, {"A": starts, "B": point(10)})
        self.assertEqual(tuple(b.path for b in flat["V"].branches), ((0,),))
        grid = evaluate_math("vector_2pt", {"tree_modes": {"B": "graft"}},
                             {"A": [point(), point(1)], "B": [point(10), point(20)]})
        # Ryven assigns a complete flat list by slot, without a Cartesian product.
        self.assertEqual(grid["L"].values(), (10, 19))
        self.assertEqual(tuple(b.path for b in grid["V"].branches), ((0, 0), (0, 1)))

    def test_unit_vector_threshold_and_extreme_finite_coordinates(self):
        self.assertEqual(evaluate_math("unit_vector", {}, inputs_for("unit_vector"))["U"], VectorValue((0.6, 0.8, 0)))
        for vector in ((0, 0, 0), (1e-15, 0, 0), (1e-16, 1e-16, 0)):
            with self.subTest(vector=vector), self.assertRaisesRegex(ValueError, "zero/invalid"):
                evaluate_math("unit_vector", {}, {"V": VectorValue(vector)})
        large = evaluate_math("unit_vector", {}, {"V": VectorValue((1e308, 1e308, 0))})["U"]
        self.assertAlmostEqual(math.hypot(*large.xyz), 1)
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_math("unit_vector", {}, {"V": VectorValue((1.7e308, 1.7e308, 0))})

    def test_axes_default_negative_zero_factors_and_preserved_tree_paths(self):
        factors = DataTree((Branch((3,), (-2, 0), ("a", "b")), Branch((8,), (4,), ("c",))))
        for axis, operation in enumerate(("unit_x", "unit_y", "unit_z")):
            with self.subTest(operation=operation):
                expected = lambda f: VectorValue(tuple(f if i == axis else 0 for i in range(3)))
                self.assertEqual(evaluate_math(operation, {}, {})["V"], expected(1))
                result = evaluate_math(operation, {}, {"F": factors})["V"]
                self.assertEqual(result.values(), tuple(expected(f) for f in (-2, 0, 4)))
                self.assertEqual(tuple(b.path for b in result.branches), ((3,), (8,)))
                self.assertEqual(tuple(b.keys for b in result.branches), tuple(b.keys for b in factors.branches))

    def test_amplitude_signed_length_zero_vectors_and_repeat_last(self):
        vector = VectorValue((3, 4, 0))
        self.assertEqual(evaluate_math("amplitude", {}, {"V": vector})["V"], VectorValue((0.6, 0.8, 0)))
        self.assertEqual(evaluate_math("amplitude", {}, {"V": vector, "A": -10})["V"], VectorValue((-6, -8, 0)))
        self.assertEqual(evaluate_math("amplitude", {}, {"V": vector, "A": 0})["V"], VectorValue((0, 0, 0)))
        self.assertEqual(evaluate_math("amplitude", {}, {"V": VectorValue((0, 0, 0)), "A": 9})["V"], VectorValue((0, 0, 0)))
        result = evaluate_math("amplitude", {}, {"V": [vector], "A": [5, -10, 0]})["V"]
        self.assertEqual(result.values(), (vector, VectorValue((-6, -8, 0)), VectorValue((0, 0, 0))))
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_math("amplitude", {}, {"V": VectorValue((1.7e308, 1.7e308, 0)), "A": 0})

    def test_reverse_keeps_length_keys_and_positive_zero(self):
        source = DataTree((Branch((5,), (VectorValue((3, -4, -0.0)),), ("vector-key",)),))
        result = evaluate_math("reverse_vector", {}, {"V": source})["V"]
        self.assertEqual(result.branches[0].path, (5,))
        self.assertEqual(result.branches[0].keys, ("vector-key",))
        self.assertEqual(result.values(), (VectorValue((-3, 4, 0)),))
        self.assertEqual(math.copysign(1, result.values()[0].xyz[2]), 1)
        self.assertEqual(evaluate_math("reverse_vector", {}, {"V": result})["V"].values(), source.values())

    def test_singleton_graft_survives_on_every_new_input(self):
        for operation in OPERATIONS:
            for descriptor in MATH_SPECS[operation]["inputs"]:
                with self.subTest(operation=operation, port=descriptor.port):
                    result = evaluate_math(operation, {"tree_modes": {descriptor.port: "graft"}}, inputs_for(operation))
                    for tree in result.values():
                        self.assertIsInstance(tree, DataTree)
                        self.assertEqual(tuple(b.path for b in tree.branches), ((0, 0),))
        # Existing Vector also lost Y/Z singleton Graft to the first X input.
        self.assertEqual(evaluate_math("vector", {"tree_modes": {"Y": "graft"}}, {})["Vector"].branches[0].path, (0, 0))
        empty = list(aligned(DataTree(()), DataTree((Branch((0, 0), (1,)),))))
        self.assertEqual(empty, [])

    def test_invalid_typed_inputs_and_unavailable_defaults_are_errors(self):
        for operation in OPERATIONS:
            port = MATH_SPECS[operation]["inputs"][0].port
            invalid = (None, True, float("nan"), {"id": "scene"}, [1, 2, 3])
            if port == "F":
                invalid = (None, True, float("nan"), VectorValue((1, 0, 0)), point())
            for value in invalid:
                with self.subTest(operation=operation, value=value), self.assertRaises(ValueError):
                    evaluate_math(operation, {}, {**inputs_for(operation), port: value})
        for operation in ("unit_vector", "amplitude", "reverse_vector"):
            with self.assertRaises(ValueError):
                evaluate_math(operation, {}, {"V": point(1, 2, 3)})
        with self.assertRaises(ValueError):
            evaluate_math("vector_2pt", {}, {"A": VectorValue((0, 0, 0)), "B": point()})

    def test_empty_inputs_paths_and_limit_do_not_make_extra_vectors(self):
        for operation in OPERATIONS:
            port = MATH_SPECS[operation]["inputs"][0].port
            result = evaluate_math(operation, {}, {**inputs_for(operation), port: []})
            self.assertTrue(all(isinstance(t, DataTree) and t.count == 0 for t in result.values()))
        with self.assertRaisesRegex(ValueError, "paths differ"):
            evaluate_math("amplitude", {}, {"V": DataTree((Branch((1,), (VectorValue((1, 0, 0)),)),
                Branch((2,), (VectorValue((1, 0, 0)),)))), "A": DataTree((Branch((3,), (1,)), Branch((4,), (2,))))})
        with self.assertRaisesRegex(ValueError, "10,000"):
            evaluate_math("amplitude", {"tree_modes": {"A": "graft"}},
                          {"V": [VectorValue((1, 0, 0))] * 101, "A": list(range(100))})

    def test_engine_chain_failure_recovery_cache_and_no_scene_objects(self):
        engine = GraphEngine()
        def graph(factor):
            return [NodeSpec("axis", "unit_z", {"factor": factor}),
                NodeSpec("unit", "unit_vector", inputs={"V": Connection("axis", "V")}),
                NodeSpec("amp", "amplitude", {"amplitude": -7}, inputs={"V": Connection("unit", "U")}),
                NodeSpec("rev", "reverse_vector", inputs={"V": Connection("amp", "V")}),
                NodeSpec("dot", "multiplication", inputs={"A": Connection("rev", "V"), "B": Connection("axis", "V")})]
        good = engine.evaluate(graph(2))
        self.assertEqual(good.results["rev"].outputs["V"], VectorValue((0, 0, 7)))
        self.assertEqual(good.results["dot"].outputs["R"], 14)
        self.assertTrue(all(r.parametric_object is None for r in good.results.values()))
        self.assertEqual(engine.evaluate(graph(2)).computed, ())
        bad = engine.evaluate(graph(0))
        self.assertIn("zero/invalid", bad.results["unit"].error)
        for key in ("amp", "rev", "dot"):
            self.assertTrue(bad.results[key].blocked)
            self.assertEqual(bad.results[key].outputs, {})
        self.assertEqual(engine.evaluate(graph(-2)).results["dot"].outputs["R"], 14)


class VectorOperationWindowTests(unittest.TestCase):
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

    def add(self, operation):
        node = self.window.add_node("NoodleS.Math." + MATH_SPECS[operation]["class"])
        self.settle()
        return node

    def test_each_input_graft_toggle_flatten_and_undo_with_real_clicks(self):
        for operation in OPERATIONS:
            node = self.add(operation)
            for port in node.inputs():
                panel = self.window.properties.math_properties
                with self.subTest(operation=operation, port=port):
                    def click(mode):
                        QTest.mouseClick(panel.modifiers[port].buttons[mode], QtCore.Qt.LeftButton)
                        self.settle()
                    click("graft")
                    self.assertEqual(node.get_property("tree_modes"), {port: "graft"})
                    click("graft")
                    self.assertEqual(node.get_property("tree_modes"), {})
                    click("flatten")
                    self.assertEqual(node.get_property("tree_modes"), {port: "flatten"})
                    click("graft")
                    self.assertFalse(panel.modifiers[port].buttons["flatten"].isChecked())
                    self.window.graph.undo_stack().undo()
                    self.settle()
                    self.assertEqual(node.get_property("tree_modes"), {port: "flatten"})
                    click("flatten")
                    self.assertEqual(node.get_property("tree_modes"), {})

    def test_real_points_unitize_click_undo_connected_preview_and_disconnect(self):
        a = self.window.graph.create_node("NoodleS.Geometry.PointNode")
        b = self.window.graph.create_node("NoodleS.Geometry.PointNode")
        b.set_property("x", 3)
        b.set_property("y", 4)
        node = self.add("vector_2pt")
        a.outputs()["P"].connect_to(node.inputs()["A"])
        b.outputs()["P"].connect_to(node.inputs()["B"])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        panel = self.window.properties.math_properties
        editor = panel.editors["unitize"]
        self.assertIsInstance(editor, QtWidgets.QCheckBox)
        QTest.mouseClick(editor, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, editor.height() // 2))
        self.settle()
        result = self.window.evaluation.results[node.id].outputs
        self.assertEqual(result["V"].values(), (VectorValue((0.6, 0.8, 0)),))
        self.assertEqual(result["L"].values(), (5,))
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertFalse(editor.isChecked())
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 1)
        number.outputs()["Number"].connect_to(node.inputs()["U"])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        self.assertIs(panel.stacks["U"].currentWidget(), panel.previews["U"])
        self.assertEqual(panel.previews["U"].text(), "True")
        number.set_property("value", 2)
        self.settle()
        self.assertTrue(self.window.evaluation.results[node.id].error)
        self.assertEqual(self.window.evaluation.results[node.id].outputs, {})
        node.inputs()["U"].clear_connections()
        self.settle()
        self.assertIsNone(self.window.evaluation.results[node.id].error)
        self.assertFalse(editor.isChecked())

    def test_factor_typing_signed_amplitude_and_connected_defaults_restore(self):
        node = self.add("unit_x")
        editor = self.window.properties.math_properties.editors["factor"]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, "-2.5")
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[node.id].outputs["V"], VectorValue((-2.5, 0, 0)))
        amplitude = self.add("amplitude")
        node.outputs()["V"].connect_to(amplitude.inputs()["V"])
        amplitude.set_property("amplitude", -5)
        self.window.graph.clear_selection()
        amplitude.set_selected(True)
        self.settle()
        self.assertEqual(self.window.evaluation.results[amplitude.id].outputs["V"], VectorValue((5, 0, 0)))
        self.assertEqual(self.window.properties.math_properties.previews["V"].text(), "Vector(-2.5, 0, 0)")
        number = self.window.graph.create_node("NoodleS.Inputs.NumberNode")
        number.set_property("value", 9)
        number.outputs()["Number"].connect_to(amplitude.inputs()["A"])
        self.settle()
        self.assertEqual(self.window.evaluation.results[amplitude.id].outputs["V"], VectorValue((-9, 0, 0)))
        amplitude.inputs()["A"].clear_connections()
        self.settle()
        self.assertEqual(self.window.evaluation.results[amplitude.id].outputs["V"], VectorValue((5, 0, 0)))

    def test_save_reload_all_vector_types_defaults_modifiers_and_unitize_validation(self):
        for operation in OPERATIONS:
            node = self.add(operation)
            node.set_property("tree_modes", {port: "graft" for port in node.inputs()})
            if operation == "vector_2pt":
                node.set_property("unitize", True)
            if operation in ("unit_x", "unit_y", "unit_z"):
                node.set_property("factor", -3)
            for port in node.output_ports():
                watch = self.window.graph.create_node("NoodleS.Data.WatchNode")
                port.connect_to(watch.inputs()["Value"])
        session = self.window.graph.serialize_session()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / "vector-family.noodles"
            write_document(path, session)
            clean = read_document(path, self.window.node_ports)
        self.window.load_session(clean)
        self.window.evaluate_now()
        for operation in OPERATIONS:
            node = next(n for n in self.window.graph.all_nodes() if n.OPERATION == operation)
            self.assertEqual(node.get_property("tree_modes"), {port: "graft" for port in node.inputs()})
            self.assertTrue(all(len(p.connected_ports()) == 1 for p in node.output_ports()))
            if operation == "vector_2pt":
                self.assertIs(node.get_property("unitize"), True)
        record = next(r for r in session["nodes"].values() if r["type_"].endswith(".Vector2PtNode"))
        record["custom"]["unitize"] = "not a flag"
        with self.assertRaises(DocumentError):
            validate_document({"format": "NoodleS", "schema_version": 1, "session": session}, self.window.node_ports)


if __name__ == "__main__":
    unittest.main()
