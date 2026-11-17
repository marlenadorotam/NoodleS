"""Typed curve arrays and native placement through the connected editor."""
import math
import unittest

import test_point_native as fixture
from noodles.backend.array_along_curve import evaluate, normalize_state
from noodles.backend.curves import PlaneValue, circle, line
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.rigid_motion import IDENTITY


class CurveArrayDataTests(unittest.TestCase):
    def test_matching_paths_defaults_and_placement_limit(self):
        rail = line('rail', (0, 0, 0), (10, 0, 0))
        branches = DataTree((Branch((4,), (rail,)), Branch((8,), (rail,)), Branch((9,), ())))
        result = evaluate({}, {'C': branches})
        self.assertEqual([b.path for b in result['X'].branches], [(4,), (8,), (9,)])
        self.assertEqual(result['G'].count, 0)
        self.assertEqual(len(result['_sampling']['plan']['rows']), 1)
        self.assertEqual(normalize_state({})['parameters'], {'N': 6, 'O': 1})
        with self.assertRaisesRegex(ValueError, '2,000'):
            evaluate({}, {'C': [rail] * 5, 'N': 500})
        with self.assertRaisesRegex(ValueError, 'Orientation'):
            evaluate({}, {'C': rail, 'O': 4})


class CurveArrayNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def motions(self, rail, count, orientation):
        inputs = {'C': rail, 'N': count, 'O': orientation}
        request = evaluate(self.parameters, inputs)['_sampling']
        job = self.call('geometry.sample', request)
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing')
        reply = self.call('geometry.job', job)
        self.assertEqual(reply['state'], 'complete', reply)
        details = {'signature': request['signature'], 'values': reply['measurements']}
        return evaluate({**self.parameters, 'sampling_details': details}, inputs)['X'].values()

    def test_modes_on_tilted_closed_rail_and_exact_count_on_open_rail(self):
        root = math.sqrt(.5)
        rail = circle('tilted', (0, 0, 0), 10, PlaneValue(normal=(0, -root, root)))
        start, end = (10, 0, 0), (0, 10*root, 10*root)
        for mode in range(4):
            with self.subTest(mode=mode):
                motions = self.motions(rail, 4, mode)
                self.assertEqual(len(motions), 4)
                self.assertEqual(motions[0], IDENTITY)
                self.assertLess(math.dist(motions[1].point(start), end), 1e-8)
                self.assertGreater(math.dist(motions[-1].point(start), start), 1)
                if mode == 0:
                    self.assertEqual(motions[1].axes, IDENTITY.axes)
                elif mode == 3:
                    self.assertEqual(motions[1].direction((0, 0, 1)), (0, 0, 1))
                    self.assertLess(math.dist(motions[1].direction((0, 1, 0)), (-1, 0, 0)), 1e-8)
                else:
                    self.assertLess(math.dist(motions[1].direction((0, root, root)), (-1, 0, 0)), 1e-8)
                    if mode == 2:
                        self.assertAlmostEqual(motions[1].direction((-1, 0, 0))[2], 0)
        straight = line('line', (0, 0, 0), (10, 0, 0))
        self.assertEqual(tuple(m.offset for m in self.motions(straight, 3, 0)),
                         ((0, 0, 0), (5, 0, 0), (10, 0, 0)))
        self.assertEqual(self.motions(straight, 1, 1), (IDENTITY,))
        self.assertFalse(self.window.scene.objects)

    def test_editor_publishes_one_owner_only_when_geometry_is_connected(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.backend.grid_reference_native import children
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            rail = editor.add_node('NoodleS.Geometry.LineNode')
            array = editor.add_node('NoodleS.Geometry.ArrayAlongCurveNode')
            rail.outputs()['C'].connect_to(array.inputs()['C'])
            def transforms_ready():
                result = editor.evaluation.results.get(array.id) if editor.evaluation else None
                return result and not result.error and result.outputs['X'].count == 6

            self.wait_for(transforms_ready)
            self.assertNotIn(array.id, editor.point_service.models)
            self.wait_for(lambda: editor.properties.node_id == array.id)
            orientation = editor.properties.curve_properties.editors['O'][0]
            QTest.keyClick(orientation, Qt.Key_End)
            self.assertEqual(array.curve_state()['parameters']['O'], 3)

            box = editor.add_node('NoodleS.Geometry.BoxNode')
            box.set_property('parameters', {'X': 1, 'Y': 2, 'Z': 3})
            box.outputs()['G'].connect_to(array.inputs()['G'])
            identity = editor.project_uuid, array.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None)
            self.assertEqual(len(tuple(children(owner().shape))), 6)
            object_id = owner().id
            array.set_property('parameters', {'N': 3, 'O': 3})
            self.wait_for(lambda: len(tuple(children(owner().shape))) == 3)
            self.assertEqual(owner().id, object_id)
            box.outputs()['G'].disconnect_from(array.inputs()['G'])
            self.wait_for(lambda: owner() is None)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
