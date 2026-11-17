"""3D recipe math, stable trees and actual geometry Properties interactions."""
import math
from pathlib import Path
import tempfile
import unittest

import test_curves as curve_fixture
from test_curves import PROJECT, NODE, points
from noodles.backend.solids import SOLID_SPECS, evaluate_solid, normalize_solid_state, solid_object_from_outputs
from noodles.backend.reference_drive import build_reference_drive, decode_updates
from noodles.backend.point import object_from_wire
from noodles.backend.curves import PlaneValue
from noodles.backend.datatree import Branch, DataTree
from noodles.document import read_document, write_document
from Qt import QtCore
from PySide6.QtTest import QTest


def state(operation, **changes):
    return normalize_solid_state(operation, {'project_uuid': PROJECT, 'node_uuid': NODE, **changes})


class SolidDataTests(unittest.TestCase):
    def test_reference_heights_match_captured_keys_or_fail_before_publication(self):
        from dataclasses import replace
        template = evaluate_solid('cylinder', state('cylinder'), {})['G'].values()[0]
        params = state('cylinder', mode='reference', references=[
            {'key': key, 'id': key, 'recipe': replace(template, key=key).to_wire()} for key in ('a', 'b', 'c')])
        def updates(value):
            wire = build_reference_drive('cylinder', params, {'H': value})
            return [(key, patch['H']) for key, patch in decode_updates('cylinder', wire['updates']).items()]
        self.assertEqual(updates(15), [('a', 15), ('b', 15), ('c', 15)])
        self.assertEqual(updates([3, 5, 7]), [('a', 3), ('b', 5), ('c', 7)])
        for invalid in ([3, 5], [3, 5, 7, 9], [3, False, 7]):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                updates(invalid)
        params['tree_modes'] = {'References': 'graft', 'H': 'graft'}
        self.assertEqual(updates([3, 5, 7]), [('a', 3), ('b', 5), ('c', 7)])

    def test_every_primitive_deferred_wire_volume_and_default_frame(self):
        for operation in SOLID_SPECS:
            with self.subTest(operation=operation):
                parameters = state(operation)
                output = evaluate_solid(operation, parameters, {})
                self.assertEqual(output['Count'], 1)
                model = solid_object_from_outputs(parameters, output)
                self.assertEqual(model.kind, 'solids')
                self.assertEqual(object_from_wire(model.to_wire()).to_wire(), model.to_wire())
                self.assertEqual(output['O'].values()[0].xyz, (0, 0, 0))
                if 'V' in output:
                    self.assertGreater(output['V'].values()[0], 0)
        box = evaluate_solid('box', state('box'), {})
        self.assertEqual(box['C'].values()[0].xyz, (5, 5, 5))
        self.assertEqual(box['V'].values(), (1000,))
        sphere = evaluate_solid('sphere', state('sphere'), {'R': 3})
        self.assertAlmostEqual(sphere['V'].values()[0], 36*math.pi)

    def test_cylinder_and_cone_solid_shell_per_item_and_zero_enclosed_volume(self):
        for operation in ('cylinder', 'cone'):
            output = evaluate_solid(operation, state(operation), {'S': [True, False]})
            self.assertEqual(output['S'].values(), (True, False))
            self.assertGreater(output['V'].values()[0], 0)
            self.assertEqual(output['V'].values()[1], 0)
            self.assertEqual(output['Count'], 2)
            shell = state(operation, parameters={'S': False})
            self.assertFalse(shell['parameters']['S'])
            self.assertEqual(evaluate_solid(operation, shell, {})['V'].values(), (0,))
        for invalid in (2, 'Shell', None):
            with self.assertRaises(ValueError):
                evaluate_solid('cylinder', state('cylinder'), {'S': invalid})

    def test_two_hundred_slots_keep_paths_and_stable_keys_when_dimensions_change(self):
        source = DataTree(tuple(Branch((i,), tuple(points((j, i, 0) for j in range(20)))) for i in range(10)))
        dimensions = list(range(1, 201))
        for operation, port in (('box', 'Z'), ('cylinder', 'H')):
            output = evaluate_solid(operation, state(operation), {'O': source, port: dimensions})
            self.assertEqual(output['Count'], 200)
            self.assertEqual(output[port].values(), tuple(dimensions))
            changed = evaluate_solid(operation, state(operation), {'O': source, port: [v+1 for v in dimensions]})
            self.assertEqual(tuple(v.key for v in changed['G'].values()), tuple(v.key for v in output['G'].values()))
            self.assertEqual(tuple(b.path for b in output['G'].branches), tuple((i,) for i in range(10)))
        with self.assertRaises(ValueError):
            evaluate_solid('box', state('box'), {'X': [1, 2], 'Y': [1, 2, 3]})
        with self.assertRaises(ValueError):
            evaluate_solid('box', state('box'), {'O': source, 'Z': [1, 2, 3]})

    def test_truncated_cone_signed_heights_keep_radii_and_tree_paths(self):
        frame = PlaneValue((10, 20, 30), (0, 1, 0), (1, 0, 0))
        heights = DataTree((Branch((2,), (-7,)), Branch((4,), (7,))))
        output = evaluate_solid('truncated_cone', state('truncated_cone'),
                                {'P': frame, 'H': heights, 'R': 3, 'r': 6})
        self.assertEqual(tuple(b.path for b in output['G'].branches), ((2,), (4,)))
        self.assertEqual(output['H'].values(), (-7, 7))
        self.assertEqual(output['R'].values(), (3, 3))
        self.assertEqual(output['r'].values(), (6, 6))
        self.assertEqual(tuple(v.xyz for v in output['Top'].values()), ((3, 20, 30), (17, 20, 30)))
        self.assertEqual(tuple(v.xyz for v in output['N'].values()), ((-1, 0, 0), (1, 0, 0)))
        self.assertAlmostEqual(output['V'].values()[0], 147*math.pi)
        for inputs in ({'H': 0}, {'r': 0}, {'R': 5}):
            with self.assertRaises(ValueError):
                evaluate_solid('truncated_cone', state('truncated_cone'), inputs)

    def test_base_center_and_pyramid_apex_follow_the_input_plane(self):
        frame = PlaneValue((10, 20, 30), (0, 1, 0), (1, 0, 0))
        box = evaluate_solid('box_from_center', state('box_from_center'),
                             {'P': frame, 'X': 6, 'Y': 8, 'Z': 10})
        self.assertEqual(box['O'].values()[0].xyz, (10, 20, 30))
        self.assertEqual(box['C'].values()[0].xyz, (15, 20, 30))
        out = evaluate_solid('pyramid', state('pyramid'),
                             {'P': frame, 'X': 6, 'Y': 8, 'H': [-9, 12], 'S': [True, False]})
        self.assertEqual(tuple(tip.xyz for tip in out['Tip'].values()), ((1, 20, 30), (22, 20, 30)))
        self.assertEqual(out['V'].values(), (144, 0))
        with self.assertRaisesRegex(ValueError, 'nonzero Height'):
            evaluate_solid('pyramid', state('pyramid'), {'H': 0})

    def test_each_input_modifiers_placement_and_invalid_dimensions(self):
        for operation, spec in SOLID_SPECS.items():
            for descriptor in spec['inputs']:
                output = evaluate_solid(operation, state(operation, tree_modes={descriptor.port: 'graft'}), {})
                self.assertEqual(output['G'].branches[0].path, (0, 0))
            output = evaluate_solid(operation, state(operation), {'O': []})
            self.assertEqual(output['Count'], 0)
            for bad in (0, -2, float('nan'), True):
                with self.assertRaises(ValueError):
                    evaluate_solid(operation, state(operation), {spec['inputs'][0].port: bad})
        with self.assertRaisesRegex(ValueError, 'Minor Radius'):
            evaluate_solid('torus', state('torus'), {'R': 5, 'r': 5})
        frame = PlaneValue((10, 20, 30), (0, 1, 0), (1, 0, 0))
        output = evaluate_solid('cylinder', state('cylinder'), {'P': frame, 'H': 7})
        self.assertEqual(output['O'].values()[0].xyz, (10, 20, 30))
        self.assertEqual(output['Top'].values()[0].xyz, (17, 20, 30))
        explicit = evaluate_solid('cylinder', state('cylinder'), {'P': frame, 'O': points(((2, 3, 4),))[0]})
        self.assertEqual(explicit['O'].values()[0].xyz, (2, 3, 4))


