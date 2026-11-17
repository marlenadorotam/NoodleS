"""Pull Point's DataTree and exact native projection through a Reference node."""
import math
import unittest

import test_point_native as fixture
from test_curves import PROJECT, NODE
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.point import PointValue
from noodles.backend.pull import evaluate_pull


def p(key, x, y=0, z=0):
    return PointValue(key, (x, y, z))


class PullDataTests(unittest.TestCase):
    def test_nearest_across_each_branch_and_explicit_flatten(self):
        points = DataTree((Branch((2,), (p('a', 2), p('b', 8))),
                           Branch((5,), (p('c', 2),))))
        attractors = DataTree((Branch((2,), (p('one', 0), p('two', 10), p('three', 30))),
                               Branch((5,), (p('four', 9),))))
        out = evaluate_pull({}, {'P': points, 'G': attractors})
        self.assertEqual([b.path for b in out['P'].branches], [(2,), (5,)])
        self.assertEqual(out['D'].values(), (2., 2., 7.))
        self.assertEqual(out['P'].branches[0].keys, points.branches[0].keys)
        flat = evaluate_pull({'tree_modes': {'G': 'flatten'}}, {'P': points, 'G': attractors})
        self.assertEqual(flat['D'].values(), (2., 1., 2.))
        with self.assertRaisesRegex(ValueError, 'matching branch paths'):
            evaluate_pull({'tree_modes': {'G': 'graft'}}, {'P': points, 'G': attractors})
        with self.assertRaisesRegex(ValueError, 'at least one attractor'):
            evaluate_pull({}, {'P': points, 'G': []})


class NativePullTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def test_pull_reference_curve_projects_on_trim_and_tracks_manual_edits(self):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.TopoDS import TopoDS
        from noodles.backend.curves import curve_from_wire
        from noodles.backend.spline_native import materialize_spline
        from noodles.window import MainWindow

        recipe = {'key': 'rational', 'kind': 'curve', 'points': [[1, 0, 0], [1, 1, 0], [0, 1, 0]],
                  'degree': 2, 'closed': False, 'periodic': False, 'knots': [0, 1],
                  'multiplicities': [3, 3], 'weights': [1, math.sqrt(.5), 1], 'domain': [0, 1]}
        edge = materialize_spline(curve_from_wire(recipe))
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge)).BSpline()
        trimmed = BRepBuilderAPI_MakeEdge(curve, .3, .8).Edge()
        expected = self.geo.pnt_tuple(curve.Value(.3))
        scene = self.window.scene
        native_curve = scene.add(trimmed, name='Trimmed reference curve')
        native_point = scene.add(self.geo.make_point((2, 0, 0)), name='Probe')
        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()

        def capture(node, native):
            node.set_property('mode', 'reference')
            self.wait_for(lambda: editor.properties.node_id == node.id)
            self.window.selection.set([native.id])
            editor._capture_points()
            self.wait_for(lambda: len(node.get_property('references')) == 1)

        try:
            point = editor.add_node('NoodleS.Geometry.PointNode')
            capture(point, native_point)
            curve_node = editor.add_node('NoodleS.Geometry.CurveNode')
            capture(curve_node, native_curve)
            pull = editor.add_node('NoodleS.Operations.PullPointNode')
            point.outputs()['P'].connect_to(pull.inputs()['P'])
            curve_node.outputs()['C'].connect_to(pull.inputs()['G'])

            def projected(target):
                result = editor.evaluation.results.get(pull.id)
                if not result or result.error:
                    return False
                value = result.outputs['P'].values()[0]
                return isinstance(value, PointValue) and math.dist(value.xyz, target) < 1e-7

            self.wait_for(lambda: projected(expected))
            self.assertAlmostEqual(editor.evaluation.results[pull.id].outputs['D'].values()[0],
                                   math.dist((2, 0, 0), expected))
            self.assertIn('D ·', editor.properties.output.text())
            self.assertEqual(set(scene.objects), {native_curve.id, native_point.id})
            self.assertIs(scene.get(native_curve.id)._shape, trimmed)

            edited = self.geo.translate(trimmed, (0, 0, 3))
            scene.replace_shape(native_curve.id, edited)
            self.wait_for(lambda: projected((expected[0], expected[1], 3)))
            self.assertEqual(set(scene.objects), {native_curve.id, native_point.id})
            self.assertIs(scene.get(native_curve.id)._shape, edited)
        finally:
            editor.point_service.stop()
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_mixed_attractors_choose_actual_closest_shape(self):
        from noodles.backend.curves import line
        query = (p('q', 2, 2), p('r', 7, 8))
        inputs = {'P': list(query), 'G': [p('target', 7, 7), line('edge', (0, 0, 0), (10, 0, 0))]}
        payload = evaluate_pull({'project_uuid': PROJECT, 'node_uuid': NODE}, inputs)['_pull']
        request = self.call('geometry.pull', payload)
        self.wait_for(lambda: self.bridge.geometry.jobs[request['job_id']]['state'] != 'preparing')
        result = self.call('geometry.job', request)
        self.assertEqual(result['state'], 'complete', result)
        self.assertEqual(result['measurements'], [[[2, 0, 0], [7, 7, 0]]])
        self.assertFalse(self.window.scene.objects)

    def test_latest_measurement_supersedes_queued_curve_work(self):
        import threading
        from noodles.backend.curves import line

        inputs = {'P': p('p', 2, 3), 'G': line('line', (0, 0, 0), (10, 0, 0))}
        state = {'project_uuid': PROJECT, 'node_uuid': NODE}
        release = threading.Event()
        self.bridge.geometry.pool.submit(release.wait, 5)
        try:
            first = self.call('geometry.pull', evaluate_pull(state, inputs)['_pull'])
            inputs['P'] = p('p', 7, 9)
            second = self.call('geometry.pull', evaluate_pull(state, inputs)['_pull'])
            self.assertEqual(self.call('geometry.job', first)['state'], 'superseded')
        finally:
            release.set()
        self.wait_for(lambda: self.bridge.geometry.jobs[second['job_id']]['state'] != 'preparing')
        self.assertEqual(self.call('geometry.job', second)['measurements'], [[[7, 0, 0]]])
