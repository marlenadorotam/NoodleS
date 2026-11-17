"""Safe formulas, DataTree matching and the real Properties editor."""
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_curves as fixture

from noodles.backend.datatree import Branch, DataTree
from noodles.backend.math_nodes import evaluate_math


class ExpressionTests(unittest.TestCase):
    def test_numeric_data_tree_matching_and_invalid_formula(self):
        x = DataTree((Branch((2,), (2, 3)), Branch((7,), (4,))))
        y = DataTree((Branch((2,), (1,)), Branch((7,), (2,))))
        result = evaluate_math('expression', {'formula': 'x^2 - y^2'}, {'X': x, 'Y': y})['R']
        self.assertEqual([(b.path, b.items) for b in result.branches], [((2,), (3, 8)), ((7,), (12,))])
        self.assertEqual(evaluate_math('expression', {'formula': 'sqrt(9) + sin(pi/2)'}, {})['R'], 4)
        for formula in ('1/0', '(-2)^0.5', '__import__("os")', 'x.__class__', 'sin(x, y)', '[x for x in y]'):
            with self.subTest(formula=formula), self.assertRaises(ValueError):
                evaluate_math('expression', {'formula': formula}, {})


class ExpressionWindowTests(unittest.TestCase):
    setUpClass = classmethod(fixture.CurveWindowTests.setUpClass.__func__)
    setUp = fixture.CurveWindowTests.setUp
    tearDown = fixture.CurveWindowTests.tearDown
    settle = fixture.CurveWindowTests.settle

    def test_formula_edit_pretty_powers_undo_and_save(self):
        from pathlib import Path
        import tempfile
        from noodles.document import read_document
        node = self.window.add_node('NoodleS.Math.ExpressionNode')
        self.settle()
        panel = self.window.properties.math_properties
        panel.formula.setFocus()
        panel.formula.selectAll()
        QTest.keyClicks(panel.formula, 'x^2 - y^2 + 5')
        QTest.keyClick(panel.formula, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(panel.formula_preview.text(), 'x² - y² + 5')
        self.assertEqual(self.window.evaluation.results[node.id].outputs['R'], 5)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'expression.noodles'
            self.assertTrue(self.window._save_to(path))
            saved = read_document(path, self.window.node_ports)
            self.assertEqual(next(iter(saved['nodes'].values()))['custom']['formula'], 'x^2 - y^2 + 5')
        panel.formula.clearFocus()
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(panel.formula.text(), 'x')