class SolidPropertiesTests(unittest.TestCase):
    setUpClass = classmethod(curve_fixture.CurveWindowTests.setUpClass.__func__)
    setUp = curve_fixture.CurveWindowTests.setUp
    tearDown = curve_fixture.CurveWindowTests.tearDown
    settle = curve_fixture.CurveWindowTests.settle

    def test_solid_shell_real_keyboard_undo_and_graft_click(self):
        for kind, port in (('CylinderNode', 'H'), ('PyramidNode', 'H'), ('EllipsoidNode', 'Z')):
            with self.subTest(kind=kind):
                node = self.window.add_node('NoodleS.Geometry.' + kind)
                self.settle()
                panel = self.window.properties.curve_properties
                choice = panel.editors['S'][0]
                choice.setFocus()
                QTest.keyClick(choice, QtCore.Qt.Key_Up)
                self.settle()
                self.assertFalse(node.get_property('parameters')['S'])
                self.assertEqual(self.window.evaluation.results[node.id].outputs['V'].values(), (0,))
                self.window.graph.undo_stack().undo()
                self.settle()
                self.assertTrue(node.get_property('parameters')['S'])
                self.assertEqual(choice.currentText(), 'Solid')
                QTest.mouseClick(panel.modifiers[port].buttons['graft'], QtCore.Qt.LeftButton)
                self.settle()
                self.assertEqual(node.get_property('tree_modes'), {port: 'graft'})

    def test_all_nodes_document_roundtrip_and_reference_modes(self):
        nodes = []
        for operation, spec in SOLID_SPECS.items():
            node = self.window.add_node('NoodleS.Geometry.'+spec['class'])
            self.settle()
            node.set_property('tree_modes', {spec['inputs'][0].port: 'graft'})
            node.set_property('mode', 'reference')
            nodes.append(node)
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder)/'solids.noodles'
            write_document(path, self.window.graph.serialize_session())
            restored = read_document(path, self.window.node_ports)
            self.assertEqual(len(restored['nodes']), len(SOLID_SPECS))
