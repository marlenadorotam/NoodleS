"""Real OCC movement: selective grid members, copies, native references and persistence."""
from pathlib import Path
import threading
import unittest
import uuid
from dataclasses import replace
import test_curve_native as fixture
from test_moves import grid,move,state,PROJECT
from noodles.core import GraphEngine,NodeSpec,Connection
from noodles.backend.point import normalize_point_state
from noodles.backend.curves import normalize_curve_state
from noodles.backend.operations import normalize_operation_state


class NativeMoveTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp=fixture.NativeCurveTests.setUp
    tearDown=fixture.NativeCurveTests.tearDown
    call=fixture.NativeCurveTests.call
    wait_for=fixture.NativeCurveTests.wait_for
    publish=fixture.NativeCurveTests.publish

    def frame(self,plans):
        result=self.call('geometry.move_refs',{'client_uuid':'fba66dd1-1529-4760-9dd8-1d40e0ad5a66','entries':list(plans)})
        if 'job_id' in result:
            self.wait_for(lambda:self.bridge.geometry.jobs[result['job_id']]['state']!='preparing')
            result=self.call('geometry.job',result)
        self.assertEqual(result['state'],'complete',result)
        return result

    def test_selective_grid_points_edges_cells_and_whole_preserve_source_id_and_attributes(self):
        source=grid()
        base=GraphEngine().evaluate([source]).results['grid'].parametric_object
        owner=self.publish(base.to_wire())
        edges_before=[self.geo.sample_curve(e,3) for e in self.geo.edges_of(owner.shape)]
        for port in ('P','C','E','G'):
            result=GraphEngine().evaluate([source,move(port)])
            model=result.results['grid'].parametric_object
            updated=self.publish(model.to_wire())
            self.assertEqual(updated.id,owner.id)
            self.assertEqual(len(self.window.scene.objects),1)
            points=self.geo.free_points(updated.shape)
            self.assertEqual({round(p[2],6) for p in points},{5 if port in ('P','G') else 0})
            edge_points=[self.geo.sample_curve(e,3) for e in self.geo.edges_of(updated.shape)]
            if port=='P':
                self.assertEqual(edge_points,edges_before)
            else:
                self.assertTrue(all(abs(p[2]-5)<1e-7 for pts in edge_points for p in pts))
            self.assertTrue(updated.mesh_ready)

    def test_each_grid_point_gets_a_different_height_through_a_flat_numeric_list(self):
        source=grid()
        numbers=NodeSpec('series','series',{'count':6})
        translated=move()
        translated=NodeSpec(translated.id,translated.operation,translated.parameters,
            {**translated.inputs,'Z':Connection('series','S')})
        engine=GraphEngine()
        for _ in range(3):
            result=engine.evaluate([source,numbers,translated])
            self.assertIsNone(result.results['move'].error)
            model=result.results['grid'].parametric_object
            owner=self.publish(model.to_wire())
            self.assertEqual(sorted(round(p[2],6) for p in self.geo.free_points(owner.shape)),list(range(6)))
            self.assertTrue(all(abs(p[2])<1e-7 for e in self.geo.edges_of(owner.shape) for p in self.geo.sample_curve(e,2)))
        reset=engine.evaluate([source]).results['grid'].parametric_object
        owner=self.publish(reset.to_wire())
        self.assertEqual({round(p[2],6) for p in self.geo.free_points(owner.shape)},{0})

    def test_move_gh_copies_have_their_own_owner_and_delete_never_removes_grid(self):
        source=grid()
        result=GraphEngine().evaluate([source,move(operation='move_gh')])
        original=self.publish(result.results['grid'].parametric_object.to_wire())
        shape=original._shape
        copied_model=result.results['move'].parametric_object.to_wire()
        copied=self.publish(copied_model)
        self.assertNotEqual(copied.id,original.id)
        self.assertEqual(len(self.window.scene.objects),2)
        self.assertIs(self.window.scene.get(original.id)._shape,shape)
        self.assertEqual({round(p[2],6) for p in self.geo.free_points(copied.shape)},{5})
        self.call('geometry.remove',{k:copied_model[k] for k in ('project_uuid','node_uuid')})
        self.assertIsNotNone(self.window.scene.get(original.id))
        restored=self.publish(copied_model)
        self.assertEqual(restored.id,copied.id)

    def point_reference(self):
        obj=self.window.scene.add(self.geo.make_point((1,2,3)),name='Native point')
        params=normalize_point_state({'mode':'reference','project_uuid':PROJECT,'node_uuid':str(uuid.uuid4())})
        self.window.selection.set([obj.id])
        params['references']=self.call('points.capture',params)['references']
        source=NodeSpec('reference','point',params)
        moving=NodeSpec('moving','move',state('move',{'Z':5}),{'G':Connection('reference','P')})
        return obj,source,moving

    def test_point_reference_no_poll_drift_manual_move_and_changed_parameter(self):
        obj,source,moving=self.point_reference()
        engine=GraphEngine()
        plans=engine.evaluate([source,moving]).reference_moves
        self.frame(plans)
        self.assertEqual(tuple(self.geo.point_coords(self.window.scene.get(obj.id).shape)),(1,2,8))
        for _ in range(10):
            params={**source.parameters,'references':self.call('points.read',source.parameters)['references']}
            source=NodeSpec(source.id,source.operation,params)
            result=engine.evaluate([source,moving])
            self.assertEqual(result.results['moving'].outputs['G'].values()[0].xyz,(1,2,8))
            self.frame(result.reference_moves)
        self.window.scene.replace_shape(obj.id,self.geo.make_point((7,4,10)))
        source=NodeSpec(source.id,source.operation,{**source.parameters,'references':self.call('points.read',source.parameters)['references']})
        self.frame(engine.evaluate([source,moving]).reference_moves)
        self.assertEqual(tuple(self.geo.point_coords(self.window.scene.get(obj.id).shape)),(7,4,10))
        moving=NodeSpec(moving.id,moving.operation,{**moving.parameters,'parameters':{'X':0,'Y':0,'Z':9,'W':True}},moving.inputs)
        self.frame(engine.evaluate([source,moving]).reference_moves)
        self.assertEqual(tuple(self.geo.point_coords(self.window.scene.get(obj.id).shape)),(7,4,14))
        self.assertEqual(obj.name,'Native point')
        self.assertEqual(len(self.window.scene.objects),1)

    def test_reference_offsets_survive_serp_reopen_without_applying_twice(self):
        from serpentine3d.fileio.native import save_scene,load_scene
        obj,source,moving=self.point_reference()
        self.frame(GraphEngine().evaluate([source,moving]).reference_moves)
        path=Path(self.folder.name)/'moved.serp'
        save_scene(self.window.scene,str(path))
        reopened=self.Scene()
        load_scene(reopened,str(path))
        self.window.scene=reopened
        # An in-flight graph snapshot may still contain the old runtime ID.
        self.frame(GraphEngine().evaluate([source,moving]).reference_moves)
        params={**source.parameters,'references':self.call('points.read',source.parameters)['references']}
        self.assertEqual(params['references'][0]['move_offset'],[0,0,5])
        source=NodeSpec(source.id,source.operation,params)
        result=GraphEngine().evaluate([source,moving])
        self.frame(result.reference_moves)
        new=reopened.get(params['references'][0]['id'])
        self.assertNotEqual(new.id,obj.id)
        self.assertEqual(tuple(self.geo.point_coords(new.shape)),(1,2,8))

    def test_reference_reset_replays_after_disconnection_and_another_edit(self):
        from noodles.bridge import BridgeUnavailable
        from noodles.point_service import GeometryService

        available = threading.Event()
        available.set()
        interrupted = threading.Event()
        client = self.client

        class Client:
            def events(self, stop):
                return client.events(stop)

            def call(self, method, frame):
                if method == 'geometry.move_refs' and not available.is_set():
                    interrupted.set()
                    raise BridgeUnavailable('Simulated disconnection')
                return client.call(method, frame)

        obj, source, moving = self.point_reference()
        second, second_source, second_move = self.point_reference()
        second_source = replace(second_source, id='second_source')
        second_move = replace(second_move, id='second_move', inputs={'G': Connection(second_source.id, 'P')})
        service = GeometryService(client=Client())
        engine = GraphEngine()

        def coordinates(native):
            return tuple(self.geo.point_coords(self.window.scene.get(native.id).shape))

        service.start()
        try:
            service.sync_movements(engine.evaluate([source, moving]).reference_moves)
            self.wait_for(lambda: coordinates(obj) == (1, 2, 8))
            available.clear()
            service.sync_movements(())
            self.wait_for(interrupted.is_set)
            service.stop()
            service.sync_movements(engine.evaluate([second_source, second_move]).reference_moves)
            available.set()
            service.start()
            self.wait_for(lambda: coordinates(obj) == (1, 2, 3) and coordinates(second) == (1, 2, 8))
            self.assertEqual(len(self.window.scene.objects), 2)
        finally:
            service.stop()

    def test_duplicate_reference_binding_rejects_the_frame_before_mutating_geometry(self):
        from noodles.bridge import BridgeRemoteError

        obj, source, moving = self.point_reference()
        native = self.window.scene.get(obj.id)
        duplicate = self.window.scene.add(self.geo.make_point((4, 5, 6)))
        self.window.scene.update(duplicate.id, user_text=native.user_text)
        plans = GraphEngine().evaluate([source, moving]).reference_moves
        with self.assertRaisesRegex(BridgeRemoteError, 'duplicated'):
            self.frame(plans)
        self.assertEqual(tuple(self.geo.point_coords(self.window.scene.get(obj.id).shape)), (1, 2, 3))

    def test_extrude_accepts_a_moved_surface_recipe(self):
        def state_for(operation, normalize):
            return normalize(operation, {'project_uuid': PROJECT, 'node_uuid': str(uuid.uuid4())})

        rect = NodeSpec('rect', 'rectangle', state_for('rectangle', normalize_curve_state))
        surface = NodeSpec('face', 'planar_surface', state_for('planar_surface', normalize_operation_state),
                           {'C': Connection('rect', 'C')})
        moved = NodeSpec('move', 'move', state('move', {'Z': 5}), {'G': Connection('face', 'G')})
        extrude = NodeSpec('extrude', 'extrude', state_for('extrude', normalize_operation_state),
                           {'G': Connection('move', 'G')})
        result = GraphEngine().evaluate([rect, surface, moved, extrude]).results
        self.assertIsNone(result['extrude'].error)
        owner = self.publish(result['extrude'].parametric_object.to_wire())
        low, high = self.geo.bbox(owner.shape)
        self.assertAlmostEqual(low[2], 5, places=5)
        self.assertAlmostEqual(high[2], 15, places=5)

    def test_curve_reference_preserves_native_id_layer_color_and_source_editability(self):
        obj=self.window.scene.add(self.geo.make_line((0,0,0),(5,0,0)),name='Native line')
        layer=self.window.scene.layers.create('Movement layer')
        self.window.scene.update(obj.id,layer_id=layer.id,color=None)
        params=normalize_curve_state('line',{'mode':'reference','project_uuid':PROJECT,'node_uuid':str(uuid.uuid4())})
        self.window.selection.set([obj.id])
        params['references']=self.call('curves.capture',params)['references']
        source=NodeSpec('reference','line',params)
        moving=NodeSpec('moving','move',state('move',{'X':3,'Y':4}),{'G':Connection('reference','C')})
        self.frame(GraphEngine().evaluate([source,moving]).reference_moves)
        current=self.window.scene.get(obj.id)
        self.assertEqual(current.layer_id,layer.id)
        self.assertEqual(current.name,'Native line')
        self.assertIsNone(current.color)
        self.assertEqual(self.geo.sample_curve(current.shape,2),[(3,4,0),(8,4,0)])
        params['references']=self.call('curves.read',params)['references']
        source=NodeSpec(source.id,source.operation,params)
        self.frame(GraphEngine().evaluate([source,moving]).reference_moves)
        self.assertEqual(self.geo.sample_curve(current.shape,2),[(3,4,0),(8,4,0)])
