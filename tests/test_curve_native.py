"""Real OCC/Scene/TCP tests, always in private scenes (never the user's CAD document)."""
import copy
import json
import importlib.util
import math
from pathlib import Path
import uuid
import unittest
from unittest.mock import patch

import test_point_native as native_fixture
from noodles.backend.curves import CURVE_SPECS, evaluate_curve, curve_object_from_outputs, PlaneValue
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.point import PointValue
from noodles.bridge import BridgeRemoteError
from test_curves import state, inputs_for


class NativeCurveTests(unittest.TestCase):
    setUpClass = classmethod(native_fixture.NativePointTests.setUpClass.__func__)
    setUp = native_fixture.NativePointTests.setUp
    tearDown = native_fixture.NativePointTests.tearDown
    call = native_fixture.NativePointTests.call
    wait_for = native_fixture.NativePointTests.wait_for

    def model(self, operation='circle', parameters=None, inputs=None):
        parameters = parameters or state(operation)
        output = evaluate_curve(operation, parameters, inputs if inputs is not None else inputs_for(operation))
        return curve_object_from_outputs(parameters, output).to_wire()

    def publish(self, model):
        request = self.call('geometry.prepare', {'model': model, 'name': 'Primitive'})
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        result = self.call('geometry.job', request)
        self.assertEqual(result['state'], 'complete', result)
        return self.window.scene.get(result['object_id']) if result.get('object_id') else None

    def native_source(self, operation):
        from noodles.backend.curves import curve_from_wire
        from noodles.backend.scene_curves import materialize
        value = curve_from_wire(self.model(operation)['branches'][0]['parts'][0])
        return self.window.scene.add(materialize(value), name=operation)

    def test_curves_reference_mixed_selection_drives_loft_in_selection_order(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_Circle, GeomAbs_Ellipse
        from noodles.backend.geometry import recipe_from_wire
        from noodles.backend.scene_curves import materialize
        from noodles.window import MainWindow

        g = self.geo
        scene = self.window.scene
        sections = [scene.add(shape) for shape in (
            g.make_circle((0, 0, 0), 5),
            g.make_ellipse((0, 0, 10), 6, 4),
            g.make_interp_curve([(6, 0, 20), (0, 6, 20), (-6, 0, 20), (0, -6, 20)], closed=True),
        )]
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            node = editor.add_node('NoodleS.Geometry.CurvesNode')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: panel.sources['reference'].isVisible())
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            self.wait_for(panel.capture.isVisible)
            # Selection is deliberately reversed from scene creation order.
            ids = [obj.id for obj in reversed(sections)]
            self.window.selection.set(ids)
            QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(node.get_property('references')) == 3)
            records = node.get_property('references')
            self.assertEqual([record['id'] for record in records], ids)
            kinds = [BRepAdaptor_Curve(g.edges_of(materialize(recipe_from_wire(record['recipe'])))[0]).GetType()
                     for record in records]
            self.assertEqual(kinds, [GeomAbs_BSplineCurve, GeomAbs_Ellipse, GeomAbs_Circle])
            loft = editor.add_node('NoodleS.Geometry.LoftNode')
            node.outputs()['C'].connect_to(loft.inputs()['C'])
            identity = (editor.project_uuid, loft.curve_state()['node_uuid'], 0)
            self.wait_for(lambda: self.bridge.points.owner(identity) is not None)
            owner = self.bridge.points.owner(identity)
            self.assertGreater(g.surface_area(owner.shape), 0.)
            self.assertEqual(len(scene.objects), 4)
            scene.replace_shape(sections[0].id, g.make_circle((0, 0, 0), 7))
            self.wait_for(lambda: self.bridge.points.owner(identity)._shape is not owner._shape)
            self.assertEqual(self.bridge.points.owner(identity).id, owner.id)
            self.assertEqual([record['key'] for record in node.get_property('references')],
                             [record['key'] for record in records])
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_all_primitives_generate_one_real_compound_with_native_display_mesh(self):
        from OCP.TopAbs import TopAbs_COMPOUND
        for operation in CURVE_SPECS:
            with self.subTest(operation=operation):
                owner = self.publish(self.model(operation))
                self.assertEqual(owner.shape.ShapeType(), TopAbs_COMPOUND)
                self.assertEqual(len(self.window.scene.objects), 1)
                self.assertTrue(owner.mesh_ready)
                self.assertGreater(self.geo.curve_length(owner.shape), 0)

    def test_ellipse_axis_order_and_perimeter_match_native_occ(self):
        from noodles.backend.curves import curve_from_wire
        from noodles.backend.scene_curves import materialize
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GCPnts import GCPnts_AbscissaPoint
        from OCP.TopoDS import TopoDS
        for a, b in ((10, 5), (5, 10), (10, 10), (100, .1)):
            parameters = state('ellipse', parameters={'A': a, 'B': b})
            value = evaluate_curve('ellipse', parameters, {})['C'].values()[0]
            shape = materialize(value)
            low, high = self.geo.bbox(shape)
            self.assertAlmostEqual(high[0]-low[0], 2*a, delta=1e-5)
            self.assertAlmostEqual(high[1]-low[1], 2*b, delta=1e-5)
            adaptor = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
            length = GCPnts_AbscissaPoint.Length_s(adaptor, adaptor.FirstParameter(), adaptor.LastParameter(), 1e-10)
            self.assertAlmostEqual(length, value.length, delta=max(a, b)*1e-7)

    def test_ellipse_reference_accepts_circle_limit_but_not_partial_ellipse(self):
        scene = self.window.scene
        obj = scene.add(self.geo.make_circle((0, 0, 0), 7))
        parameters = state('ellipse', mode='reference')
        self.window.selection.set([obj.id])
        records = self.call('curves.capture', parameters)['references']
        self.assertEqual(records[0]['recipe']['dimensions'], [7, 7])
        scene.replace_shape(obj.id, self.geo.make_ellipse_axis((1, 2, 3), (0, 1, 0), 12, 4))
        updated = self.call('curves.read', {**parameters, 'references': records})['references'][0]
        self.assertEqual(updated['key'], records[0]['key'])
        self.assertEqual(updated['recipe']['dimensions'], [12, 4])
        shape = self.geo.make_ellipse_axis((0, 0, 0), (1, 0, 0), 12, 4, start=0, end=math.pi)
        scene.replace_shape(obj.id, shape)
        with self.assertRaises(BridgeRemoteError):
            self.call('curves.read', {**parameters, 'references': records})

    def test_ellipse_reference_captures_affine_nurbs_and_single_edge_wire_in_properties(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
        from OCP.GeomAbs import GeomAbs_BSplineCurve
        from noodles.window import MainWindow

        scene = self.window.scene
        native = self.geo.make_ellipse((0, 0, 0), 10, 5)
        scaled = self.geo.scale(native, (0, 0, 0), 1., factors=(1., 3., 1.))
        self.assertEqual(BRepAdaptor_Curve(self.geo.edges_of(scaled)[0]).GetType(), GeomAbs_BSplineCurve)
        first = scene.add(scaled, name='Scaled ellipse')
        second = scene.add(BRepBuilderAPI_MakeWire(self.geo.edges_of(native)[0]).Wire(), name='Wrapped ellipse')
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            slider = editor.add_node('NoodleS.Inputs.SliderNode')
            slider.set_property('value', 7.)
            node = editor.add_node('NoodleS.Geometry.EllipseNode')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: editor.properties.node_id == node.id and panel.sources['reference'].isVisible())
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            self.wait_for(panel.capture.isVisible)
            scene_selection = self.window.selection
            for ids in ([first.id], [first.id, second.id]):
                scene_selection.set(ids)
                QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
                self.wait_for(lambda: len(node.get_property('references')) == len(ids))
                self.wait_for(lambda: editor.evaluation.results[node.id].outputs.get('Count') == len(ids))
            records = {record['id']: record for record in node.get_property('references')}
            self.assertAlmostEqual(records[first.id]['recipe']['dimensions'][0], 15.)
            self.assertAlmostEqual(records[first.id]['recipe']['dimensions'][1], 10.)
            self.assertEqual(records[second.id]['recipe']['dimensions'], [10., 5.])
            self.assertIs(scene.get(first.id)._shape, scaled)
            slider.outputs()['Number'].connect_to(node.inputs()['A'])
            self.wait_for(lambda: editor.evaluation.results[node.id].outputs['A'].values() == (7., 7.))
            self.assertEqual(set(scene.objects), {first.id, second.id})
            self.assertEqual({r['key'] for r in node.get_property('references')},
                             {r['key'] for r in records.values()})
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_ellipse_reference_rejects_closed_quadratic_nurbs_that_is_not_a_conic(self):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Pnt

        ellipse = self.geo.make_ellipse((0, 0, 0), 10, 5)
        scaled = self.geo.scale(ellipse, (0, 0, 0), 1., factors=(1., 2., 1.))
        spline = BRepAdaptor_Curve(self.geo.edges_of(scaled)[0]).BSpline()
        pole = spline.Pole(2)
        spline.SetPole(2, gp_Pnt(pole.X()+1., pole.Y(), pole.Z()))
        source = self.window.scene.add(BRepBuilderAPI_MakeEdge(spline).Edge())
        self.window.selection.set([source.id])
        with self.assertRaisesRegex(BridgeRemoteError, 'complete ellipse or circle'):
            self.call('curves.capture', state('ellipse', mode='reference'))

    def test_installed_server_discards_stale_geometry_modules_on_upgrade(self):
        import sys
        from noodles.install_bridge import install
        from noodles.bridge import BridgeClient
        directory = Path(self.folder.name)/'plugins'
        install(directory)
        spec = importlib.util.spec_from_file_location('ellipse_installed_bridge', directory/'NoodleSBridge.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        descriptor = self.bridge.descriptor
        self.bridge.stop()
        self.bridge = module.BridgeServer(self.ctx, descriptor)
        self.bridge.start()
        self.client = BridgeClient(descriptor, timeout=1)
        owner = self.publish(self.model('ellipse'))
        stale = sys.modules['_noodles_core.curves']
        stale.CURVE_SPECS.pop('ellipse')
        self.bridge.stop()
        self.bridge = module.BridgeServer(self.ctx, descriptor)
        self.bridge.start()
        self.assertIsNot(sys.modules['_noodles_core.curves'], stale)
        updated = self.publish(self.model('ellipse', inputs={'A': 15}))
        self.assertEqual(updated.id, owner.id)

    def test_two_hundred_ellipses_share_one_owner_and_reuse_unchanged_parts(self):
        from noodles.backend.scene_curves import materialize
        radii = [10+i/10 for i in range(200)]
        owner = self.publish(self.model('ellipse', inputs={'A': radii, 'B': 5}))
        self.assertEqual(len(self.window.scene.objects), 1)
        radii[100] += .25
        with patch('noodles.backend.scene_curves.materialize', wraps=materialize) as build:
            updated = self.publish(self.model('ellipse', inputs={'A': radii, 'B': 5}))
            self.assertEqual(updated.id, owner.id)
            self.assertEqual(build.call_count, 1)

    def test_two_hundred_circles_one_owner_and_all_scene_attributes_survive(self):
        scene = self.window.scene
        owner = self.publish(self.model())
        layer = scene.layers.create('Parametric curves')
        scene.update(owner.id, name='My circles', layer_id=layer.id, color=(.2, .3, .4), visible=False, locked=True,
                     linetype='Continuous', print_width=.7, material={'opacity': .8})
        params = state('circle')
        centers = DataTree((Branch((4,), tuple(PointValue('p'+str(i), (i*30, 0, 0)) for i in range(200))),))
        before = scene.revision
        output = self.publish(self.model('circle', params, {'C': centers, 'R': list(range(1, 201))}))
        self.assertEqual(len(scene.objects), 1)
        self.assertEqual(output.id, owner.id)
        self.assertEqual(output.name, 'My circles')
        self.assertEqual(output.color, (.2, .3, .4))
        self.assertFalse(output.visible)
        self.assertTrue(output.locked)
        self.assertEqual(output.print_width, .7)
        self.assertEqual(output.material, {'opacity': .8})
        self.assertGreater(scene.revision, before)
        self.assertAlmostEqual(self.geo.curve_length(output.shape), 2*math.pi*sum(range(1, 201)), delta=.01)
        self.assertEqual(output.linetype, 'Continuous')
        self.assertEqual(output.layer_id, layer.id)
        scene.update(output.id, color=None)
        output = self.publish(self.model(inputs={'R': 33}))
        self.assertIsNone(output.color)  # ByLayer remains authoritative.
        self.assertEqual(output.layer_id, layer.id)

    def test_topology_only_reuses_shape_mesh_and_empty_removes_owned_geometry(self):
        params = state('circle')
        owner = self.publish(self.model('circle', params, {'R': [2, 3]}))
        shape, mesh = owner.shape, owner.mesh
        updated = self.publish(self.model('circle', state('circle', tree_modes={'R': 'graft'}), {'R': [2, 3]}))
        self.assertIs(updated.shape, shape)
        self.assertIs(updated.mesh, mesh)
        self.assertIsNone(self.publish(self.model('circle', params, {'R': []})))
        self.assertFalse(self.window.scene.objects)

    def test_changing_one_of_two_hundred_parts_reuses_the_other_native_shapes(self):
        from noodles.backend.scene_curves import materialize
        radii = list(range(1, 201))
        self.publish(self.model(inputs={'R': radii}))
        radii[100] += .5
        with patch('noodles.backend.scene_curves.materialize', wraps=materialize) as build:
            self.publish(self.model(inputs={'R': radii}))
            self.assertEqual(build.call_count, 1)

    def test_circle_update_refreshes_display_mesh_and_preserves_owner(self):
        import numpy as np
        from noodles.backend.native_display import tessellate

        owner = self.publish(self.model(inputs={'R': [100, 10, 50]}))
        original_mesh = owner.mesh
        updated = self.publish(self.model(inputs={'R': [101, 10, 50]}))
        self.assertEqual(updated.id, owner.id)
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertIsNot(updated.mesh, original_mesh)
        expected = tessellate(updated.shape)
        np.testing.assert_array_equal(updated.mesh.edge_segments, expected.edge_segments)
        np.testing.assert_array_equal(updated.mesh.edge_of_segment, expected.edge_of_segment)

    def test_reference_move_rotate_scale_and_native_parameter_edits_keep_ids(self):
        scene = self.window.scene
        for operation in CURVE_SPECS:
            with self.subTest(operation=operation):
                obj = self.native_source(operation)
                params = state(operation, mode='reference', node_uuid=str(uuid.uuid4()))
                self.window.selection.set([obj.id])
                records = self.call('curves.capture', params)['references']
                before = records[0]
                moved = self.geo.translate(obj.shape, (3, 4, 5))
                moved = self.geo.rotate(moved, (0, 0, 0), (1, 0, 0), .5)
                moved = self.geo.scale(moved, (0, 0, 0), 2)
                scene.replace_shape(obj.id, moved)
                current = self.call('curves.read', {**params, 'references': records})['references'][0]
                self.assertEqual(current['id'], obj.id)
                self.assertEqual(current['key'], before['key'])
                self.assertNotEqual(current['recipe']['points'], before['recipe']['points'])
                scene.remove(obj.id)
        obj = scene.add(self.geo.make_circle((0, 0, 0), 2))
        params = state('circle', mode='reference')
        self.window.selection.set([obj.id])
        refs = self.call('curves.capture', params)['references']
        scene.replace_shape(obj.id, self.geo.make_circle((10, 20, 30), 77, (0, 1, 0)))
        recipe = self.call('curves.read', {**params, 'references': refs})['references'][0]['recipe']
        self.assertEqual(recipe['radius'], 77)
        self.assertEqual(recipe['plane']['origin'], [10, 20, 30])

    def test_reference_reopen_and_missing_or_duplicate_metadata_errors(self):
        from serpentine3d.fileio.native import save_scene, load_scene
        scene = self.window.scene
        obj = self.native_source('rectangle')
        params = state('rectangle', mode='reference')
        self.window.selection.set([obj.id])
        refs = self.call('curves.capture', params)['references']
        path = Path(self.folder.name)/'curves.serp'
        save_scene(scene, str(path))
        restored = self.Scene()
        load_scene(restored, str(path))
        self.window.scene = restored
        current = self.call('curves.read', {**params, 'references': refs})['references'][0]
        self.assertNotEqual(current['id'], obj.id)
        self.assertEqual(current['key'], refs[0]['key'])
        original = restored.get(current['id'])
        duplicate = restored.add(original.shape, name='copy')
        restored.update(duplicate.id, user_text=copy.deepcopy(original.user_text))
        with self.assertRaises(BridgeRemoteError):
            self.call('curves.read', {**params, 'references': refs})
        restored.remove(duplicate.id)
        restored.remove(original.id)
        with self.assertRaises(BridgeRemoteError):
            self.call('curves.read', {**params, 'references': refs})

    def test_capture_is_atomic_and_rejects_generated_compounds_without_claiming_sources(self):
        scene = self.window.scene
        source = self.native_source('circle')
        line = self.native_source('line')
        self.window.selection.set([source.id, line.id])
        with self.assertRaises(BridgeRemoteError):
            self.call('curves.capture', state('circle', mode='reference'))
        self.assertIsNone(scene.get(source.id).user_text)
        owner = self.publish(self.model())
        self.window.selection.set([owner.id])
        with self.assertRaises(BridgeRemoteError):
            self.call('curves.capture', state('circle', mode='reference'))
        self.assertEqual(len(scene.objects), 3)

    def test_scene_user_text_and_owner_restore_together_with_native_undo(self):
        owner = self.publish(self.model('circle', inputs={'R': 3}))
        before = self.geo.curve_length(owner.shape)
        manifest = copy.deepcopy(owner.user_text)
        updated = self.publish(self.model('circle', inputs={'R': 9}))
        self.assertAlmostEqual(self.geo.curve_length(updated.shape), before*3)
        self.window.history.undo()
        restored = self.window.scene.get(owner.id)
        self.assertAlmostEqual(self.geo.curve_length(restored.shape), before)
        self.assertEqual(restored.user_text, manifest)

    def test_real_window_generate_capture_live_native_edit_and_delete_reference(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow
        app = MainWindow()
        app.point_service.client = self.client
        app.point_service.start()
        app.show()
        try:
            node = app.add_node('NoodleS.Geometry.CircleNode')
            self.wait_for(lambda: len(self.window.scene.objects) == 1)
            owner = next(iter(self.window.scene.all()))
            self.assertEqual(owner.shape.ShapeType().name, 'TopAbs_COMPOUND')
            source = self.window.scene.add(self.geo.make_circle((1, 2, 3), 8), name='Source circle')
            panel = app.properties.curve_properties
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            self.wait_for(lambda: self.window.scene.get(owner.id) is None)
            self.window.selection.set([source.id])
            QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(node.get_property('references')) == 1)
            self.wait_for(lambda: not app.evaluation.results[node.id].error)
            self.window.scene.replace_shape(source.id, self.geo.make_circle((50, 60, 70), 12, (0, 1, 0)))
            self.wait_for(lambda: not app.evaluation.results[node.id].error and
                          app.evaluation.results[node.id].outputs['R'].values() == (12,))
            self.assertEqual(app.evaluation.results[node.id].outputs['O'].values()[0].xyz, (50, 60, 70))
            self.assertEqual(self.window.scene.get(source.id).name, 'Source circle')
            app.graph.delete_node(node)
            self.app.processEvents()
            self.assertIsNotNone(self.window.scene.get(source.id))
        finally:
            app.point_service.stop()
            app.graph.undo_stack().setClean()
            app.close()
            app.deleteLater()
            self.app.processEvents()
