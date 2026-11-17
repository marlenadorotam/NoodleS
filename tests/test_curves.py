"""Deferred primitives, DataTree, shared ParametricObject and actual Properties."""
import copy
import math
import os
from pathlib import Path
import tempfile
import unittest

os.environ['QT_PREFERRED_BINDING'] = 'PySide6'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest

from noodles.backend.curves import (CURVE_SPECS, PlaneValue, CurveValue, evaluate_curve, normalize_curve_state,
    curve_object_from_outputs, curve_object_from_wire, curve_from_wire, circle, arc, rectangle, ellipse_perimeter)
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.point import PointValue, ParametricObject, object_from_wire
from noodles.backend.parametric import ParametricObject as UniversalParametricObject
from noodles.backend.arithmetic import VectorValue
from noodles.core import GraphEngine, NodeSpec, Connection
from noodles.document import read_document, write_document
from noodles.window import MainWindow

PROJECT = 'af96bbf5-d242-4876-bebb-15d8de7a8991'
NODE = 'e5c1ed25-f186-4668-842d-b554cc39c95f'


def state(operation, **changes):
    return normalize_curve_state(operation, {'project_uuid': PROJECT, 'node_uuid': NODE, **changes})


def points(values):
    return [PointValue('point'+str(i), xyz) for i, xyz in enumerate(values)]


def inputs_for(operation):
    return {'P': points(((0, 0, 0), (10, 0, 0), (10, 10, 0), (20, 10, 5)))} if operation in ('polyline', 'curve', 'interpcurve') else {}


