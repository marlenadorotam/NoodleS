"""Spline fitting, exact reference shapes and asynchronous derived outputs on real OCC."""
import copy
import math
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from Qt import QtCore
from noodles.backend.curves import evaluate_curve, curve_from_wire
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.splines import signature, PendingGeometry
from test_curves import state, inputs_for, points
import test_curve_native as curve_fixture


class NativeSplineTests(unittest.TestCase):
    setUpClass = classmethod(curve_fixture.NativeCurveTests.setUpClass.__func__)
    setUp = curve_fixture.NativeCurveTests.setUp
    tearDown = curve_fixture.NativeCurveTests.tearDown
    call = curve_fixture.NativeCurveTests.call
    wait_for = curve_fixture.NativeCurveTests.wait_for
    model = curve_fixture.NativeCurveTests.model
    publish = curve_fixture.NativeCurveTests.publish

    def test_legacy_bezier_reference_preserves_weights_trim_orientation_and_placement(self):
        from OCP.Geom import Geom_BezierCurve
        from OCP.gp import gp_Pnt
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.TColStd import TColStd_Array1OfReal
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS
        from noodles.backend.spline_native import materialize_spline
        poles = TColgp_Array1OfPnt(1, 3)
        weights = TColStd_Array1OfReal(1, 3)
        for i, (p, weight) in enumerate(zip(((1, 0, 0), (1, 1, 0), (0, 1, 0)), (1, math.sqrt(.5), 1)), 1):
            poles.SetValue(i, gp_Pnt(*p))
            weights.SetValue(i, weight)
        shape = BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles, weights), .2, .9).Edge().Reversed()
        shape = self.geo.translate(shape, (3, 4, 5))
        obj = self.window.scene.add(shape, name='Editable Bezier')
        self.window.selection.set([obj.id])
        original = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
        for operation in ('curve', 'interpcurve'):
            refs = self.call('curves.capture', state(operation, mode='reference'))['references']
            value = curve_from_wire(refs[0]['recipe'])
            self.assertTrue(any(weight != 1 for weight in value.weights))
            actual = BRepAdaptor_Curve(TopoDS.Edge_s(materialize_spline(value)))
            for t in (0, .1, .5, .9, 1):
                old_t = original.LastParameter()-t*(original.LastParameter()-original.FirstParameter())
                new_t = actual.FirstParameter()+t*(actual.LastParameter()-actual.FirstParameter())
                self.assertLess(original.Value(old_t).Distance(actual.Value(new_t)), 1e-8)
            self.assertEqual(refs[0]['id'], obj.id)
            self.assertIs(self.window.scene.get(obj.id)._shape, shape)
        self.assertEqual(len(self.window.scene.objects), 1)

    def test_legacy_singular_three_point_interpolation_is_preserved(self):
        from noodles.backend.scene_curves import materialize
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS
        sites = ((0, 0, 0), (4, 7, 3), (10, 1, 2))
        value = evaluate_curve('interpcurve', state('interpcurve'), {'P': points(sites)})['C'].values()[0]
        shape = materialize(value)
        actual = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
        arguments = (0, math.dist(sites[0], sites[1]), math.dist(sites[0], sites[1])+math.dist(sites[1], sites[2]))
        for t, target in zip(arguments, sites):
            p = actual.Value(t)
            self.assertLess(math.dist((p.X(), p.Y(), p.Z()), target), 1e-7)

    def test_all_interpolation_degrees_styles_periodic_and_closed_fit_actual_sites(self):
        from noodles.backend.scene_curves import materialize
        from noodles.backend.spline_native import _params
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS
        from OCP.BRepCheck import BRepCheck_Analyzer
        sites = ((0, 0, 0), (1, 4, 2), (5, 1, 1), (9, 6, 3), (10, 2, -1), (12, 0, 2))
        for degree in range(1, 6):
            for style in range(3):
                for closed, periodic in ((False, False), (True, False), (False, True)):
                    with self.subTest(degree=degree, style=style, closed=closed, periodic=periodic):
                        output = evaluate_curve('interpcurve', state('interpcurve'),
                            {'P': points(sites), 'D': degree, 'K': style, 'C': closed, 'T': periodic})
                        value = output['C'].values()[0]
                        shape = materialize(value)
                        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
                        adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
                        if degree == 3 and style == 1 and not periodic:
                            # The retained legacy OCC interpolator uses cumulative chord lengths.
                            arguments = [0.]
                            for a, b in zip(sites, sites[1:]):
                                arguments.append(arguments[-1]+math.dist(a, b))
                        elif periodic:
                            knots = _params(sites, style, True)
                            arguments = [a+.25*(b-a) for a, b in zip(knots, knots[1:])]
                        else:
                            arguments = _params(sites+(sites[0],) if closed else sites, style, False)[:len(sites)]
                        for argument, target in zip(arguments, sites):
                            p = adaptor.Value(argument)
                            self.assertLess(math.dist((p.X(), p.Y(), p.Z()), target), 1e-6)
                        self.assertEqual(adaptor.IsClosed(), closed or periodic)
                        if periodic:
                            self.assertTrue(adaptor.IsPeriodic())

    def test_exact_rational_trimmed_reversed_references_and_reconstruction(self):
        from noodles.backend.spline_native import materialize_spline, describe_spline
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.TopoDS import TopoDS
        recipe = {'key': 'rational', 'kind': 'curve', 'points': [[1, 0, 0], [1, 1, 0], [0, 1, 0]],
            'degree': 2, 'closed': False, 'periodic': False, 'knots': [0, 1],
            'multiplicities': [3, 3], 'weights': [1, math.sqrt(.5), 1], 'domain': [0, 1], 'length': math.pi/2}
        edge = materialize_spline(curve_from_wire(recipe))
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge)).BSpline()
        trimmed = BRepBuilderAPI_MakeEdge(curve, .1, .8).Edge().Reversed()
        for kind in ('curve', 'interpcurve'):
            value = describe_spline(trimmed, 'rational', kind)
            self.assertTrue(any(w != 1 for w in value.weights))
            rebuilt = materialize_spline(curve_from_wire(value.to_wire()))
            original = BRepAdaptor_Curve(TopoDS.Edge_s(trimmed))
            actual = BRepAdaptor_Curve(TopoDS.Edge_s(rebuilt))
            for t in (0, .1, .5, .9, 1):
                old_t = original.LastParameter()-t*(original.LastParameter()-original.FirstParameter())
                new_t = actual.FirstParameter()+t*(actual.LastParameter()-actual.FirstParameter())
                self.assertLess(original.Value(old_t).Distance(actual.Value(new_t)), 1e-8)
            self.assertAlmostEqual(value.length, describe_spline(rebuilt, 'rational', kind).length, delta=1e-8)

    def test_two_hundred_branches_share_owner_native_worker_and_cache(self):
        from noodles.backend.scene_curves import materialize
        sites = tuple(inputs_for('curve')['P'])
        branches = tuple(Branch((i,), tuple(type(p)(p.key, (p.xyz[0], p.xyz[1]+i, p.xyz[2])) for p in sites)) for i in range(200))
        tree = DataTree(branches)
        worker_ids = []
        def build(value):
            worker_ids.append(threading.get_ident())
            return materialize(value)
        with patch('noodles.backend.scene_curves.materialize', side_effect=build):
            owner = self.publish(self.model('curve', inputs={'P': tree}))
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(worker_ids), 200)
        self.assertNotIn(threading.get_ident(), worker_ids)
        changed = list(branches)
        changed[77] = Branch((77,), tuple(type(p)(p.key, (p.xyz[0], p.xyz[1], p.xyz[2]+1)) for p in changed[77].items))
        with patch('noodles.backend.scene_curves.materialize', wraps=materialize) as build:
            updated = self.publish(self.model('curve', inputs={'P': DataTree(tuple(changed))}))
            self.assertEqual(build.call_count, 1)
        self.assertEqual(owner.id, updated.id)

    def test_native_details_resolve_length_and_control_points_without_republication(self):
        parameters = state('interpcurve')
        inputs = inputs_for('interpcurve')
        owner = self.publish(self.model('interpcurve'))
        details = list(self.bridge.points.jobs.values())[-1]['curve_details']
        output = evaluate_curve('interpcurve', {**parameters, 'curve_details': details}, inputs)
        self.assertGreater(output['L'].values()[0], 0)
        self.assertGreaterEqual(output['CP'].count, 4)
        self.assertEqual(output['V'].count, 4)
        self.assertEqual(self.model('interpcurve', parameters={**parameters, 'curve_details': details}), self.model('interpcurve'))
        previous_shape, previous_mesh = owner._shape, owner._mesh
        again = self.publish(self.model('interpcurve'))
        self.assertIs(again._shape, previous_shape)
        self.assertIs(again._mesh, previous_mesh)
        # Details must also be returned when the shape is already up to date.
        self.assertTrue(list(self.bridge.points.jobs.values())[-1]['curve_details'])

    def test_reference_measurements_run_off_qt_and_bind_after_serp_reopen(self):
        from noodles.backend.spline_native import describe_spline
        from noodles.backend.scene_curves import materialize
        from serpentine3d.fileio.native import save_scene, load_scene
        params = state('interpcurve', mode='reference')
        generated = evaluate_curve('interpcurve', state('interpcurve'), inputs_for('interpcurve'))['C'].values()[0]
        obj = self.window.scene.add(materialize(generated), name='Editable spline')
        self.window.selection.set([obj.id])
        measured_on = []
        def describe(*args, **kwargs):
            if kwargs.get('measure', True):
                measured_on.append(threading.get_ident())
            return describe_spline(*args, **kwargs)
        with patch('noodles.backend.spline_native.describe_spline', side_effect=describe):
            refs = self.call('curves.capture', params)['references']
            self.wait_for(lambda: bool(measured_on))
            self.wait_for(lambda: self.bridge.points.curves.inspections['interpcurve:'+obj.id]['future'].done())
            self.app.processEvents()
            refs = self.call('curves.read', {**params, 'references': refs})['references']
        self.assertNotIn(threading.get_ident(), measured_on)
        output = evaluate_curve('interpcurve', {**params, 'references': refs}, {})
        self.assertIsInstance(output['L'].values()[0], float)
        self.assertEqual(output['V'].count, 0)  # No invented interpolation sites.
        self.assertGreater(output['CP'].count, 0)
        path = Path(self.folder.name)/'spline.serp'
        save_scene(self.window.scene, str(path))
        restored = self.Scene()
        load_scene(restored, str(path))
        self.window.scene = restored
        current = self.call('curves.read', {**params, 'references': refs})['references'][0]
        self.assertNotEqual(current['id'], obj.id)
        self.assertEqual(current['key'], refs[0]['key'])
        self.assertEqual(current['recipe']['weights'], refs[0]['recipe']['weights'])

    def test_native_window_point_to_interpcurve_length_feedback(self):
        from noodles.window import MainWindow
        app = MainWindow()
        app.point_service.client = self.client
        app.point_service.start()
        app.show()
        try:
            point = app.add_node('NoodleS.Geometry.PointNode')
            source = [self.window.scene.add(self.geo.make_point(v.xyz)) for v in inputs_for('interpcurve')['P']]
            self.window.selection.set([p.id for p in source])
            point.set_property('mode', 'reference')
            self.app.processEvents()
            app._refresh_inspector()
            app._capture_points()
            self.wait_for(lambda: len(point.get_property('references')) == 4)
            curve = app.add_node('NoodleS.Geometry.InterpCurveNode')
            point.outputs()['P'].connect_to(curve.inputs()['P'])
            watch = app.add_node('NoodleS.Data.WatchNode')
            curve.outputs()['L'].connect_to(watch.inputs()['Value'])
            self.wait_for(lambda: app.evaluation and watch.id in app.evaluation.results and not app.evaluation.results[watch.id].error)
            old_length = app.evaluation.results[watch.id].outputs['Value'].values()[0]
            self.assertIsInstance(old_length, float)
            self.assertEqual(len(self.window.scene.objects), 5)
            self.window.scene.replace_shape(source[-1].id, self.geo.make_point((30, 20, 5)))
            app.point_service.refresh()
            self.wait_for(lambda: not app.evaluation.results[watch.id].error and app.evaluation.results[watch.id].outputs['Value'].values()[0] != old_length)
            self.assertEqual(len(self.window.scene.objects), 5)
        finally:
            app.graph.undo_stack().setClean()
            app.close()
            app.deleteLater()
            self.app.processEvents()
