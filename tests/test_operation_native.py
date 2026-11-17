"""True OCC operation chains, common owner/cache/lifecycle and native commands."""
import copy
import math
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_curve_native as fixture
from test_operations import state,inputs,sections
from noodles.backend.operations import evaluate_operation,operation_object_from_outputs
from noodles.backend.curves import circle,line,polyline,PlaneValue
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.scene_curves import materialize
from noodles.backend.operation_native import extrude_shape,loft_shape,register_commands


class NativeOperationTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp=fixture.NativeCurveTests.setUp
    tearDown=fixture.NativeCurveTests.tearDown
    call=fixture.NativeCurveTests.call
    def wait_for(self,condition,timeout=30):
        return fixture.NativeCurveTests.wait_for(self,condition,timeout)
    publish=fixture.NativeCurveTests.publish

    def model(self,op,data=None,parameters=None):
        parameters=parameters or state(op)
        out=evaluate_operation(op,parameters,inputs(op) if data is None else data)
        return operation_object_from_outputs(parameters,out).to_wire()

    def test_fillet_parametric_polyline_tree_and_show_parent(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow
        from noodles.backend.fillet_curves import fillet_shape

        a = polyline('a', ((-10, 5, 0), (-10, 0, 0), (0, 0, 0)))
        b = polyline('b', ((0, 0, 0), (0, 10, 0), (5, 10, 0)))
        shape = fillet_shape(materialize(a), materialize(b), 1., (0, 0, 0))
        self.assertEqual(len(self.geo.edges_of(shape)), 5)
        op = 'fillet_parametric'
        model = self.model(op, {**inputs(op), 'R': DataTree((Branch((3,), (1.,)), Branch((7,), (2.,))))})
        owner = self.publish(model)
        self.assertEqual([branch['path'] for branch in model['branches']], [[3], [7]])
        self.assertEqual(len(self.geo.edges_of(owner.shape)), 6)
        self.window.scene.remove(owner.id)

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            first, second, near, fillet = self._fillet_graph(gui, 'FilletParametricNode')
            checkbox = gui.properties.curve_properties.show_parent
            self.wait_for(lambda: checkbox.isVisible() and len(self.window.scene.objects) == 4)
            QTest.mouseClick(checkbox, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, checkbox.height() // 2))
            def source(node):
                state = node.point_state() if node is near else node.curve_state()
                return self.bridge.points.owner((gui.project_uuid, state['node_uuid'], 0))
            self.wait_for(lambda: not source(first).visible and not source(second).visible)
            self.assertTrue(source(near).visible)
            self.assertEqual(len(self.geo.edges_of(source(fillet).shape)), 3)
            gui.graph.undo_stack().undo()
            self.wait_for(lambda: source(first).visible and source(second).visible)
            self.assertEqual(len(self.window.scene.objects), 4)
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    @staticmethod
    def _fillet_graph(gui, kind):
        first = gui.add_node('NoodleS.Geometry.LineNode')
        second = gui.add_node('NoodleS.Geometry.LineNode')
        first.set_property('parameters', {'A': [-10, 0, 0], 'B': [0, 0, 0]})
        second.set_property('parameters', {'A': [0, 0, 0], 'B': [0, 10, 0]})
        near = gui.add_node('NoodleS.Geometry.PointNode')
        fillet = gui.add_node('NoodleS.Geometry.' + kind)
        first.outputs()['C'].connect_to(fillet.inputs()['A'])
        second.outputs()['C'].connect_to(fillet.inputs()['B'])
        near.outputs()['P'].connect_to(fillet.inputs()['N'])
        return first, second, near, fillet

    def test_native_fillet_ui_consumes_once_and_updates_saved_originals_after_reopen(self):
        from pathlib import Path
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from serpentine3d.fileio.native import load_scene, save_scene
        from noodles.window import MainWindow

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            first, _, _, fillet = self._fillet_graph(gui, 'FilletNode')
            panel = gui.properties.curve_properties
            button = panel.boolean_apply
            self.wait_for(lambda: button.isEnabled() and len(self.window.scene.objects) == 3
                          and not gui._pending and not gui._graph_worker.running)
            self.assertFalse(panel.show_parent.isVisible())
            self.assertEqual(button.text(), 'Apply Fillet')
            identity = gui.project_uuid, first.curve_state()['node_uuid'], 0
            source = self.bridge.points.owner(identity)
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.wait_for(lambda: button.text() == 'Update Fillet'
                          and gui.evaluation.results[fillet.id].outputs['R'].values() == (1.,))
            self.assertEqual(len(self.window.scene.objects), 2)
            self.assertEqual(len(self.geo.edges_of(self.window.scene.get(source.id).shape)), 3)
            path = str(Path(self.folder.name) / 'fillet.serp')
            save_scene(self.window.scene, path)
            self.window.scene = self.Scene()
            self.window.history = self.History(self.window.scene)
            load_scene(self.window.scene, path)
            gui.point_service.refresh()
            self.wait_for(lambda: fillet.boolean_records and fillet.boolean_records[0]['id'] != source.id)
            oid = fillet.boolean_records[0]['id']
            fillet.set_property('parameters', {'R': 2})
            self.wait_for(lambda: button.isEnabled() and not gui._pending and not gui._graph_worker.running)
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.wait_for(lambda: gui.evaluation.results[fillet.id].outputs['R'].values() == (2.,))
            self.assertEqual(fillet.boolean_records[0]['id'], oid)
            self.assertEqual(len(self.window.scene.objects), 2)
            self.window.history.undo()
            self.wait_for(lambda: gui.evaluation.results[fillet.id].outputs['R'].values() == (1.,))
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    def test_fillet_edge_capture_multiple_parts_and_rejects_ambiguous_points(self):
        from uuid import uuid4
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from noodles.backend.fillet_edges import target_key
        from noodles.backend.grid_reference_native import children
        from noodles.backend.moves import Binding
        from noodles.backend.point import PointValue
        from noodles.backend.solids import SolidValue, normalize_solid_state, solid_object_from_outputs

        op = 'fillet_edge'
        boxes = (inputs(op)['G'], SolidValue('other', 'box', PlaneValue(origin=(30, 0, 0)), (10, 10, 10)))
        tree = DataTree((Branch((4,), (boxes[0],)), Branch((7,), (boxes[1],))))
        source_state = normalize_solid_state('box', {'project_uuid': state(op)['project_uuid'], 'node_uuid': str(uuid4())})
        source_model = solid_object_from_outputs(source_state, {'G': tree}).to_wire()
        source = self.publish(source_model)
        source_shape = source._shape
        native_edges = self.geo.edges_of(source_shape)
        selected_edges = [self.geo.edges_of(solid)[0] for solid in children(source_shape)]
        indices = [next(i for i, edge in enumerate(native_edges) if edge.IsSame(pick)) for pick in selected_edges]
        self.window.selection.set_subobjects([(source.id, 'edge', i) for i in indices])
        targets = [{'project_uuid': source_model['project_uuid'], 'node_uuid': source_model['node_uuid'],
                    'reference': False, 'key': box.key} for box in boxes]
        capture = self.call('geometry.capture', {**state(op), 'fillet_targets': targets})
        self.wait_for(lambda: self.bridge.points.jobs[capture['job_id']]['state'] != 'preparing')
        data = self.call('geometry.job', capture)
        self.assertEqual(data['state'], 'complete', data)
        self.assertEqual(set(data['measurements']), {target_key(target) for target in targets})
        params = state(op, parameters={'fillet_mode': 'selected', 'fillet_selection': data['measurements']})
        bindings = {'G': {box.key: Binding('source', box.key, project=source_model['project_uuid'],
                                         source_uuid=source_model['node_uuid']) for box in boxes}}
        result = evaluate_operation(op, params, {'G': tree, 'R': 1}, bindings)
        self.assertEqual([b.path for b in result['G'].branches], [(4,), (7,)])
        model = operation_object_from_outputs(params, result).to_wire()
        owner = self.publish(model)
        self.assertEqual(len(tuple(children(owner.shape))), 2)
        self.assertEqual(len(self.window.scene.objects), 2)
        self.assertIs(self.window.scene.get(source.id)._shape, source_shape)
        self.assertTrue(all(len(self.geo.faces_of(s)) == 7 for s in children(owner.shape)))
        saved_recipe = result['G'].values()[0]
        from noodles.backend.fillet_native import fillet_shape
        shifted = self.geo.translate(next(children(source_shape)), (10, 20, 30))
        shifted_result = fillet_shape(shifted, 1, saved=saved_recipe.fillet_selection)
        self.assertEqual(len(self.geo.faces_of(shifted_result)), 7)
        all_edges = self.publish(self.model(op, {'G': boxes[0]}))
        self.assertGreater(len(self.geo.faces_of(all_edges.shape)), 7)
        curve = BRepAdaptor_Curve(selected_edges[0])
        mid = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
        point = PointValue('edge-midpoint', self.geo.pnt_tuple(mid))
        live = evaluate_operation(op, state(op, parameters={'fillet_mode': 'selected'}), {'G': boxes[0], 'E': point})
        self.assertEqual(len(self.geo.faces_of(materialize(live['G'].values()[0]))), 7)
        corner = PointValue('corner', self.geo.pnt_tuple(curve.Value(curve.FirstParameter())))
        bad = self.model(op, {'G': boxes[0], 'E': corner}, state(op, parameters={'fillet_mode': 'selected'}))
        request = self.call('geometry.prepare', {'model': bad})
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        failure = self.call('geometry.job', request)
        self.assertEqual(failure['state'], 'error')
        self.assertIn('equally near', failure['error'])
        self.assertIs(self.window.scene.get(all_edges.id)._shape, all_edges._shape)

    def test_fillet_edge_set_edges_in_properties_for_a_referenced_solid(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        original = self.window.scene.add(materialize(inputs('fillet_edge')['G']), name='CAD Box')
        try:
            box = gui.add_node('NoodleS.Geometry.BoxNode')
            box.set_property('mode', 'reference')
            self.window.selection.set([original.id])
            panel = gui.properties.curve_properties
            self.wait_for(panel.capture.isVisible)
            QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: box.curve_state()['references'])
            fillet = gui.add_node('NoodleS.Geometry.FilletEdgeNode')
            box.outputs()['G'].connect_to(fillet.inputs()['G'])
            self.wait_for(lambda: panel.fillet_buttons['all'].isVisible() and not gui._pending)
            QTest.mouseClick(panel.fillet_buttons['selected'], QtCore.Qt.LeftButton)
            self.wait_for(lambda: panel.fillet_capture.isVisible() and not gui._pending and not gui._graph_worker.running)
            self.window.selection.set_subobjects([(original.id, 'edge', 0)])
            QTest.mouseClick(panel.fillet_capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: fillet.curve_state()['parameters']['fillet_selection'])
            identity = (gui.project_uuid, fillet.curve_state()['node_uuid'], 0)
            self.wait_for(lambda: (obj := self.bridge.points.owner(identity)) is not None
                          and len(self.geo.faces_of(obj.shape)) == 7)
            obj = self.bridge.points.owner(identity)
            self.assertEqual(len(self.window.scene.objects), 2)
            self.assertIs(self.window.scene.get(original.id)._shape, original._shape)
            fillet.set_property('parameters', {**fillet.curve_state()['parameters'], 'R': 0.5})
            self.wait_for(lambda: self.bridge.points.owner(identity)._shape is not obj._shape)
            self.assertEqual(self.bridge.points.owner(identity).id, obj.id)
            gui.graph.undo_stack().undo()
            gui.graph.undo_stack().undo()
            self.assertFalse(fillet.curve_state()['parameters']['fillet_selection'])
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    def test_parametric_booleans_preserve_native_operands_and_classify_result(self):
        from noodles.backend.grid_reference_native import children
        from noodles.backend.solids import SolidValue

        a, b = inputs('boolean_union_parametric')['O']
        source = self.window.scene.add(materialize(a), name='Source')
        before = source._shape
        for operation, volume in (('union', 1500), ('difference', 500), ('intersection', 500)):
            op = f'boolean_{operation}_parametric'
            owner = self.publish(self.model(op))
            result, = children(owner.shape)
            self.assertEqual(self.geo.shape_kind(result), 'solid')
            self.assertAlmostEqual(self.geo.volume(result), volume)
            self.assertIs(self.window.scene.get(source.id)._shape, before)

        disjoint = SolidValue('remote', 'box', PlaneValue(origin=(30, 0, 0)), (10, 10, 10))
        owner = self.publish(self.model('boolean_union_parametric', {'O': [a, disjoint]}))
        result, = children(owner.shape)
        self.assertEqual(len(self.geo.loose_pieces(result)), 2)
        self.assertAlmostEqual(self.geo.volume(result), 2000)

        op = 'boolean_intersection_parametric'
        last_valid = self.publish(self.model(op))
        shape = last_valid._shape
        request = self.call('geometry.prepare', {
            'model': self.model(op, {'O': [a, disjoint]}), 'name': 'Primitive',
        })
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        failure = self.call('geometry.job', request)
        self.assertEqual(failure['state'], 'error')
        self.assertIn('no solid volume', failure['error'])
        self.assertIs(self.window.scene.get(last_valid.id)._shape, shape)

    def test_show_parent_tracks_shared_sources_and_restores_original_visibility(self):
        import uuid
        from pathlib import Path
        from serpentine3d.fileio.native import load_scene, save_scene
        from noodles.backend.solids import evaluate_solid, normalize_solid_state, solid_object_from_outputs
        from test_curves import PROJECT

        source_state = normalize_solid_state('box', {
            'project_uuid': PROJECT, 'node_uuid': str(uuid.uuid4()),
        })
        outputs = evaluate_solid('box', source_state, {})
        source_wire = solid_object_from_outputs(source_state, outputs).to_wire()
        native = self.window.scene.add(materialize(outputs['G'].values()[0]), name='Hidden CAD solid')
        ref_state = normalize_solid_state('box', {
            'mode': 'reference', 'project_uuid': PROJECT, 'node_uuid': str(uuid.uuid4()),
        })
        self.window.selection.set([native.id])
        capture = self.call('geometry.capture', ref_state)
        self.wait_for(lambda: self.bridge.points.jobs[capture['job_id']]['state'] != 'preparing')
        reference, = self.call('geometry.job', capture)['references']
        self.window.scene.update(native.id, visible=False)
        claims = [
            ['owner', PROJECT, source_wire['node_uuid'], ''],
            ['reference', PROJECT, ref_state['node_uuid'], reference['key']],
        ]
        union = self.model('boolean_union_parametric')
        intersection = self.model('boolean_intersection_parametric',
                                  parameters=state('boolean_intersection_parametric', node_uuid=str(uuid.uuid4())))

        def publish(model, hidden):
            request = self.call('geometry.prepare', {'model': model, 'hidden_parents': hidden})
            self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
            result = self.call('geometry.job', request)
            self.assertEqual(result['state'], 'complete', result)
            return self.window.scene.get(result['object_id'])

        first = publish(union, claims)
        publish(intersection, claims)
        source = self.publish(source_wire)
        self.assertFalse(self.window.scene.get(source.id).visible)
        self.assertIs(publish(union, [])._shape, first._shape)
        self.assertFalse(self.window.scene.get(source.id).visible)
        path = str(Path(self.folder.name) / 'show-parent.serp')
        save_scene(self.window.scene, path)
        self.window.scene = self.Scene()
        load_scene(self.window.scene, path)
        self.call('geometry.remove', intersection)
        scene = self.window.scene
        source = self.bridge.points.owner(self.bridge.points.identity(source_wire))
        self.assertTrue(source.visible)
        self.assertFalse(next(obj for obj in scene.all() if obj.name == native.name).visible)

    def test_extrude_open_curve_surface_and_capped_profile_solid(self):
        from OCP.TopAbs import TopAbs_COMPOUND
        profile=sections()[0]
        owner=self.publish(self.model('extrude',{'G':profile}))
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertEqual(owner.shape.ShapeType(),TopAbs_COMPOUND)
        self.assertTrue(owner.mesh_ready)
        self.assertAlmostEqual(self.geo.volume(owner.shape),math.pi*25*10,delta=1e-5)
        shell=self.publish(self.model('extrude',{'G':profile,'C':False}))
        self.assertEqual(owner.id,shell.id)
        self.assertEqual(len(self.geo.faces_of(shell.shape)),1)
        face=self.publish(self.model('extrude',{'G':line('p',(0,0,0),(5,0,0))}))
        self.assertEqual(len(self.geo.faces_of(face.shape)),1)
        self.assertAlmostEqual(self.geo.surface_area(face.shape),50,delta=1e-6)

    def test_revolve_full_partial_negative_and_axis_position(self):
        profile=inputs('revolve')['C']
        for angle in (360,90,-90):
            with self.subTest(angle=angle):
                owner=self.publish(self.model('revolve',{'C':profile,'D':angle}))
                self.assertAlmostEqual(self.geo.surface_area(owner.shape),5*10*abs(math.radians(angle)),delta=1e-5)
                low,high=self.geo.bbox(owner.shape)
                if angle==90:
                    self.assertGreaterEqual(low[1],-1e-5)
                elif angle==-90:
                    self.assertLessEqual(high[1],1e-5)
        axis=line('axis',(10,0,0),(10,0,20))
        owner=self.publish(self.model('revolve',{'C':profile,'A':axis}))
        low,high=self.geo.bbox(owner.shape)
        self.assertAlmostEqual((low[0]+high[0])/2,10,delta=1e-5)

    def test_loft_smooth_ruled_closed_and_branch_collection(self):
        for ruled in (0,1):
            owner=self.publish(self.model('loft',{'C':sections(),'T':ruled}))
            self.assertTrue(owner.mesh_ready)
            self.assertGreater(self.geo.surface_area(owner.shape),1)
        closed_sections=[circle('c'+str(i),(10*math.cos(a),10*math.sin(a),0),2,
            PlaneValue(axis_x=(0,0,1),normal=(-math.sin(a),math.cos(a),0))) for i,a in enumerate((0,2*math.pi/3,4*math.pi/3))]
        owner=self.publish(self.model('loft',{'C':closed_sections,'Cl':True,'T':1}))
        self.assertGreater(self.geo.surface_area(owner.shape),1)
        tree=DataTree((Branch((4,),tuple(sections())),Branch((7,),tuple(sections()))))
        owner=self.publish(self.model('loft',{'C':tree}))
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertTrue(owner.mesh_ready)

    def test_nested_surface_extrusion_and_profile_cache_shared_between_two_hundred_parts(self):
        base=evaluate_operation('extrude',state('extrude'),{'G':line('base',(0,0,0),(5,0,0)),
            'V':VectorValue((0,5,0))})['G'].values()[0]
        owner=self.publish(self.model('extrude',{'G':base,'V':VectorValue((0,0,5))}))
        self.assertAlmostEqual(self.geo.volume(owner.shape),125,delta=1e-6)
        profile=sections()[0]
        vectors=[VectorValue((0,0,i)) for i in range(1,201)]
        from noodles.backend.operation_native import materialize as operation_build
        threads=[]
        def build(value, resolve, topology_cache=None):
            threads.append(threading.get_ident())
            return operation_build(value, resolve, topology_cache)
        with patch('noodles.backend.operation_native.materialize',side_effect=build) as operations:
            owner=self.publish(self.model('extrude',{'G':profile,'V':vectors}))
            self.assertEqual(operations.call_count,200)
        self.assertTrue(all(t!=threading.get_ident() for t in threads))
        self.assertEqual(len(self.window.scene.objects),1)
        vectors[70]=VectorValue((0,0,71.5))
        with patch('noodles.backend.operation_native.materialize',wraps=operation_build) as operations:
            changed=self.publish(self.model('extrude',{'G':profile,'V':vectors}))
            self.assertEqual(operations.call_count,1)
        self.assertEqual(owner.id,changed.id)

    def test_native_classification_details_attributes_delete_undo_and_invalid_result_rollback(self):
        model=self.model('extrude')
        owner=self.publish(model)
        job=next(reversed(self.bridge.geometry.jobs.values()))
        key=model['branches'][0]['parts'][0]['key']
        self.assertEqual(job['curve_details'][key]['kind'],'solid')
        layer=self.window.scene.layers.create('Operation layer')
        self.window.scene.update(owner.id,name='My extrusion',color=None,layer_id=layer.id)
        shape,mesh=owner._shape,owner._mesh
        identity={k:model[k] for k in ('project_uuid','node_uuid')}
        self.call('geometry.remove',identity)
        restored=self.publish(model)
        self.assertEqual(restored.id,owner.id)
        self.assertIs(restored._shape,shape)
        self.assertIs(restored._mesh,mesh)
        self.assertEqual(restored.name,'My extrusion')
        self.assertIsNone(restored.color)
        self.assertEqual(restored.layer_id,layer.id)
        # A line swept along itself has zero area: reject before any scene commit.
        request=self.call('geometry.prepare',{'model':self.model('extrude',{
            'G':line('bad',(0,0,0),(0,0,5)),'V':VectorValue((0,0,10))})})
        self.wait_for(lambda:self.bridge.geometry.jobs[request['job_id']]['state']!='preparing')
        self.assertEqual(self.call('geometry.job',request)['state'],'error')
        self.assertIs(self.window.scene.get(restored.id)._shape,shape)

    def test_native_commands_use_factories_on_worker_without_replacing_builtins(self):
        from serpentine3d.commands import base,surfaces
        originals=[base.resolve(name) for name in ('extrude','revolve','loft')]
        self.window._noodles_bridge=self.bridge
        register_commands(self.ctx)
        self.assertEqual([base.resolve(name) for name in ('extrude','revolve','loft')],originals)
        native_curves=[self.window.scene.add(materialize(c)) for c in sections()]
        axis_curve=self.window.scene.add(materialize(inputs('revolve')['C']))
        cases=(('extrudevector',[[native_curves[0]],(0,0,0),(0,0,10),'Yes']),
               ('revolveparam',[[axis_curve],(0,0,0),(0,0,10),180.]),
               ('loftparam',[native_curves,'Ruled','No','Yes']))
        for name,values in cases:
            messages=[]
            context=SimpleNamespace(echo=messages.append)
            before=len(self.window.scene.objects)
            generator=base.resolve(name).fn(context)
            next(generator)
            for value in values:
                try:
                    generator.send(value)
                except StopIteration:
                    break
            else:
                self.fail('Native operation did not finish.')
            self.wait_for(lambda:any(m.startswith('Created ') for m in messages))
            self.assertEqual(len(self.window.scene.objects),before+1)
            self.assertFalse(base.resolve(name).mutates)

    def test_offset_fix_corrects_lines_and_collinear_wires_with_signed_distance(self):
        from noodles.backend.offset_native import offset_curve_shape

        cases = (self.geo.make_line((0, 0, 0), (10, 0, 0)),
                 self.geo.make_polyline([(0, 0, 0), (10, 0, 0)]),
                 self.geo.make_polyline([(0, 0, 0), (4, 0, 0), (10, 0, 0)]))
        for shape in cases:
            original = self.geo.sample_curve(shape, 3)
            for distance in (-2., 2.):
                result = offset_curve_shape(shape, distance)
                self.assertEqual(result.ShapeType(), shape.ShapeType())
                self.assertEqual(len(self.geo.edges_of(result)), len(self.geo.edges_of(shape)))
                self.assertEqual(self.geo.sample_curve(result, 3), [(x, y-distance, z) for x, y, z in original])
            self.assertEqual(self.geo.sample_curve(shape, 3), original)
        reversed_line = self.geo.make_line((10, 0, 0), (0, 0, 0))
        moved = offset_curve_shape(reversed_line, 2.)
        self.assertEqual(self.geo.sample_curve(moved, 3), [(10, 2, 0), (5, 2, 0), (0, 2, 0)])
        vertical = self.geo.make_line((0, 0, 0), (0, 0, 10))
        with self.assertRaisesRegex(ValueError, 'parallel'):
            offset_curve_shape(vertical, 2.)
        moved = offset_curve_shape(vertical, 2., (0, 1, 0))
        self.assertEqual(self.geo.sample_curve(moved, 3), [(-2, 0, 0), (-2, 0, 5), (-2, 0, 10)])
        bent = self.geo.make_polyline([(0, 0, 0), (4, 0, 0), (10, 3, 0)])
        expected = self.geo.offset_curve(bent, 2.)
        actual = offset_curve_shape(bent, 2.)
        self.assertAlmostEqual(self.geo.curve_length(actual), self.geo.curve_length(expected))

    def test_offset_publishes_curves_fill_and_thickness(self):
        source = line('line', (0, 0, 0), (10, 0, 0))
        node = state('offset', parameters={'D': 2.})
        owner = self.publish(self.model('offset', {'G': source}, node))
        edge, = self.geo.edges_of(owner.shape)
        self.assertEqual(self.geo.sample_curve(edge, 2), [(0, -2, 0), (10, -2, 0)])
        fill = {**node, 'parameters': {'D': 2., 'fill': True}}
        ribbon = self.publish(self.model('offset', {'G': source}, fill))
        self.assertEqual(ribbon.id, owner.id)
        self.assertAlmostEqual(self.geo.surface_area(ribbon.shape), 20.)
        ring = circle('circle', (0, 0, 0), 10, PlaneValue())
        annulus = self.publish(self.model('offset', {'G': ring}, fill))
        self.assertAlmostEqual(self.geo.surface_area(annulus.shape), 44*math.pi, delta=.01)

        outline = polyline('outline', ((0, 0, 0), (10, 0, 0), (10, 5, 0), (0, 5, 0)), True)
        surface = evaluate_operation('planar_surface', state('planar_surface'), {'C': outline})['G']
        sheet = self.publish(self.model('offset', {'G': surface}, node))
        self.assertAlmostEqual(self.geo.surface_area(sheet.shape), 50.)
        lower, upper = self.geo.bbox(sheet.shape)
        self.assertAlmostEqual(lower[2], upper[2], places=5)
        self.assertAlmostEqual(abs(lower[2]), 2., places=5)
        for sign in (-1, 1):
            mode = {**node, 'parameters': {'D': sign*2., 'solid': True}}
            solid = self.publish(self.model('offset', {'G': surface}, mode))
            self.assertEqual(self.geo.shape_kind(solid.shape), 'solid')
            self.assertAlmostEqual(self.geo.volume(solid.shape), 100.)
        self.assertEqual(len(self.window.scene.objects), 1)

    def test_surface_offset_preserves_signed_curvature_safety(self):
        from noodles.backend.offset_native import offset_geometry_shape
        from noodles.backend.solids import SolidValue
        cylinder = SolidValue('shell', 'cylinder', PlaneValue(), (5, 10), False)
        shape = materialize(cylinder)
        expanded = offset_geometry_shape(shape, 1.)
        self.assertAlmostEqual(self.geo.surface_area(expanded), 2*math.pi*6*10, delta=1e-5)
        with self.assertRaisesRegex(ValueError, 'folding'):
            offset_geometry_shape(shape, -4.5)

    def test_offset_fill_and_surface_native_commands_use_same_factories(self):
        from serpentine3d.commands import base
        from noodles.backend.offset_native import register_commands as register_offset

        self.window._noodles_bridge = self.bridge
        register_offset(self.ctx)
        scene = self.window.scene
        curve = scene.add(self.geo.make_line((0, 0, 0), (10, 0, 0)))
        surface = scene.add(self.geo.planar_face(self.geo.make_rectangle((0, 0, 0), (10, 5, 0))))
        for command, values, check in (
                ('offsetcurvefill', ([curve], 2.), self.geo.surface_area),
                ('offsetsurfacev2', ([surface], 2., 'Solid'), self.geo.volume)):
            previous = set(scene.objects)
            messages = []
            context = SimpleNamespace(echo=messages.append, cplane=SimpleNamespace(normal=(0, 0, 1)))
            action = base.resolve(command).fn(context)
            next(action)
            for value in values[:-1]:
                action.send(value)
            with self.assertRaises(StopIteration):
                action.send(values[-1])
            self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
            result, = set(scene.objects) - previous
            self.assertAlmostEqual(check(scene.get(result).shape), 20. if command == 'offsetcurvefill' else 100.)

    def test_offset_fix_command_previews_and_adds_a_native_wire_on_source_layer(self):
        from serpentine3d.commands import base, edit
        from noodles.backend.offset_native import register_commands as register_offset
        original = base.resolve('offset')
        self.window._noodles_bridge = self.bridge
        register_offset(self.ctx)
        self.assertIs(base.resolve('offset'), original)
        scene = self.window.scene
        layer = scene.layers.create('Offset source')
        shape = self.geo.make_polyline([(0, 0, 0), (10, 0, 0)])
        source = scene.add(shape, layer_id=layer.id)
        messages = []
        context = SimpleNamespace(echo=messages.append, cplane=SimpleNamespace(normal=(0, 0, 1)))
        command = base.resolve('offsetfix').fn(context)
        next(command)
        prompt = command.send([source])
        self.assertEqual(prompt.number_from, ((5, 0, 0), (0, -1, 0)))
        self.assertEqual(self.geo.sample_curve(prompt.preview_fn((5, 3, 0)), 2), [(0, 3, 0), (10, 3, 0)])
        with self.assertRaises(StopIteration):
            command.send((5, 3, 0))
        self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
        result, = [obj for obj in scene.all() if obj.id != source.id]
        self.assertEqual((result.layer_id, result.shape.ShapeType()), (layer.id, shape.ShapeType()))
        self.assertEqual(self.geo.sample_curve(result.shape, 2), [(0, 3, 0), (10, 3, 0)])
        self.assertIs(scene.get(source.id)._shape, shape)
        self.window.history.undo()
        self.assertEqual(list(scene.objects), [source.id])

    def test_cooperative_surface_mesh_keeps_native_face_and_edge_indices(self):
        import numpy as np
        from noodles.backend.native_display import tessellate
        from serpentine3d.core.tessellate import tessellate as baseline
        parts=[extrude_shape(materialize(curve),(0,0,12),True) for curve in sections()]
        compound=self.geo.make_compound(parts)
        actual=tessellate(compound,parts=parts)
        expected=baseline(compound)
        np.testing.assert_allclose(actual.vertices,expected.vertices,atol=1e-7)
        np.testing.assert_array_equal(actual.triangles,expected.triangles)
        np.testing.assert_array_equal(actual.face_of_triangle,expected.face_of_triangle)
        np.testing.assert_array_equal(actual.edge_of_segment,expected.edge_of_segment)
        np.testing.assert_allclose(actual.edge_segments,expected.edge_segments,atol=1e-7)

    def test_pipe_uses_native_factory_one_owner_for_solid_and_shell(self):
        rail = line('rail', (0, 0, 0), (0, 0, 20))
        owner = self.publish(self.model('pipe', {'C': rail, 'R': 2}))
        self.assertAlmostEqual(self.geo.volume(owner.shape), 80*math.pi, delta=1e-5)
        self.assertEqual(len(self.geo.faces_of(owner.shape)), 3)
        shell = self.publish(self.model('pipe', {'C': rail, 'R': 3, 'S': False}))
        self.assertEqual(shell.id, owner.id)
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(self.geo.faces_of(shell.shape)), 1)
        self.assertAlmostEqual(self.geo.surface_area(shell.shape), 120*math.pi, delta=1e-5)
