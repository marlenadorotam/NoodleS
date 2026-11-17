"""Real OCC/mesh/native commands in isolated scenes, never the user's document."""
from concurrent.futures import Future
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_point_native as native_fixture
import test_curve_native as curve_fixture
from test_grids import state
from noodles.backend.grids import GRID_SPECS,evaluate_grid,grid_object_from_outputs
from noodles.backend.scene_curves import materialize
from noodles.backend.grid_native import register_commands


class NativeGridTests(unittest.TestCase):
    setUpClass=classmethod(native_fixture.NativePointTests.setUpClass.__func__)
    setUp=native_fixture.NativePointTests.setUp
    tearDown=native_fixture.NativePointTests.tearDown
    call=native_fixture.NativePointTests.call
    wait_for=native_fixture.NativePointTests.wait_for
    publish=curve_fixture.NativeCurveTests.publish

    def model(self,operation,inputs=None,parameters=None):
        parameters=parameters or state(operation)
        return grid_object_from_outputs(parameters,evaluate_grid(operation,parameters,inputs or {})).to_wire()

    def test_ungroup_grid_command_keeps_exact_native_parts_and_follows_cad_undo(self):
        from pathlib import Path
        from serpentine3d.commands import base
        from serpentine3d.fileio.native import save_scene, load_scene
        from noodles.backend.scene_ungroup import register_commands

        scene = self.window.scene
        model = self.model('grid_rectangle', {'Ex': 2, 'Ey': 1})
        owner = self.publish(model)
        owner_id = owner.id
        layer = scene.layers.create('Grid results')
        scene.update(owner_id, layer_id=layer.id, color=(.2, .3, .4),
                     user_text={**owner.user_text, 'Part code': 'A123'})
        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        messages = []
        command = base.resolve('ungroupparametric').fn(SimpleNamespace(echo=messages.append))
        self.assertEqual(next(command).max_count, 1)
        with self.assertRaises(StopIteration):
            command.send([scene.get(owner_id)])
        self.wait_for(lambda: len(messages) > 1)
        self.assertIn('Ungrouped into 13 native object(s).', messages)

        parts = scene.all()
        self.assertEqual(sum(obj.kind == 'point' for obj in parts), 6)
        self.assertEqual(sum(obj.kind == 'curve' for obj in parts), 7)
        self.assertTrue(all(obj.layer_id == layer.id and obj.color == (.2, .3, .4) for obj in parts))
        self.assertTrue(all(obj.user_text == {'Part code': 'A123'} for obj in parts))
        self.assertIsNone(scene.get(owner_id))
        identity = {k: model[k] for k in ('project_uuid', 'node_uuid')}
        updated = self.model('grid_rectangle', {'Ex': 3, 'Ey': 1})
        job = self.call('geometry.prepare', {'model': updated, 'name': 'Grid'})
        self.assertTrue(self.call('geometry.job', job)['detached'])
        self.assertFalse(self.call('geometry.remove', identity)['removed'])
        self.assertEqual([obj.id for obj in scene.all()], [obj.id for obj in parts])

        self.window.history.undo()
        self.assertEqual(list(scene.objects), [owner_id])
        self.assertIs(scene.get(owner_id).shape, owner.shape)
        self.assertFalse(self.bridge.summary()['ungrouped_owners'])
        self.window.history.redo()
        self.assertEqual(len(scene.objects), 13)
        self.assertEqual(self.bridge.summary()['ungrouped_owners'], [list(identity.values())])

        path = Path(self.folder.name) / 'ungrouped.serp'
        save_scene(scene, str(path))
        load_scene(scene, str(path))
        self.assertEqual(len(self.window.scene.objects), 13)
        job = self.call('geometry.prepare', {'model': updated, 'name': 'Grid'})
        self.assertTrue(self.call('geometry.job', job)['detached'])

    def test_graph_node_context_ungroup_keeps_outgoing_data_and_graph_history(self):
        from Qt import QtCore, QtGui
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.client = editor.point_service.client = self.client
        editor.serpentine.interval = .02
        editor.show()
        try:
            grid = editor.add_node('NoodleS.Geometry.GridRectangleNode')
            editor.graph.center_on([grid])
            editor.serpentine.start()
            self.wait_for(lambda: editor.serpentine.state == 'connected' and len(self.window.scene.objects) == 1)
            before = editor.evaluation.results[grid.id].outputs['P']
            stack = editor.graph.undo_stack()
            stack.setClean()
            viewer = editor.graph.viewer()
            pos = viewer.mapFromScene(grid.view.sceneBoundingRect().center())
            menu = editor.graph.get_context_menu('graph').qmenu
            action = editor._ungroup_action
            seen = []

            def choose():
                seen.append(action.isVisible() and action.isEnabled() and menu.actions()[-1] is action)
                QTest.mouseClick(menu, QtCore.Qt.LeftButton, pos=menu.actionGeometry(action).center())
                menu.close()

            QTest.mousePress(viewer.viewport(), QtCore.Qt.RightButton, pos=pos)
            QtCore.QTimer.singleShot(0, choose)
            event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, viewer.viewport().mapToGlobal(pos))
            self.app.sendEvent(viewer.viewport(), event)
            QTest.mouseRelease(viewer.viewport(), QtCore.Qt.RightButton, pos=pos)
            self.assertEqual(seen, [True])
            self.wait_for(lambda: 'Ungrouped' in grid.scene_status)
            self.assertGreater(len(self.window.scene.objects), 1)
            self.assertFalse(grid.disabled())
            self.assertEqual(before, editor.evaluation.results[grid.id].outputs['P'])
            self.assertTrue(stack.isClean())
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_all_grids_one_scene_add_on_qt_native_points_edges_and_valid_mesh(self):
        from OCP.TopAbs import TopAbs_COMPOUND
        from OCP.BRepCheck import BRepCheck_Analyzer
        from noodles.backend.grid_native import materialize as native_grid
        for op in GRID_SPECS:
            with self.subTest(op=op):
                threads=[]
                def factory(value):
                    threads.append(threading.get_ident())
                    return native_grid(value)
                adds=[]
                native_add=self.window.scene.add
                def add(*args,**kwargs):
                    adds.append(threading.get_ident())
                    return native_add(*args,**kwargs)
                # Same binding across families intentionally exercises replace_shape.
                was_empty=not self.window.scene.objects
                with patch('noodles.backend.grid_native.materialize',side_effect=factory),patch.object(self.window.scene,'add',side_effect=add):
                    owner=self.publish(self.model(op))
                self.assertEqual(len(self.window.scene.objects),1)
                self.assertEqual(owner.shape.ShapeType(),TopAbs_COMPOUND)
                self.assertTrue(BRepCheck_Analyzer(owner.shape).IsValid())
                self.assertTrue(owner.mesh_ready)
                expected=evaluate_grid(op,state(op),{})['G'].values()[0].counts
                self.assertEqual(len(self.geo.edges_of(owner.shape)),expected[2])
                self.assertEqual(len(owner.mesh.points),expected[1])
                self.assertEqual(adds,[threading.get_ident()] if was_empty else [])
                self.assertTrue(threads and all(t!=threading.get_ident() for t in threads))

    def test_radial_cells_have_native_circular_arcs_not_faceted_polylines(self):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Circle
        out=evaluate_grid('grid_radial',state('grid_radial'),{'Er':2,'Ep':4})
        for cell in out['C'].values():
            native=materialize(cell)
            self.assertTrue(BRepCheck_Analyzer(native).IsValid())
            arcs=sum(BRepAdaptor_Curve(e).GetType()==GeomAbs_Circle for e in self.geo.edges_of(native))
            self.assertEqual(arcs,1 if len(cell.segments)==3 else 2)
            self.assertAlmostEqual(self.geo.curve_length(native),cell.length,delta=1e-6)

    def test_many_grids_one_owner_preserve_attributes_and_native_undo_snapshot(self):
        op='grid_hexagon'
        model=self.model(op,{'S':[2,3,4]})
        owner=self.publish(model)
        layer=self.window.scene.layers.create('My grids')
        self.window.scene.update(owner.id,name='Edited native name',layer_id=layer.id,color=None)
        updated=self.publish(self.model(op,{'S':[4,5,6]}))
        self.assertEqual(updated.id,owner.id)
        self.assertEqual(updated.name,'Edited native name')
        self.assertEqual(updated.layer_id,layer.id)
        self.assertIsNone(updated.color)
        shape,mesh=updated._shape,updated._mesh
        identity={k:model[k] for k in ('project_uuid','node_uuid')}
        self.assertTrue(self.call('geometry.remove',identity)['removed'])
        self.assertFalse(self.window.scene.objects)
        restored=self.publish(self.model(op,{'S':[4,5,6]}))
        self.assertEqual(restored.id,owner.id)
        self.assertIs(restored._shape,shape)
        self.assertIs(restored._mesh,mesh)
        self.assertEqual(restored.name,'Edited native name')

    def test_stale_grid_results_superseded_and_only_latest_commits(self):
        from threading import Event
        from noodles.backend.grid_native import materialize as build
        hold=Event()
        blocker=self.bridge.geometry.pool.submit(lambda:hold.wait(4))
        with patch('noodles.backend.grid_native.materialize',wraps=build) as factory:
            try:
                jobs=[self.call('geometry.prepare',{'model':self.model('grid_rectangle',{'Sx':i})}) for i in range(1,41)]
                a,b=jobs[0],jobs[-1]
                self.assertFalse(self.window.scene.objects)
            finally:
                hold.set()
            self.wait_for(lambda:self.bridge.geometry.jobs[b['job_id']]['state']!='preparing')
            self.assertEqual(factory.call_count,1)
        self.assertEqual(self.call('geometry.job',a)['state'],'superseded')
        result=self.call('geometry.job',b)
        self.assertEqual(result['state'],'complete')
        self.assertEqual(len(self.window.scene.objects),1)
        owner=self.window.scene.get(result['object_id'])
        low,high=self.geo.bbox(owner.shape)
        self.assertAlmostEqual(high[0]-low[0],160,delta=1e-6)

    def test_empty_input_removes_generated_owner(self):
        owner=self.publish(self.model('grid_rectangle'))
        self.assertIsNotNone(owner)
        result=self.publish(self.model('grid_rectangle',{'Sx':[]}))
        self.assertIsNone(result)
        self.assertFalse(self.window.scene.objects)

    def test_native_commands_use_same_async_publisher_without_editor(self):
        from serpentine3d.commands import base
        from serpentine3d.core.cplane import CPlane
        self.window._noodles_bridge=self.bridge
        register_commands(self.ctx)
        for op in GRID_SPECS:
            name=op.replace('_','')
            definition=base.resolve(name)
            self.assertFalse(definition.mutates)  # The asynchronous commit owns its checkpoint.
            messages=[]
            context=SimpleNamespace(scene=self.window.scene,cplane=CPlane(),echo=messages.append)
            generator=definition.fn(context)
            next(generator)
            values=['Native '+op,(1,2,3)]+([2.,3.] if op=='grid_rectangle' else [2.])+[2,4 if op=='grid_radial' else 2]
            for value in values:
                try:
                    generator.send(value)
                except StopIteration:
                    break
            else:
                self.fail('Command did not finish.')
            self.wait_for(lambda:any(m.startswith('Created ') for m in messages))
        self.assertEqual(len(self.window.scene.objects),4)
        self.assertTrue(all(o.mesh_ready for o in self.window.scene.all()))

    def test_native_accelerations_preserve_classification_free_points_and_display_mesh(self):
        import numpy as np
        from noodles.backend.viewport_acceleration import install_classification,marker_segments
        from noodles.backend.native_display import tessellate
        from serpentine3d.core import geometry as g
        from serpentine3d.core.tessellate import tessellate as native_tessellate
        from noodles.backend.grid_native import materialize as build
        old_kind=g.shape_kind
        old_points=g.free_points
        values=[evaluate_grid(op,state(op),{})['G'].values()[0] for op in GRID_SPECS]
        shapes=[build(value) for value in values]
        shapes += [g.make_point((1,2,3)),g.make_compound([]),g.make_compound([g.make_line((0,0,0),(1,2,3))])]
        expected_kinds=[old_kind(s) for s in shapes]
        expected_points=[old_points(s) for s in shapes]
        try:
            install_classification()
            for s,k,p in zip(shapes,expected_kinds,expected_points):
                self.assertEqual(g.shape_kind(s),k)
                self.assertEqual(g.free_points(s),p)
            for shape in shapes[:4]:
                actual,expected=tessellate(shape),native_tessellate(shape)
                np.testing.assert_allclose(actual.points,expected.points,atol=1e-6)
                np.testing.assert_allclose(actual.edge_segments,expected.edge_segments,atol=1e-6)
                np.testing.assert_array_equal(actual.edge_of_segment,expected.edge_of_segment)
            points=np.array([(1,2,3),(1e6,2e6,3e6)],np.float32)
            for size in (.7,.9,150.):
                axes=np.eye(3,dtype=np.float32)*size
                original=np.concatenate([np.stack([p-axis,p+axis]) for p in points for axis in axes]).astype(np.float32)
                np.testing.assert_array_equal(marker_segments(points,size),original)
        finally:
            g.shape_kind,g.free_points=old_kind,old_points
    def test_all_grid_references_preserve_owner_and_real_data_tree_after_reopen(self):
        from pathlib import Path
        import uuid
        from serpentine3d.fileio.native import save_scene, load_scene
        from noodles.backend.datatree import Branch, DataTree
        from noodles.backend.reference_drive import build_reference_drive

        def complete(method, params):
            job = self.call(method, params)
            self.wait_for(lambda: self.bridge.geometry.jobs[job['job_id']]['state'] != 'preparing')
            result = self.call('geometry.job', job)
            self.assertEqual(result['state'], 'complete', result)
            return result

        saved = []
        for op in GRID_SPECS:
            with self.subTest(op=op):
                port = 'Sx' if op == 'grid_rectangle' else 'S'
                tree = DataTree((Branch((4,), (6,)), Branch((7,), (8,))))
                parameters = state(op, node_uuid=str(uuid.uuid4()))
                owner = self.publish(self.model(op, {port: tree}, parameters))
                scene = self.window.scene
                moved = self.geo.translate(self.geo.rotate(owner.shape, (0, 0, 0), (0, 1, 0), 35), (3, 4, 5))
                scene.replace_shape(owner.id, moved)
                scene.update(owner.id, name='Manual grid', color=(.1, .3, .5))
                self.window.selection.set([owner.id])
                reference = state(op, mode='reference', node_uuid=str(uuid.uuid4()))
                reference['references'] = complete('geometry.capture', reference)['references']
                original = evaluate_grid(op, reference, {})
                self.assertEqual([b.path for b in original['G'].branches], [(4,), (7,)])
                self.assertAlmostEqual(original['G'].values()[0].frame.origin[2], 5)
                self.assertAlmostEqual(original['G'].values()[0].spacing[0], 6)
                self.assertNotAlmostEqual(original['G'].values()[0].frame.normal[0], 0)
                previous_ids = set(scene.objects)
                incoming = DataTree((Branch((4,), (11,)), Branch((7,), (13,))))
                drive = build_reference_drive(op, reference, {port: incoming})
                complete('geometry.drive', {**reference, 'drive': drive})
                reference['references'] = complete('geometry.read', reference)['references']
                current = evaluate_grid(op, reference, {})
                self.assertEqual([v.spacing[0] for v in current['G'].values()], [11, 13])
                self.assertEqual(set(scene.objects), previous_ids)
                self.assertEqual(scene.get(owner.id).name, 'Manual grid')
                self.assertEqual(scene.get(owner.id).color, (.1, .3, .5))
                self.assertTrue(scene.get(owner.id).mesh_ready)
                self.assertNotEqual(original['P'].values()[-1].xyz, current['P'].values()[-1].xyz)
                saved.append(reference)
        self.assertEqual(len(saved), 4)
        file = Path(self.folder.name) / 'reference-grids.serp'
        save_scene(self.window.scene, str(file))
        scene = self.Scene()
        load_scene(scene, str(file))
        self.window.scene = scene
        for ref in saved:
            records = complete('geometry.read', ref)['references']
            self.assertEqual([r['key'] for r in records], [r['key'] for r in ref['references']])
            self.assertNotEqual(records[0]['id'], ref['references'][0]['id'])
            self.assertEqual(records[0]['recipe']['spacing'][0], 11)

    def test_all_grid_reference_buttons_slider_and_delete_keep_scene_source(self):
        import uuid
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        app = MainWindow()
        app.point_service.client = self.client
        app.point_service.start()
        app.show()
        try:
            for op, spec in GRID_SPECS.items():
                with self.subTest(op=op):
                    owner = self.publish(self.model(op, parameters=state(op, node_uuid=str(uuid.uuid4()))))
                    slider = app.add_node('NoodleS.Inputs.SliderNode')
                    slider.set_property('value', 10)
                    node = app.add_node('NoodleS.Geometry.'+spec['class'])
                    self.wait_for(lambda: app.properties.node_id == node.id)
                    panel = app.properties.curve_properties
                    QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
                    self.window.selection.set([owner.id])
                    QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
                    self.wait_for(lambda: len(node.get_property('references')) == 1)
                    port = 'Sx' if op == 'grid_rectangle' else 'S'
                    slider.outputs()['Number'].connect_to(node.inputs()[port])
                    self.wait_for(lambda: node.id in app.point_service.completed_geometry_drives)
                    slider.set_property('value', 16)
                    def spacing():
                        result = app.evaluation.results.get(node.id)
                        return result.outputs['G'].values()[0].spacing[0] if result and not result.error else None
                    self.wait_for(lambda: spacing() == 16)
                    shape = self.window.scene.get(owner.id)._shape
                    self.assertIsNot(shape, owner._shape)
                    app.graph.delete_node(node)
                    self.wait_for(lambda: node.id not in app.point_service.references)
                    self.assertIs(self.window.scene.get(owner.id)._shape, shape)
        finally:
            app.point_service.stop()
            app.graph.undo_stack().setClean()
            app.close()
            app.deleteLater()
            self.app.processEvents()