class CurveDataTests(unittest.TestCase):
    def test_curves_preserves_mixed_tree_and_passthrough_bindings(self):
        from noodles.backend.curve_collection import evaluate, normalize_state
        from noodles.backend.curves import line

        a = circle('round', (0, 0, 0), 4, PlaneValue())
        b = line('edge', (0, 0, 0), (1, 2, 3))
        tree = DataTree((Branch((3,), (a,), ('a',)), Branch((6,), (b,), ('b',))))
        params = normalize_state({'project_uuid': PROJECT, 'node_uuid': NODE})
        self.assertEqual(evaluate(params, {'C': tree})['C'], tree)
        graft = evaluate({**params, 'tree_modes': {'C': 'graft'}}, {'C': tree})['C']
        self.assertEqual([(branch.path, branch.keys) for branch in graft.branches],
                         [((3, 0), ('a',)), ((6, 0), ('b',))])
        flat = evaluate({**params, 'tree_modes': {'C': 'flatten'}}, {'C': tree})['C']
        self.assertEqual(flat.branches, (Branch((0,), (a, b), ('a', 'b')),))

        result = GraphEngine().evaluate([
            NodeSpec('circle', 'circle', state('circle')),
            NodeSpec('collector', 'curves', params, {'C': Connection('circle', 'C')}),
        ]).results
        self.assertEqual(result['collector'].bindings['C'], result['circle'].bindings['C'])
        self.assertIsNone(result['collector'].parametric_object)

    def test_ellipse_radii_stay_on_named_axes_and_wire_roundtrip(self):
        for a, b in ((10, 5), (5, 10), (7, 7), (1e9, 1.00001e-9)):
            parameters = state('ellipse', parameters={'A': a, 'B': b, 'P': 'YZ'})
            result = evaluate_curve('ellipse', parameters, {})
            value = result['C'].values()[0]
            self.assertEqual(result['A'].values(), (a,))
            self.assertEqual(result['B'].values(), (b,))
            self.assertEqual(value.frame.axis_x, (0, 1, 0))
            self.assertEqual(value.dimensions, (a, b))
            self.assertEqual(curve_from_wire(value.to_wire()).to_wire(), value.to_wire())
            self.assertTrue(math.isfinite(value.length))
        self.assertAlmostEqual(ellipse_perimeter(10, 5), 48.44224110273838, delta=1e-12)
        self.assertEqual(ellipse_perimeter(10, 10), 20*math.pi)
        self.assertEqual(ellipse_perimeter(10, 5), ellipse_perimeter(5, 10))
        self.assertAlmostEqual(ellipse_perimeter(1e9, 1.00001e-9), 4e9, delta=.0001)

    def test_ellipse_perimeter_against_independent_speed_integration(self):
        # Composite Simpson quadrature is independent of the AGM implementation.
        count = 2000
        step = (math.pi/2)/count
        for a, b in ((10, 5), (5, 10), (3, 2.99999), (100, 1)):
            speed = lambda t: math.hypot(a*math.sin(t), b*math.cos(t))
            integral = step/3*(speed(0)+speed(math.pi/2)+math.fsum(
                (4 if i%2 else 2)*speed(i*step) for i in range(1, count)))
            self.assertAlmostEqual(ellipse_perimeter(a, b), 4*integral, delta=max(a, b)*1e-10)

    def test_ellipse_invalid_radii_and_multi_branch_slot_matching(self):
        for port in ('A', 'B'):
            for value in (0, -1, 1e-10, True, float('nan'), float('inf')):
                with self.subTest(port=port, value=value), self.assertRaises(ValueError):
                    evaluate_curve('ellipse', state('ellipse'), {port: value})
        centers = DataTree((Branch((3,), tuple(points(((0, 0, 0), (10, 0, 0))))),
                            Branch((9,), tuple(points(((0, 10, 0), (10, 10, 0)))))))
        result = evaluate_curve('ellipse', state('ellipse'), {'C': centers, 'A': [1, 2, 3, 4], 'B': 5})
        self.assertEqual(result['Count'], 4)
        self.assertEqual(result['A'].values(), (1, 2, 3, 4))
        self.assertEqual(tuple(b.path for b in result['C'].branches), ((3,), (9,)))

    def test_all_primitives_are_deferred_parts_in_the_same_parametric_class(self):
        self.assertIs(ParametricObject, UniversalParametricObject)
        for operation in CURVE_SPECS:
            with self.subTest(operation=operation):
                parameters = state(operation)
                output = evaluate_curve(operation, parameters, inputs_for(operation))
                model = curve_object_from_outputs(parameters, output)
                self.assertIsInstance(model, ParametricObject)
                self.assertEqual(model.parts.count, 1)
                self.assertEqual(model.kind, 'curves')
                self.assertIsInstance(model.parts.values()[0], CurveValue)
                self.assertEqual(output['Count'], 1)
                decoded = object_from_wire(model.to_wire())
                self.assertEqual(decoded.to_wire(), model.to_wire())

    def test_circle_planes_normals_and_two_hundred_different_radii(self):
        centers = DataTree((Branch((3,), tuple(points((i, 0, 0) for i in range(200)))),))
        radii = list(range(1, 201))
        output = evaluate_curve('circle', state('circle'), {'C': centers, 'R': radii})
        self.assertEqual(output['Count'], 200)
        self.assertEqual(output['R'].values(), tuple(radii))
        self.assertEqual(len({v.key for v in output['C'].values()}), 200)
        self.assertEqual(tuple(b.path for b in output['C'].branches), ((3,),))
        other = evaluate_curve('circle', state('circle'), {'C': centers, 'R': [r+1 for r in radii]})
        self.assertEqual(tuple(v.key for v in output['C'].values()), tuple(v.key for v in other['C'].values()))
        tilted = evaluate_curve('circle', state('circle'), {'P': VectorValue((1, 2, 3))})
        self.assertAlmostEqual(math.hypot(*tilted['N'].values()[0].xyz), 1)
        self.assertAlmostEqual(sum(a*b for a, b in zip(tilted['P'].values()[0].axis_x, tilted['N'].values()[0].xyz)), 0)

    def test_rectangle_numeric_and_reversed_domains_are_centered_in_plane(self):
        output = evaluate_curve('rectangle', state('rectangle'), {'X': DomainValue(10, 2), 'Y': DomainValue(-3, 5)})
        value = output['C'].values()[0]
        self.assertEqual(value.frame.origin, (6, 1, 0))
        self.assertEqual(value.dimensions, (8, 8))
        self.assertEqual(value.points, ((2, -3, 0), (10, -3, 0), (10, 5, 0), (2, 5, 0)))
        self.assertEqual(output['L'].values(), (32,))
        self.assertEqual(output['V'].count, 4)
        shifted = evaluate_curve('rectangle', state('rectangle'), {'P': PlaneValue((10, 20, 30), (0, 1, 0), (1, 0, 0))})
        self.assertEqual(shifted['O'].values()[0].xyz, (10, 20, 30))

    def test_full_flat_list_fills_primitive_grid_slots_without_multiplying_geometry(self):
        centers = DataTree(tuple(Branch((row,), tuple(PointValue(f'p{row}:{i}', (i*10, row*10, 0))
                                               for i in range(20))) for row in range(10)))
        radii = DataTree((Branch((0,), tuple(range(1, 201))),))
        result = evaluate_curve('circle', state('circle'), {'C': centers, 'R': radii})
        self.assertEqual(result['Count'], 200)
        self.assertEqual(result['R'].values(), tuple(range(1, 201)))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            evaluate_curve('circle', state('circle'), {'C': centers, 'R': list(range(1, 200))})

    def test_three_point_arc_circle_math_and_negative_center_sweeps(self):
        value = arc('arc', (-10, 0, 0), (0, 10, 0), (10, 0, 0))
        self.assertEqual(value.frame.origin, (0, 0, 0))
        self.assertEqual(value.radius, 10)
        self.assertAlmostEqual(value.length, 10*math.pi)
        for angle in (-270, -90, 90, 270):
            parameters = state('arc_center', parameters={'R': 5, 'A': angle})
            output = evaluate_curve('arc_center', parameters, {})
            self.assertAlmostEqual(output['S'].values()[0], angle)
            value = output['C'].values()[0]
            self.assertEqual(curve_from_wire(value.to_wire()).to_wire(), value.to_wire())
            self.assertAlmostEqual(value.length, 5*abs(math.radians(angle)))
        with self.assertRaises(ValueError):
            arc('bad', (0, 0, 0), (1, 1, 1), (2, 2, 2))

    def test_polyline_one_curve_per_branch_closure_and_vertex_provenance(self):
        a = tuple(points(((0, 0, 0), (3, 0, 0), (3, 4, 0))))
        b = tuple(points(((10, 0, 0), (13, 0, 0), (13, 4, 0))))
        tree = DataTree((Branch((4,), a), Branch((9,), b)))
        output = evaluate_curve('polyline', state('polyline'), {'P': tree, 'C': True})
        self.assertEqual(output['Count'], 2)
        self.assertEqual(output['L'].values(), (12, 12))
        self.assertEqual(tuple(branch.path for branch in output['C'].branches), ((4,), (9,)))
        self.assertEqual(output['V'].count, 6)
        self.assertEqual(output['Closed'].values(), (True, True))
        with self.assertRaises(ValueError):
            evaluate_curve('polyline', state('polyline'), {'P': a, 'C': [True, False]})

    def test_each_input_graft_flatten_empty_and_invalid_types(self):
        for operation, spec in CURVE_SPECS.items():
            for descriptor in spec['inputs']:
                with self.subTest(operation=operation, port=descriptor.port):
                    if operation not in ('polyline', 'curve', 'interpcurve'):
                        output = evaluate_curve(operation, state(operation, tree_modes={descriptor.port: 'graft'}), {})
                        self.assertEqual(output['C'].branches[0].path, (0, 0))
                    with self.assertRaises(ValueError):
                        evaluate_curve(operation, state(operation), {**inputs_for(operation), descriptor.port: {'scene_id': 'wrong'}})
        output = evaluate_curve('circle', state('circle'), {'R': []})
        self.assertEqual(output['Count'], 0)
        with self.assertRaises(ValueError):
            evaluate_curve('circle', state('circle'), {'R': -1})
        with self.assertRaises(ValueError):
            evaluate_curve('rectangle', state('rectangle'), {'X': DomainValue(1, 1)})
        with self.assertRaises(ValueError):
            evaluate_curve('line', state('line'), {'A': PointValue('a', (0, 0, 0)), 'B': PointValue('b', (0, 0, 0))})

    def test_reference_outputs_native_source_and_drives_connected_inputs(self):
        recipe = circle('source', (3, 4, 5), 7, PlaneValue())
        parameters = state('circle', mode='reference', references=[{'key': 'source', 'id': 'runtime', 'name': 'Circle', 'recipe': recipe.to_wire()}],
                           tree_modes={'References': 'graft'})
        output = evaluate_curve('circle', parameters, {'R': -999, 'C': None})
        self.assertEqual(output['R'].values(), (7,))
        self.assertEqual(output['C'].branches[0].path, (0, 0))
        engine = GraphEngine()
        result = engine.evaluate([NodeSpec('bad', 'number', {'value': 1}, disabled=True),
            NodeSpec('ref', 'circle', parameters, {'R': Connection('bad', 'Number')})])
        self.assertIn('No valid value at input R', result.results['ref'].error)
        result = engine.evaluate([NodeSpec('number', 'number', {'value': 9}),
            NodeSpec('ref', 'circle', parameters, {'R': Connection('number', 'Number')})])
        self.assertEqual(result.results['ref'].outputs['R'].values(), (7,))
        self.assertEqual(result.results['ref'].reference_drive, {'updates': [{'key': 'source', 'values': {'R': 9}}]})

    def test_wire_validation_and_duplicate_keys(self):
        parameters = state('circle')
        model = curve_object_from_outputs(parameters, evaluate_curve('circle', parameters, {})).to_wire()
        bad = copy.deepcopy(model)
        bad['branches'][0]['parts'] *= 2
        with self.assertRaisesRegex(ValueError, 'unique'):
            curve_object_from_wire(bad)
        for changes in ({'mode': 'reference'}, {'schema': True}):
            with self.assertRaises(ValueError):
                curve_object_from_wire({**model, **changes})


