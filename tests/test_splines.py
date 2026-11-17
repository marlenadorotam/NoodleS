"""Unified singular/branch spline contracts and actual Qt Properties events."""
import unittest

from Qt import QtCore
from PySide6.QtTest import QTest
from noodles.backend.curves import CURVE_SPECS, evaluate_curve, normalize_curve_state, curve_object_from_outputs
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.splines import PendingGeometry, spline
from noodles.core import GraphEngine, NodeSpec, Connection
import test_curves as curve_fixture
from test_curves import state, inputs_for


class SplineDataTests(unittest.TestCase):
    def test_one_list_and_many_branches_same_node_stable_keys(self):
        sites = tuple(inputs_for('curve')['P'])
        for operation in ('curve', 'interpcurve'):
            parameters = state(operation)
            tree = DataTree((Branch((3, 7), sites), Branch((8, 2), sites), Branch((9,), ())))
            output = evaluate_curve(operation, parameters, {'P': tree})
            self.assertEqual(output['Count'], 2)
            self.assertEqual(tuple(b.path for b in output['C'].branches), ((3, 7), (8, 2), (9,)))
            self.assertEqual(output['V'].count, 8)
            self.assertTrue(all(isinstance(v, PendingGeometry) for v in output['L'].values()))
            keys = tuple(v.key for v in output['C'].values())
            shifted = DataTree(tuple(Branch(b.path, tuple(type(v)(v.key, tuple(c+2 for c in v.xyz)) for v in b.items), b.keys) for b in tree.branches))
            updated = evaluate_curve(operation, parameters, {'P': shifted})
            self.assertEqual(tuple(v.key for v in updated['C'].values()), keys)
            self.assertEqual(curve_object_from_outputs(parameters, output).kind, 'curves')

    def test_branch_parameters_do_not_duplicate_points_and_ambiguous_values_fail(self):
        sites = tuple(inputs_for('curve')['P'])
        tree = DataTree((Branch((4,), sites), Branch((6,), sites)))
        for operation in ('curve', 'interpcurve'):
            output = evaluate_curve(operation, state(operation), {'P': tree, 'D': [2, 3]})
            self.assertEqual(output['D'].values(), (2, 3))
            self.assertEqual(tuple(len(v.points) for v in output['C'].values()), (4, 4))
            with self.assertRaisesRegex(ValueError, 'constant'):
                evaluate_curve(operation, state(operation), {'P': sites, 'D': [2, 3]})
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                evaluate_curve(operation, state(operation), {'P': tree, 'D': [2, 2, 3]})

    def test_flatten_graft_and_empty_branches(self):
        sites = tuple(inputs_for('curve')['P'])
        tree = DataTree((Branch((4,), sites), Branch((6,), sites)))
        for operation in ('curve', 'interpcurve'):
            flat = evaluate_curve(operation, state(operation, tree_modes={'P': 'flatten'}), {'P': tree})
            self.assertEqual(flat['Count'], 1)
            self.assertEqual(len(flat['C'].values()[0].points), 8)
            with self.assertRaisesRegex(ValueError, 'at least three'):
                evaluate_curve(operation, state(operation, tree_modes={'P': 'graft'}), {'P': tree})
            empty = evaluate_curve(operation, state(operation), {'P': []})
            self.assertEqual(empty['Count'], 0)

    def test_degree_closure_duplicates_and_saved_parameter_validation(self):
        from noodles.backend.spline_native import _validate_xyz
        near_closed = ((0, 0, 0), (1, 1, 0), (2, 0, 0), (8e-9, 0, 0))
        native_sites, native_closed = _validate_xyz(near_closed)
        self.assertEqual(len(native_sites), 4)
        self.assertFalse(native_closed)
        sites = tuple(v.xyz for v in inputs_for('curve')['P'])
        for degree in (0, 1, 2.5, 11, True):
            with self.assertRaises(ValueError):
                spline('k', 'curve', sites, degree)
        closed = spline('k', 'curve', sites[:3], 3, True)
        self.assertTrue(closed.periodic)
        with self.assertRaises(ValueError):
            spline('k', 'curve', sites[:3], 3)
        for operation in ('curve', 'interpcurve'):
            with self.assertRaises(ValueError):
                normalize_curve_state(operation, {'parameters': {'D': 2.5}})
            with self.assertRaises(ValueError):
                spline('k', operation, (sites[0], sites[0], *sites[1:]), 2)
        repeated = spline('k', 'interpcurve', sites+(sites[0],), 3)
        self.assertTrue(repeated.closed)
        self.assertEqual(repeated.points, sites)
        self.assertTrue(spline('k', 'interpcurve', sites, periodic=True).closed)
        with self.assertRaises(ValueError):
            spline('k', 'interpcurve', sites, knot_style=3)

    def test_deferred_length_blocks_only_consumers_until_matching_native_result(self):
        from noodles.backend.splines import signature
        parameters = state('curve')
        sites = tuple(inputs_for('curve')['P'])
        point_refs = [{'key': p.key, 'id': str(i), 'name': '', 'xyz': list(p.xyz)} for i, p in enumerate(sites)]
        # Feed an actual upstream Point Reference tree, keeping the whole graph Qt/OCC-free.
        from noodles.backend.point import normalize_point_state
        point_state = normalize_point_state({'mode': 'reference', 'references': point_refs,
            'project_uuid': parameters['project_uuid'], 'node_uuid': parameters['node_uuid']})
        engine = GraphEngine()
        nodes = [NodeSpec('p', 'point', point_state),
                 NodeSpec('c', 'curve', parameters, {'P': Connection('p', 'P')}),
                 NodeSpec('l', 'watch', {}, {'Value': Connection('c', 'L')})]
        result = engine.evaluate(nodes)
        self.assertIsNone(result.results['c'].error)
        self.assertTrue(result.results['l'].blocked)
        value = result.results['c'].outputs['C'].values()[0]
        # A valid native snapshot for a cubic Bezier in this case.
        recipe = {**value.to_wire(), 'knots': [0, 1], 'multiplicities': [4, 4], 'weights': [1]*4,
                  'domain': [0, 1], 'length': 27.5}
        parameters = {**parameters, 'curve_details': {value.key: {'signature': signature(value), 'recipe': recipe}}}
        nodes[1] = NodeSpec('c', 'curve', parameters, nodes[1].inputs)
        output = engine.evaluate(nodes)
        self.assertIsNone(output.results['l'].error)
        self.assertEqual(output.results['l'].outputs['Value'].values(), (27.5,))
        self.assertEqual(output.results['c'].parametric_object.to_wire(), result.results['c'].parametric_object.to_wire())
        parameters['curve_details'] = {value.key: {'signature': 'stale', 'recipe': recipe}}
        self.assertTrue(engine.evaluate(nodes).results['l'].blocked)


class SplinePropertiesTests(unittest.TestCase):
    # Reuse the fixture, not the parent's test methods (covered in test_curves).
    setUpClass = classmethod(curve_fixture.CurveWindowTests.setUpClass.__func__)
    setUp = curve_fixture.CurveWindowTests.setUp
    tearDown = curve_fixture.CurveWindowTests.tearDown
    add = curve_fixture.CurveWindowTests.add
    settle = curve_fixture.CurveWindowTests.settle
    def test_spline_degree_checkbox_knot_combo_undo_and_compact_layout(self):
        node = self.add('interpcurve')
        panel = self.window.properties.curve_properties
        degree = panel.editors['D'][0]
        degree.setFocus()
        QTest.keyClick(degree, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(degree, '2')
        QTest.keyClick(degree, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property('parameters')['D'], 2)
        periodic = panel.editors['T'][0]
        QTest.mouseClick(periodic, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, periodic.height()//2))
        self.settle()
        self.assertTrue(node.get_property('parameters')['T'])
        combo = panel.editors['K'][0]
        combo.setFocus()
        QTest.keyClick(combo, QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(node.get_property('parameters')['K'], 2)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(combo.currentIndex(), 1)
        self.assertLess(node.view.width, 200)
