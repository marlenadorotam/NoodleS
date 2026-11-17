"""Real native 3D primitives, common publication and asynchronous references in private scenes."""
import copy
from dataclasses import replace
import math
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from noodles.backend.solids import SOLID_SPECS, evaluate_solid, solid_object_from_outputs, solid_from_wire
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.primitive_shapes import materialize
from noodles.bridge import BridgeRemoteError
import test_curve_native as curve_fixture
from test_solids import state


class NativeSolidTests(unittest.TestCase):
    setUpClass = classmethod(curve_fixture.NativeCurveTests.setUpClass.__func__)
    setUp = curve_fixture.NativeCurveTests.setUp
    tearDown = curve_fixture.NativeCurveTests.tearDown
    call = curve_fixture.NativeCurveTests.call
    wait_for = curve_fixture.NativeCurveTests.wait_for
    publish = curve_fixture.NativeCurveTests.publish

    def model(self, operation, inputs=None, parameters=None):
        parameters = parameters or state(operation)
        output = evaluate_solid(operation, parameters, inputs or {})
        return solid_object_from_outputs(parameters, output).to_wire()

    def reference(self, method, parameters):
        response = self.call(method, parameters)
        if 'job_id' not in response:
            return response
        self.wait_for(lambda: self.bridge.points.jobs[response['job_id']]['state'] != 'preparing')
        result = self.call('geometry.job', response)
        if result['state'] != 'complete':
            raise ValueError(result.get('error', result['state']))
        return result

    def test_grid_tori_publish_one_mesh_with_worker_prepared_bounds(self):
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from noodles.backend.grids import evaluate_grid, normalize_grid_state

        grid = evaluate_grid('grid_rectangle', normalize_grid_state('grid_rectangle', {}),
                             {'Ex': 3, 'Ey': 2, 'Sx': 20, 'Sy': 20})
        request = self.call('geometry.prepare', {
            'model': self.model('torus', {'R': 5, 'r': 2, 'O': grid['P']}),
            'name': 'Grid tori',
        })
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        reply = self.call('geometry.job', request)
        self.assertEqual(reply['state'], 'complete', reply)
        obj, = self.window.scene.all()
        self.assertEqual(obj.id, reply['object_id'])
        self.assertTrue(obj.mesh_ready)
        self.assertIs(obj._bounds[0], obj.shape)
        explorer = TopExp_Explorer(obj.shape, TopAbs_SOLID)
        count = 0
        while explorer.More():
            count += 1
            explorer.Next()
        self.assertEqual(count, 12)

    def test_ungroup_leaves_each_box_as_a_whole_brep_solid(self):
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.BRepCheck import BRepCheck_Analyzer

        model = self.model('box', {'Z': [1, 2]})
        self.publish(model)
        completed = self.reference('geometry.ungroup', {k: model[k] for k in ('project_uuid', 'node_uuid')})
        self.assertEqual(completed['ungrouped'], 2)
        self.assertEqual([obj.shape.ShapeType() for obj in self.window.scene.all()], [TopAbs_SOLID] * 2)
        self.assertTrue(all(BRepCheck_Analyzer(obj.shape).IsValid() for obj in self.window.scene.all()))

    def test_solid_display_reuses_unchanged_parts_and_preserves_native_indices(self):
        import numpy as np
        from OCP.BRepCheck import BRepCheck_Analyzer
        from serpentine3d.core import tessellate
        from noodles.backend.curves import PlaneValue
        from noodles.backend.solid_display import SolidDisplayCache

        first = evaluate_solid('cylinder', state('cylinder'), {'H': 8})['G'].values()[0]
        second = replace(first, key='second', frame=PlaneValue((1e6, 0., 0.)), dimensions=(3., 9.))
        third = replace(second, key='third')
        values = (first, second, third)
        cache = SolidDisplayCache()
        shape, mesh, bounds = cache.prepare(values, lambda: True)
        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
        self.assertTrue(mesh.far)
        np.testing.assert_allclose(bounds, self.geo.bbox(shape), atol=1e-7)
        native = tessellate.tessellate(self.geo.make_compound([materialize(v) for v in values]))
        np.testing.assert_array_equal(mesh.face_of_triangle, native.face_of_triangle)
        np.testing.assert_array_equal(mesh.edge_of_segment, native.edge_of_segment)
        np.testing.assert_allclose(mesh.edge_segments, native.edge_segments, atol=.04, rtol=0.)
        self.assertEqual(len(cache.meshes), 2)

        with patch.object(tessellate, 'tessellate', wraps=tessellate.tessellate) as prepare_mesh:
            cache.prepare((replace(first, dimensions=(3., 7.)), second, third), lambda: True)
        self.assertEqual(prepare_mesh.call_count, 1)

    def test_real_slider_drives_solid_and_shell_height_and_preserves_manual_scene_edits(self):
        from Qt import QtCore, QtWidgets
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        scene = self.window.scene
        native = []
        layer = scene.layers.create('Reference cylinders')
        for index, solid in enumerate((True, False)):
            value = evaluate_solid('cylinder', state('cylinder'),
                                   {'H': 8, 'R': 3 + index, 'S': solid})['G'].values()[0]
            shape = materialize(value)
            obj = scene.add(shape, name='User cylinder ' + str(index))
            scene.update(obj.id, layer_id=layer.id, color=None)
            native.append(obj.id)
        editor = MainWindow()
        editor.point_service.client = self.client
        slider = editor.add_node('NoodleS.Inputs.SliderNode')
        slider.set_property('value', 8)
        node = editor.add_node('NoodleS.Geometry.CylinderNode')
        node.set_property('mode', 'reference')
        slider.outputs()['Number'].connect_to(node.inputs()['H'])
        slider.set_pos(-280, 0)
        node.set_pos(180, 0)
        editor.show()
        editor.graph.center_on([slider, node])
        editor.point_service.start()
        try:
            self.window.selection.set(native)
            self.app.processEvents()
            QTest.mouseClick(editor.properties.curve_properties.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(node.get_property('references')) == 2)
            self.wait_for(lambda: node.id in editor.point_service.completed_geometry_drives)
            original = [scene.get(oid) for oid in native]

            def reported_heights():
                result = editor.evaluation.results.get(node.id)
                return result.outputs['H'].values() if result and not result.error else ()

            # An independent native change must update the graph and leave the
            # unchanged slider command alone.
            records = node.get_property('references')
            first = solid_from_wire(records[0]['recipe'])
            edited = replace(first, dimensions=(6, 9))
            scene.replace_shape(native[0], self.geo.translate(materialize(edited), (2, 3, 4)))
            self.wait_for(lambda: reported_heights() == (9, 8))
            QTest.qWait(100)
            self.assertEqual(reported_heights(), (9, 8))
            self.assertEqual(slider.get_property('value'), 8)
            editor.point_service.stop()
            editor.point_service.start()
            QTest.qWait(200)
            self.assertEqual(reported_heights(), (9, 8))

            viewer = editor.graph.viewer()
            proxy = slider.get_widget('value')
            control = proxy.slider
            option = QtWidgets.QStyleOptionSlider()
            control.initStyleOption(option)
            handle = control.style().subControlRect(QtWidgets.QStyle.CC_Slider, option,
                                                    QtWidgets.QStyle.SC_SliderHandle, control)
            pos = viewer.mapFromScene(proxy.mapToScene(QtCore.QPointF(control.mapTo(proxy.widget(), handle.center()))))
            self.window.processor.busy = True
            QTest.mousePress(viewer.viewport(), QtCore.Qt.LeftButton, pos=pos)
            self.assertTrue(control.isSliderDown())
            end = pos + QtCore.QPoint(34, 0)
            QTest.mouseMove(viewer.viewport(), end)
            QTest.mouseRelease(viewer.viewport(), QtCore.Qt.LeftButton, pos=end)
            height = slider.get_property('value')
            self.assertGreater(height, 9)
            QTest.qWait(80)
            self.assertEqual(reported_heights(), (9, 8))
            self.window.processor.busy = False
            self.wait_for(lambda: reported_heights() == (height, height))
            self.assertIn(str(height), editor.properties.curve_properties.previews['H'].text())

            self.assertEqual(list(scene.objects), native)
            records = node.get_property('references')
            values = [solid_from_wire(r['recipe']) for r in records]
            self.assertEqual([v.solid for v in values], [True, False])
            self.assertEqual(values[0].frame.origin, (2, 3, 4))
            self.assertEqual([v.dimensions[0] for v in values], [6, 4])
            for previous, oid in zip(original, native):
                current = scene.get(oid)
                self.assertEqual((current.name, current.layer_id, current.color, current.user_text),
                                 (previous.name, previous.layer_id, previous.color, previous.user_text))
                self.assertTrue(current.mesh_ready)
            editor.graph.undo_stack().undo()
            self.wait_for(lambda: reported_heights() == (8, 8))
        finally:
            self.window.processor.busy = False
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_cancelled_height_job_and_invalid_second_source_never_change_the_first(self):
        from noodles.backend.solid_native import inspect_solid

        scene = self.window.scene
        value = evaluate_solid('cylinder', state('cylinder'), {'H': 8})['G'].values()[0]
        first, second = (scene.add(materialize(value)) for _ in range(2))
        self.window.selection.set([first.id, second.id])
        params = state('cylinder', mode='reference')
        refs = self.reference('geometry.capture', params)['references']
        drive = {**params, 'drive': {'updates': [{'key': ref['key'], 'values': {'H': 15}} for ref in refs]}}
        started, release = threading.Event(), threading.Event()

        def blocked(*args):
            started.set()
            if not release.wait(5):
                raise RuntimeError('Test gate timed out.')
            return inspect_solid(*args)

        before = scene.get(first.id)._shape
        with patch('noodles.backend.solid_native.inspect_solid', side_effect=blocked):
            request = self.call('geometry.drive', drive)
            try:
                self.wait_for(started.is_set)
                cancelled = self.call('geometry.drive', {**params, 'drive': {'updates': []}})
                self.assertEqual(cancelled['state'], 'complete')
            finally:
                release.set()
            self.assertEqual(self.call('geometry.job', request)['state'], 'superseded')
        self.assertIs(scene.get(first.id)._shape, before)

        scene.replace_shape(second.id, self.geo.make_box((0, 0, 0), 2, 2, 2))
        request = self.call('geometry.drive', drive)
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        self.assertEqual(self.call('geometry.job', request)['state'], 'error')
        self.assertIs(scene.get(first.id)._shape, before)

    def test_every_primitive_one_native_compound_display_mesh_and_correct_volume(self):
        from OCP.TopAbs import TopAbs_COMPOUND
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps
        from OCP.BRepCheck import BRepCheck_Analyzer
        for operation in SOLID_SPECS:
            with self.subTest(operation=operation):
                owner = self.publish(self.model(operation))
                self.assertEqual(owner.shape.ShapeType(), TopAbs_COMPOUND)
                self.assertEqual(len(self.window.scene.objects), 1)
                self.assertTrue(owner.mesh_ready)
                self.assertTrue(BRepCheck_Analyzer(owner.shape).IsValid())
                if operation != 'paraboloid':
                    props = GProp_GProps()
                    if operation == 'ellipsoid':
                        BRepGProp.VolumeProperties_s(owner.shape, props, 1e-9)
                    else:
                        BRepGProp.VolumeProperties_s(owner.shape, props)
                    expected = evaluate_solid(operation, state(operation), {})['V'].values()[0]
                    self.assertAlmostEqual(abs(props.Mass()), expected, delta=expected*1e-6)

    def test_cylinder_and_cone_modes_retain_owner_and_native_attributes(self):
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        for operation in ('cylinder', 'cone', 'truncated_cone'):
            owner = self.publish(self.model(operation))
            layer = self.window.scene.layers.create(operation+' layer')
            self.window.scene.update(owner.id, name='My '+operation, layer_id=layer.id, color=None)
            for solid in (False, True):
                inputs = {'S': solid}
                if operation == 'truncated_cone':
                    inputs['H'] = -20
                changed = self.publish(self.model(operation, inputs))
                self.assertEqual(changed.id, owner.id)
                self.assertEqual(changed.name, 'My '+operation)
                self.assertEqual(changed.layer_id, layer.id)
                self.assertIsNone(changed.color)
                explorer = TopExp_Explorer(changed.shape, TopAbs_SOLID)
                self.assertEqual(explorer.More(), solid)
                self.assertEqual(len(self.geo.faces_of(changed.shape)), (2 if operation == 'cone' else 3) if solid else 1)
                if operation == 'truncated_cone':
                    low, high = self.geo.bbox(changed.shape)
                    self.assertAlmostEqual(low[2], -20., places=5)
                    self.assertAlmostEqual(high[2], 0., places=5)

    def test_two_hundred_boxes_coalesce_into_one_owner_and_cache_199_parts(self):
        heights = list(range(1, 201))
        owner = self.publish(self.model('box', {'Z': heights}))
        self.assertEqual(len(self.window.scene.objects), 1)
        heights[70] += .5
        with patch('noodles.backend.primitive_shapes.materialize', wraps=materialize) as build:
            changed = self.publish(self.model('box', {'Z': heights}))
            self.assertEqual(build.call_count, 1)
        self.assertEqual(changed.id, owner.id)

    def test_topology_only_changes_keep_shape_mesh_and_empty_results_remove_owner(self):
        owner = self.publish(self.model('box', {'Z': [1, 2, 3]}))
        shape, mesh = owner._shape, owner._mesh
        changed = self.publish(self.model('box', {'Z': [1, 2, 3]}, state('box', tree_modes={'Z': 'graft'})))
        self.assertIs(changed._shape, shape)
        self.assertIs(changed._mesh, mesh)
        request = self.call('geometry.prepare', {'model': self.model('box', {'Z': []})})
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        self.assertEqual(self.call('geometry.job', request)['state'], 'complete')
        self.assertFalse(self.window.scene.objects)

    def test_real_window_capture_and_move_reference_without_deleting_the_source(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow
        app = MainWindow()
        node = app.add_node('NoodleS.Geometry.BoxNode')
        node.set_property('mode', 'reference')
        app.point_service.client = self.client
        app.point_service.start()
        app.show()
        try:
            value = evaluate_solid('box', state('box'), {})['G'].values()[0]
            obj = self.window.scene.add(materialize(value), name='User box')
            self.window.selection.set([obj.id])
            self.app.processEvents()
            app._refresh_inspector()
            QTest.mouseClick(app.properties.curve_properties.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(node.get_property('references')) == 1)
            before = node.get_property('references')[0]['recipe']['plane']['origin']
            self.window.scene.replace_shape(obj.id, self.geo.translate(obj.shape, (3, 4, 5)))
            app.point_service.refresh()
            self.wait_for(lambda: node.get_property('references')[0]['recipe']['plane']['origin'] != before)
            self.assertEqual(len(self.window.scene.objects), 1)
            app.graph.delete_node(node)
            self.app.processEvents()
            self.assertIsNotNone(self.window.scene.get(obj.id))
        finally:
            app.graph.undo_stack().setClean()
            app.close()
            app.deleteLater()
            self.app.processEvents()

    def test_every_reference_moves_rotates_scales_and_reads_on_worker(self):
        from noodles.backend.solid_native import inspect_solid
        worker_ids = []
        def inspect(*args):
            worker_ids.append(threading.get_ident())
            return inspect_solid(*args)
        for operation in SOLID_SPECS:
            modes = ((True, False) if operation in ('cylinder', 'cone', 'truncated_cone', 'pyramid', 'ellipsoid')
                     else (operation != 'paraboloid',))
            for solid in modes:
                with self.subTest(operation=operation, solid=solid):
                    inputs = {'S': solid} if len(modes) == 2 else {}
                    value = evaluate_solid(operation, state(operation), inputs)['G'].values()[0]
                    obj = self.window.scene.add(materialize(value), name='Editable '+operation)
                    self.window.selection.set([obj.id])
                    params = state(operation, mode='reference')
                    with patch('noodles.backend.solid_native.inspect_solid', side_effect=inspect):
                        refs = self.reference('geometry.capture', params)['references']
                    previous = refs[0]
                    moved = self.geo.translate(obj.shape, (3, 4, 5))
                    moved = self.geo.rotate(moved, (0, 0, 0), (1, 0, 0), .4)
                    moved = self.geo.scale(moved, (0, 0, 0), 2)
                    self.window.scene.replace_shape(obj.id, moved)
                    current = self.reference('geometry.read', {**params, 'references': refs})['references'][0]
                    self.assertEqual(current['key'], previous['key'])
                    self.assertEqual(current['id'], obj.id)
                    self.assertNotEqual(current['recipe']['plane']['origin'], previous['recipe']['plane']['origin'])
                    rebuilt = materialize(solid_from_wire(current['recipe']))
                    old_bounds, new_bounds = self.geo.bbox(moved), self.geo.bbox(rebuilt)
                    for old_point, new_point in zip(old_bounds, new_bounds):
                        for a, b in zip(old_point, new_point):
                            self.assertAlmostEqual(a, b, delta=1e-4)
                    self.window.scene.remove(obj.id)
        self.assertTrue(worker_ids)
        self.assertNotIn(threading.get_ident(), worker_ids)

    def test_ellipsoid_references_native_scaled_sphere_and_rejects_trimmed_face(self):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
        from serpentine3d.commands.base import CommandContext, CommandProcessor
        from serpentine3d.commands import transform
        from noodles.backend.ellipsoid_native import inspect_ellipsoid

        scene = self.window.scene
        center = (3., -2., 7.)
        obj = scene.add(self.geo.make_sphere(center, 2.))
        self.window.selection.set([obj.id])
        processor = CommandProcessor(CommandContext(scene, self.window.selection, self.window.history))
        processor.run('scalenu')
        for text in ('3,-2,7', '3', '1', '2'):
            processor.provide_text(text)
        self.assertFalse(processor.busy)
        obj = scene.get(obj.id)
        self.window.selection.set([obj.id])
        params = state('ellipsoid', mode='reference')
        record, = self.reference('geometry.capture', params)['references']
        value = solid_from_wire(record['recipe'])
        for actual, expected in zip(value.dimensions, (6., 2., 4.)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(value.frame.origin, center):
            self.assertAlmostEqual(actual, expected)

        skewed = self.geo.rotate(obj.shape, center, (1, 1, 0), 30)
        skewed = self.geo.scale_along_axis(skewed, center, (0, 1, 0), 2)
        fitted = inspect_ellipsoid(skewed, 'skewed')
        for a, b in zip(self.geo.bbox(materialize(fitted)), self.geo.bbox(skewed)):
            for actual, expected in zip(a, b):
                self.assertAlmostEqual(actual, expected, places=5)
        partial = BRepPrimAPI_MakeSphere(5., 0., math.pi/2).Solid()
        with self.assertRaisesRegex(ValueError, 'complete sphere or ellipsoid'):
            inspect_ellipsoid(partial, 'partial')

    def test_capture_atomicity_and_binding_reopen_and_duplicates(self):
        from serpentine3d.fileio.native import save_scene, load_scene
        def source(operation):
            value = evaluate_solid(operation, state(operation), {})['G'].values()[0]
            return self.window.scene.add(materialize(value))
        box, sphere = source('box'), source('sphere')
        self.window.selection.set([box.id, sphere.id])
        params = state('box', mode='reference')
        before = copy.deepcopy(box.user_text)
        with self.assertRaises((BridgeRemoteError, ValueError)):
            self.reference('geometry.capture', params)
        self.assertEqual(self.window.scene.get(box.id).user_text, before)
        self.window.selection.set([box.id])
        refs = self.reference('geometry.capture', params)['references']
        path = Path(self.folder.name)/'solid.serp'
        save_scene(self.window.scene, str(path))
        restored = self.Scene()
        load_scene(restored, str(path))
        self.window.scene = restored
        current = self.reference('geometry.read', {**params, 'references': refs})['references'][0]
        self.assertNotEqual(current['id'], box.id)
        self.assertEqual(current['key'], refs[0]['key'])
        obj = restored.get(current['id'])
        clone = restored.add(obj.shape)
        restored.update(clone.id, user_text=copy.deepcopy(obj.user_text))
        with self.assertRaises((BridgeRemoteError, ValueError)):
            self.reference('geometry.read', {**params, 'references': refs})

    def test_changed_source_during_read_is_superseded_without_overwriting_scene(self):
        from noodles.backend.solid_native import inspect_solid
        value = evaluate_solid('box', state('box'), {})['G'].values()[0]
        obj = self.window.scene.add(materialize(value))
        self.window.selection.set([obj.id])
        params = state('box', mode='reference')
        refs = self.reference('geometry.capture', params)['references']
        started, release = threading.Event(), threading.Event()
        def slow_inspect(*args):
            started.set()
            if not release.wait(3):
                raise RuntimeError('Test inspection gate timed out.')
            return inspect_solid(*args)
        with patch('noodles.backend.solid_native.inspect_solid', side_effect=slow_inspect):
            request = self.call('geometry.read', {**params, 'references': refs})
            self.wait_for(started.is_set)
            changed = self.geo.translate(obj.shape, (7, 8, 9))
            self.window.scene.replace_shape(obj.id, changed)
            release.set()
            self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        result = self.call('geometry.job', request)
        self.assertEqual(result['state'], 'superseded')
        self.assertNotIn('references', result)
        self.assertIs(self.window.scene.get(obj.id)._shape, changed)
        current = self.reference('geometry.read', {**params, 'references': refs})['references'][0]
        self.assertNotEqual(current['recipe']['plane']['origin'], refs[0]['recipe']['plane']['origin'])

    def test_rational_revolution_is_not_misreported_as_a_quadratic_paraboloid(self):
        from OCP.gp import gp_Pnt, gp_Ax1, gp_Dir
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.TColStd import TColStd_Array1OfReal
        from OCP.Geom import Geom_BezierCurve, Geom_SurfaceOfRevolution
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        import math
        poles = TColgp_Array1OfPnt(1, 3)
        weights = TColStd_Array1OfReal(1, 3)
        for i, (xyz, weight) in enumerate(zip(((0, 0, 0), (5, 0, 0), (10, 0, 20)), (1, 2, 1)), 1):
            poles.SetValue(i, gp_Pnt(*xyz))
            weights.SetValue(i, weight)
        surface = Geom_SurfaceOfRevolution(Geom_BezierCurve(poles, weights), gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)))
        obj = self.window.scene.add(BRepBuilderAPI_MakeFace(surface, 0., 2*math.pi, 0., 1., 1e-7).Face())
        self.window.selection.set([obj.id])
        metadata = copy.deepcopy(obj.user_text)
        with self.assertRaises((ValueError, BridgeRemoteError)):
            self.reference('geometry.capture', state('paraboloid', mode='reference'))
        self.assertEqual(self.window.scene.get(obj.id).user_text, metadata)