class CurveWindowTests(unittest.TestCase):
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
        node = self.window.add_node('NoodleS.Geometry.'+CURVE_SPECS[operation]['class'])
        self.settle()
        return node

    def test_every_mode_and_modifier_real_click_toggle_and_undo(self):
        for operation, spec in CURVE_SPECS.items():
            node = self.add(operation)
            panel = self.window.properties.curve_properties
            for descriptor in spec['inputs']:
                for mode, expected in (('graft', {descriptor.port: 'graft'}), ('flatten', {descriptor.port: 'flatten'}), ('flatten', {})):
                    QTest.mouseClick(panel.modifiers[descriptor.port].buttons[mode], QtCore.Qt.LeftButton)
                    self.settle()
                    self.assertEqual(node.get_property('tree_modes'), expected)
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            self.settle()
            self.assertTrue(panel.reference.isVisible())
            self.assertTrue(panel.generate.isVisible())
            self.window.graph.undo_stack().undo()
            self.settle()
            self.assertTrue(panel.generate.isVisible())

    def test_circle_typing_connected_preview_and_invalid_edit_keeps_published_model(self):
        node = self.add('circle')
        panel = self.window.properties.curve_properties
        editor = panel.editors['R'][0]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, '25')
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[node.id].outputs['R'].values(), (25,))
        old_model = copy.deepcopy(self.window.point_service.models[node.id])
        node.set_property('parameters', {**node.get_property('parameters'), 'R': -1})
        self.settle()
        self.assertTrue(self.window.evaluation.results[node.id].error)
        self.assertEqual(self.window.point_service.models[node.id], old_model)
        number = self.window.graph.create_node('NoodleS.Inputs.NumberNode')
        number.set_property('value', 5)
        number.outputs()['Number'].connect_to(node.inputs()['R'])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        self.assertIs(panel.stacks['R'].currentWidget(), panel.previews['R'])
        self.assertEqual(self.window.evaluation.results[node.id].outputs['R'].values(), (5,))
        self.assertFalse(editor.isVisible())

    def test_ellipse_real_radius_typing_undo_and_connected_preview(self):
        node = self.add('ellipse')
        panel = self.window.properties.curve_properties
        editor = panel.editors['B'][0]
        editor.setFocus()
        QTest.keyClick(editor, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor, '12')
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        self.settle()
        result = self.window.evaluation.results[node.id].outputs
        self.assertEqual(result['A'].values(), (10,))
        self.assertEqual(result['B'].values(), (12,))
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(editor.value(), 5)
        number = self.window.graph.create_node('NoodleS.Inputs.NumberNode')
        number.set_property('value', 20)
        number.outputs()['Number'].connect_to(node.inputs()['A'])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        self.assertIs(panel.stacks['A'].currentWidget(), panel.previews['A'])
        self.assertEqual(self.window.evaluation.results[node.id].outputs['A'].values(), (20,))

    def test_save_reload_curve_only_graph_and_copy_identity(self):
        for operation in CURVE_SPECS:
            node = self.add(operation)
            node.set_property('tree_modes', {'References': 'graft'})
        session = self.window.graph.serialize_session()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder)/'curves.noodles'
            write_document(path, session)
            clean = read_document(path, self.window.node_ports)
        self.window.load_session(clean)
        self.window.evaluate_now()
        nodes = self.window.graph.all_nodes()
        self.assertEqual(len(nodes), len(CURVE_SPECS))
        self.assertEqual(len({n.get_property('node_uuid') for n in nodes}), len(CURVE_SPECS))
        self.assertTrue(all(n.get_property('project_uuid') == self.window.project_uuid for n in nodes))
        self.assertTrue(all(n.get_property('tree_modes') == {'References': 'graft'} for n in nodes))
