"""Native Boolean applies once, against a private OCC scene and real bridge."""
from pathlib import Path
import unittest
from uuid import uuid4

from noodles.backend.geometry import normalize_geometry_state
from noodles.backend.solids import evaluate_solid, normalize_solid_state, solid_object_from_outputs
from noodles.core import Connection, GraphEngine, NodeSpec
from test_curves import PROJECT
import test_operation_native as native


def box(x):
    return normalize_solid_state('box', {'project_uuid': PROJECT, 'node_uuid': str(uuid4()),
                                         'parameters': {'O': [x, 0, 0]}})


def request(primitive):
    return {'project_uuid': PROJECT, 'node_uuid': str(uuid4()), 'primitive': primitive}


def operand(state, key, reference=False):
    return {'project_uuid': PROJECT, 'node_uuid': state['node_uuid'], 'key': key, 'reference': reference}


class NativeBooleanTests(unittest.TestCase):
    setUpClass = classmethod(native.NativeOperationTests.setUpClass.__func__)
    setUp = native.NativeOperationTests.setUp
    tearDown = native.NativeOperationTests.tearDown
    call = native.NativeOperationTests.call
    wait_for = native.NativeOperationTests.wait_for
    publish = native.NativeOperationTests.publish

    def source(self, x):
        state = box(x)
        wire = solid_object_from_outputs(state, evaluate_solid('box', state, {})).to_wire()
        obj = self.publish(wire)
        return obj, wire, operand(state, wire['branches'][0]['parts'][0]['key'])

    def finish(self, method, params):
        if method == 'geometry.boolean_apply' and 'scene_token' not in params:
            status = self.finish('geometry.boolean_read', params)
            params = {**params, 'scene_token': status['scene_token']}
        reply = self.call(method, params)
        if 'job_id' in reply:
            self.wait_for(lambda: self.bridge.points.jobs[reply['job_id']]['state'] != 'preparing')
            reply = self.call('geometry.job', reply)
        return reply

    def test_each_operation_consumes_inputs_and_restores_them_with_cad_undo(self):
        scene = self.window.scene
        for operation, volume in [('union', 1500), ('difference', 500), ('intersection', 500)]:
            with self.subTest(operation=operation):
                a, wire_a, target_a = self.source(0)
                b, wire_b, target_b = self.source(5)
                scene.update(a.id, name='Base', color=(.1, .2, .3))
                params = {**request('boolean_'+operation),
                          'rows': [{'path': [3], 'targets': [target_a, target_b]}]}
                reply = self.finish('geometry.boolean_apply', params)
                self.assertEqual(reply['state'], 'complete', reply)
                result, = reply['records']
                self.assertEqual((result['id'], result['path']), (a.id, [3]))
                obj = scene.get(a.id)
                self.assertEqual((obj.name, obj.color), ('Base', (.1, .2, .3)))
                self.assertAlmostEqual(self.geo.volume(obj.shape), volume)
                self.assertIsNone(scene.get(b.id))
                self.assertEqual(self.finish('geometry.boolean_apply', params)['records'], reply['records'])
                for wire in (wire_a, wire_b):
                    response = self.finish('geometry.prepare', {'model': wire})
                    self.assertTrue(response['consumed'])
                self.assertEqual(self.window.history.undo(), 'NoodleS ' + operation.title())
                self.assertIs(scene.get(a.id)._shape, a._shape)
                self.assertIs(scene.get(b.id)._shape, b._shape)
                self.assertEqual(self.finish('geometry.boolean_read', params)['records'], [])
                self.window.history.redo()
                self.assertIsNone(scene.get(b.id))

    def test_native_failure_in_second_branch_never_consumes_first(self):
        sources = [self.source(x) for x in (0, 5, 30, 100)]
        params = {**request('boolean_intersection'), 'rows': [
            {'path': [0], 'targets': [sources[0][2], sources[1][2]]},
            {'path': [1], 'targets': [sources[2][2], sources[3][2]]},
        ]}
        response = self.finish('geometry.boolean_apply', params)
        self.assertEqual(response['state'], 'error')
        self.assertIn('produced no', response['error'])
        for obj, _, _ in sources:
            self.assertIs(self.window.scene.get(obj.id)._shape, obj._shape)
        self.assertFalse(self.window.scene.history_records)

    def test_split_keeps_shared_cutter_and_replaces_targets_with_individual_solids(self):
        from serpentine3d.fileio.native import load_scene, save_scene

        scene = self.window.scene
        a, wire_a, target_a = self.source(0)
        b, wire_b, target_b = self.source(1)
        cutter, cutter_wire, tool = self.source(5)
        layer = scene.layers.create('Split targets')
        scene.update(a.id, layer_id=layer.id)
        params = {**request('boolean_split'), 'rows': [
            {'path': [3], 'targets': [target_a, tool]},
            {'path': [3], 'targets': [target_b, tool]},
        ]}
        reply = self.finish('geometry.boolean_apply', params)
        self.assertEqual(reply['state'], 'complete', reply)
        records = reply['records']
        self.assertEqual([r['path'] for r in records], [[3]] * 4)
        self.assertEqual(len({r['recipe']['key'] for r in records}), 4)
        self.assertEqual(len(scene.objects), 5)
        self.assertEqual([scene.get(r['id']).layer_id for r in records[:2]], [layer.id]*2)
        self.assertEqual(sorted(round(self.geo.volume(scene.get(r['id']).shape)) for r in records),
                         [400, 500, 500, 600])
        self.assertIsNone(scene.get(a.id))
        self.assertIsNone(scene.get(b.id))
        self.assertIs(scene.get(cutter.id)._shape, cutter._shape)
        reapplied = self.finish('geometry.boolean_apply', params)['records']
        self.assertEqual([(r['id'], r['recipe']['key']) for r in reapplied],
                         [(r['id'], r['recipe']['key']) for r in records])
        self.assertEqual(len(scene.objects), 5)
        self.assertEqual(self.window.history.undo(), 'NoodleS Split')
        self.assertIs(scene.get(a.id)._shape, a._shape)
        self.assertIs(scene.get(b.id)._shape, b._shape)
        self.assertEqual(len(scene.objects), 3)
        self.window.history.redo()
        path = str(Path(self.folder.name) / 'native-split.serp')
        save_scene(scene, path)
        reopened = self.Scene()
        load_scene(reopened, path)
        self.window.scene = reopened
        reloaded = self.finish('geometry.boolean_read', params)['records']
        self.assertEqual([r['recipe']['key'] for r in reloaded], [r['recipe']['key'] for r in records])
        self.assertEqual(len(reopened.objects), 5)
        for wire in (wire_a, wire_b):
            self.assertTrue(self.finish('geometry.prepare', {'model': wire})['consumed'])
        self.assertFalse(self.finish('geometry.prepare', {'model': cutter_wire}).get('consumed', False))

    def test_split_parametric_uses_cutting_plane_and_publishes_one_owner(self):
        from OCP.TopAbs import TopAbs_SOLID
        from noodles.backend.curves import PlaneValue, line
        from noodles.backend.datatree import Branch, DataTree
        from noodles.backend.operations import operation_from_wire
        from noodles.backend.scene_curves import materialize
        from noodles.backend.topology_native import measure

        target, _, _ = self.source(0)
        knife = line('knife', (-5, 0, 5), (15, 0, 5))
        value, = evaluate_solid('box', box(0), {})['G'].values()
        state = normalize_geometry_state('boolean_split_parametric', request('boolean_split_parametric'))
        inputs = {'A': DataTree((Branch((2,), (value,)),)), 'B': knife,
                  'P': PlaneValue(normal=(0, 1, 0))}
        from noodles.backend.geometry import evaluate_geometry, geometry_object_from_outputs
        pending = evaluate_geometry('boolean_split_parametric', state, inputs)['_sampling']
        kinds = measure(pending['plan'], lambda: True, {})
        state['sampling_details'] = {'signature': pending['signature'], 'values': kinds}
        output = evaluate_geometry('boolean_split_parametric', state, inputs)
        self.assertEqual(output['Count'], 2)
        self.assertEqual(output['G'].branches[0].path, (2,))
        for part in output['G'].values():
            self.assertEqual(materialize(operation_from_wire(part.to_wire())).ShapeType(), TopAbs_SOLID)
        owner = self.publish(geometry_object_from_outputs(state, output).to_wire())
        self.assertEqual(len(self.window.scene.objects), 2)
        self.assertEqual(len(self.geo.loose_pieces(owner.shape)), 2)
        self.assertAlmostEqual(self.geo.volume(owner.shape), 1000)
        self.assertIs(self.window.scene.get(target.id)._shape, target._shape)

    def test_split_native_failed_target_leaves_all_sources_in_scene(self):
        sources = [self.source(x) for x in (0, 30, 5)]
        params = {**request('boolean_split'), 'rows': [
            {'path': [0], 'targets': [target, sources[-1][2]]} for _, _, target in sources[:2]
        ]}
        reply = self.finish('geometry.boolean_apply', params)
        self.assertEqual(reply['state'], 'error', reply)
        for obj, _, _ in sources:
            self.assertIs(self.window.scene.get(obj.id)._shape, obj._shape)
        self.assertFalse(self.window.scene.history_records)

    def test_split_nodes_through_properties_and_live_graph(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        scene = self.window.scene
        try:
            target = gui.add_node('NoodleS.Geometry.BoxNode')
            cutter = gui.add_node('NoodleS.Geometry.BoxNode')
            cutter.set_property('parameters', {**cutter.curve_state()['parameters'], 'O': [5, 0, 0]})
            copy = gui.add_node('NoodleS.Geometry.BooleanSplitParametricNode')
            target.outputs()['G'].connect_to(copy.inputs()['A'])
            cutter.outputs()['G'].connect_to(copy.inputs()['B'])
            self.wait_for(lambda: len(scene.objects) == 3 and
                          gui.evaluation.results[copy.id].outputs.get('Count') == 2)
            panel = gui.properties.curve_properties
            self.assertTrue(panel.show_parent.isVisible())
            QTest.mouseClick(panel.show_parent, QtCore.Qt.LeftButton,
                             pos=QtCore.QPoint(7, panel.show_parent.height() // 2))
            def owner(node):
                return self.bridge.points.owner((gui.project_uuid, node.curve_state()['node_uuid'], 0))
            self.wait_for(lambda: not owner(target).visible and not owner(cutter).visible)
            gui.graph.undo_stack().undo()
            self.wait_for(lambda: owner(target).visible and owner(cutter).visible)
            split = gui.add_node('NoodleS.Geometry.BooleanSplitNode')
            target.outputs()['G'].connect_to(split.inputs()['A'])
            cutter.outputs()['G'].connect_to(split.inputs()['B'])
            button = panel.boolean_apply
            self.wait_for(lambda: button.isVisible() and button.isEnabled() and not gui._graph_worker.running)
            target_id, cutter_id = owner(target).id, owner(cutter).id
            self.assertEqual(button.text(), 'Apply Boolean Split')
            self.assertEqual(gui.evaluation.results[split.id].outputs['Count'], 0)
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.wait_for(lambda: gui.evaluation.results[split.id].outputs.get('Count') == 2)
            self.assertIsNone(scene.get(target_id))
            self.assertIsNotNone(scene.get(cutter_id))
            self.assertFalse(button.isEnabled())
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    def test_reopen_and_deleted_result_do_not_republish_consumed_inputs(self):
        from serpentine3d.fileio.native import load_scene, save_scene
        a, wire, first = self.source(0)
        _, _, second = self.source(30)
        params = {**request('boolean_union'), 'rows': [{'path': [0], 'targets': [first, second]}]}
        result = self.finish('geometry.boolean_apply', params)
        self.assertEqual(result['state'], 'complete', result)
        from OCP.TopAbs import TopAbs_COMPOUND
        shape = self.window.scene.get(result['records'][0]['id']).shape
        self.assertEqual(shape.ShapeType(), TopAbs_COMPOUND)
        self.assertEqual(len(self.geo.loose_pieces(shape)), 2)
        path = str(Path(self.folder.name) / 'native-boolean.serp')
        save_scene(self.window.scene, path)
        self.window.scene = self.Scene()
        load_scene(self.window.scene, path)
        reloaded = self.finish('geometry.boolean_read', params)
        self.assertNotEqual(reloaded['records'][0]['id'], a.id)
        self.window.scene.remove(reloaded['records'][0]['id'])
        self.assertTrue(self.finish('geometry.boolean_read', params)['missing'])
        self.assertTrue(self.finish('geometry.prepare', {'model': wire})['consumed'])

    def test_graph_passes_stable_bindings_and_result_without_reapplying(self):
        first, second = NodeSpec('a', 'box', box(0)), NodeSpec('b', 'box', box(5))
        merge = NodeSpec('merge', 'merge', inputs={'A': Connection('a', 'G'), 'B': Connection('b', 'G')})
        state = normalize_geometry_state('boolean_union', request('boolean_union'))
        union = NodeSpec('union', 'boolean_union', state, {'O': Connection('merge', 'D')})
        engine = GraphEngine()
        graph = engine.evaluate([first, second, merge, union])
        plan = graph.results['union'].boolean_plan
        self.assertIsNotNone(plan)
        self.assertIsNone(graph.results['union'].parametric_object)
        for node in (first, second):
            self.publish(graph.results[node.id].parametric_object.to_wire())
        records = self.finish('geometry.boolean_apply', plan)['records']
        result = engine.evaluate([NodeSpec('union', 'boolean_union', {**state, 'boolean_records': records})]).results['union']
        self.assertIsNone(result.boolean_plan)
        self.assertEqual(result.outputs['G'].count, 1)
        self.assertEqual(next(iter(result.bindings['G'].values())).reference_id, records[0]['id'])

    def test_compound_is_consumed_only_with_all_of_its_parts(self):
        from noodles.backend.booleans import native_boolean_plan
        from noodles.backend.datatree import Branch, DataTree
        from noodles.backend.moves import source_bindings
        from noodles.backend.point import PointValue
        from noodles.bridge import BridgeRemoteError

        state = box(0)
        outputs = evaluate_solid('box', state, {
            'O': DataTree((Branch((0,), (PointValue('a', (0, 0, 0)), PointValue('b', (30, 0, 0)))),)),
        })
        model = solid_object_from_outputs(state, outputs)
        wire = model.to_wire()
        a = self.publish(wire)
        b, _, tool = self.source(5)
        keys = [part['key'] for part in wire['branches'][0]['parts']]
        base = operand(state, keys[0])
        params = {**request('boolean_difference'), 'rows': [{'path': [0], 'targets': [base, tool]}]}
        with self.assertRaisesRegex(BridgeRemoteError, 'every part'):
            self.finish('geometry.boolean_apply', params)
        self.assertIs(self.window.scene.get(a.id)._shape, a._shape)
        self.assertIs(self.window.scene.get(b.id)._shape, b._shape)
        source = NodeSpec('a', 'box', state)
        tool_model = box(5)
        tool_model['node_uuid'] = tool['node_uuid']
        tool_value = evaluate_solid('box', tool_model, {})
        tool_entity = solid_object_from_outputs(tool_model, tool_value)
        bindings = {'A': source_bindings(source, outputs, model)['G'],
                    'B': source_bindings(NodeSpec('b', 'box', tool_model), tool_value, tool_entity)['G']}
        state = normalize_geometry_state('boolean_difference', params)
        params = native_boolean_plan('boolean_difference', state,
            {'A': outputs['G'], 'B': tool_value['G']}, bindings)
        self.assertEqual(params['rows'][0]['targets'][0]['parts'], keys)
        result = self.finish('geometry.boolean_apply', params)
        self.assertEqual(result['state'], 'complete', result)
        self.assertAlmostEqual(self.geo.volume(self.window.scene.get(a.id).shape), 1500)

    def test_document_guard_rejects_apply_after_scene_switch(self):
        from noodles.bridge import BridgeRemoteError
        params = request('boolean_union')
        token = self.finish('geometry.boolean_read', params)['scene_token']
        self.window.scene.clear()
        with self.assertRaisesRegex(BridgeRemoteError, 'document changed'):
            self.finish('geometry.boolean_apply', {**params, 'scene_token': token})

    def test_surface_intersection_uses_live_reference_shapes(self):
        targets, ids = [], []
        for x in (0, 5):
            profile = self.geo.make_rectangle((x, 0, 0), (x+10, 10, 0))
            obj = self.window.scene.add(self.geo.planar_face(profile))
            ids.append(obj.id)
            self.window.selection.set([obj.id])
            state = {**request('planar_surface'), 'mode': 'reference'}
            record, = self.finish('geometry.capture', state)['references']
            targets.append(operand(state, record['key'], reference=True))
        params = {**request('boolean_intersection'), 'rows': [{'path': [0], 'targets': targets}]}
        reply = self.finish('geometry.boolean_apply', params)
        self.assertEqual(reply['state'], 'complete', reply)
        self.assertAlmostEqual(self.geo.surface_area(self.window.scene.get(ids[0]).shape), 50)
        self.assertIsNone(self.window.scene.get(ids[1]))

    def test_properties_apply_is_explicit_and_cad_undo_refreshes_output(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            a = gui.add_node('NoodleS.Geometry.BoxNode')
            b = gui.add_node('NoodleS.Geometry.BoxNode')
            b.set_property('parameters', {**b.curve_state()['parameters'], 'O': [5, 0, 0]})
            merge = gui.add_node('NoodleS.Data.MergeNode')
            union = gui.add_node('NoodleS.Geometry.BooleanUnionNode')
            a.outputs()['G'].connect_to(merge.inputs()['A'])
            b.outputs()['G'].connect_to(merge.inputs()['B'])
            merge.outputs()['D'].connect_to(union.inputs()['O'])
            button = gui.properties.curve_properties.boolean_apply
            self.wait_for(lambda: button.isVisible() and button.isEnabled()
                          and len(self.window.scene.objects) == 2 and not gui._graph_worker.running)
            self.assertEqual(gui.evaluation.results[union.id].outputs['G'].count, 0)
            QTest.mouseClick(button, QtCore.Qt.LeftButton)
            self.wait_for(lambda: gui.evaluation.results[union.id].outputs.get('G')
                          and gui.evaluation.results[union.id].outputs['G'].count == 1)
            self.assertEqual(len(self.window.scene.objects), 1)
            self.assertFalse(button.isEnabled())
            self.window.history.undo()
            self.wait_for(lambda: button.isEnabled() and gui.evaluation.results[union.id].outputs['G'].count == 0)
            self.assertEqual(len(self.window.scene.objects), 2)
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()
