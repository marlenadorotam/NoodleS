"""Owned-object Delete/Undo/Redo on real OCC and actual NodeGraphQt history."""
import copy
from dataclasses import fields
import uuid
import unittest
from unittest.mock import patch

from Qt import QtCore
from PySide6.QtTest import QTest
from noodles.backend.curves import CURVE_SPECS, evaluate_curve, curve_object_from_outputs
from noodles.backend.solids import SOLID_SPECS, evaluate_solid, solid_object_from_outputs
from noodles.backend.point import evaluate_point, object_from_outputs
from noodles.bridge import BridgeClient, BridgeError, BridgeRemoteError
from noodles.serpentine_plugin.NoodleSBridge import BridgeServer
from noodles.window import MainWindow
from test_curves import state as curve_state, inputs_for
from test_solids import state as solid_state
import test_curve_native as fixture


def attributes(obj):
    return {f.name: copy.deepcopy(getattr(obj, f.name)) for f in fields(obj)
            if f.name not in ('_shape', '_mesh', '_bounds', '_scene')}


class GeometryDeleteNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp = fixture.NativeCurveTests.setUp
    tearDown = fixture.NativeCurveTests.tearDown
    call = fixture.NativeCurveTests.call
    wait_for = fixture.NativeCurveTests.wait_for
    publish = fixture.NativeCurveTests.publish

    def model(self, operation):
        node_uuid = str(uuid.uuid4())
        if operation == 'point':
            state = {**self.parameters, 'node_uuid': node_uuid, 'x': 1, 'y': 2, 'z': 3, 'tree_modes': {}, 'references': []}
            return object_from_outputs(state, evaluate_point(state, {})).to_wire()
        if operation in CURVE_SPECS:
            state = curve_state(operation, node_uuid=node_uuid)
            return curve_object_from_outputs(state, evaluate_curve(operation, state, inputs_for(operation))).to_wire()
        state = solid_state(operation, node_uuid=node_uuid)
        return solid_object_from_outputs(state, evaluate_solid(operation, state, {})).to_wire()

    def editor(self, operation='BoxNode'):
        app = MainWindow()
        node = app.add_node('NoodleS.Geometry.'+operation)
        app.point_service.client = self.client
        app.point_service.start()
        app.show()
        self.wait_for(lambda: len(self.window.scene.objects) == 1)
        return app, node, self.window.scene.all()[0]

    def close_editor(self, app):
        app.graph.undo_stack().setClean()
        app.close()
        app.deleteLater()
        self.app.processEvents()

    def style(self, owner):
        scene = self.window.scene
        parent = scene.layers.create('Assembly', color=(.2, .4, .6))
        child = scene.layers.create('Beams', parent=parent.id)
        return scene.update(owner.id, name='My custom geometry', layer_id=child.id, color=None,
            visible=False, locked=True, group_id='assembly-group', linetype='Dashed', print_width=.35,
            material={'roughness': .3, 'custom': {'value': [1, 2, 3]}}, draw_order=7,
            annotation={'text': 'My note'}, clip_plane={'enabled': False},
            section_fill={'pattern': 'lines', 'angle': 25},
            user_text={**(owner.user_text or {}), 'My attribute': 'keep me'})

    def test_every_geometry_kind_restores_exact_owner_mesh_attributes_and_binding(self):
        for operation in ('point', *CURVE_SPECS, *SOLID_SPECS):
            with self.subTest(operation=operation):
                model = self.model(operation)
                owner = self.style(self.publish(model))
                expected, shape, mesh = attributes(owner), owner._shape, owner._mesh
                removed = self.call('geometry.remove', model)
                self.assertTrue(removed['removed'])
                self.assertIsNone(self.window.scene.get(owner.id))
                restored = self.publish(model)
                self.assertEqual(attributes(restored), expected)
                self.assertIs(restored._shape, shape)
                self.assertIs(restored._mesh, mesh)
                self.assertIs(restored._scene, self.window.scene)
                self.window.scene.remove(restored.id)

    def test_real_keyboard_delete_undo_redo_preserves_later_unrelated_scene_edits(self):
        app, node, owner = self.editor()
        try:
            owner = self.style(owner)
            expected, shape, mesh = attributes(owner), owner._shape, owner._mesh
            other = self.window.scene.add(self.geo.make_point((3, 4, 5)), name='Other object')
            app.graph.clear_selection()
            node.set_selected(True)
            viewer = app.graph.viewer()
            viewer.setFocus()
            self.app.processEvents()
            QTest.keyClick(viewer, QtCore.Qt.Key_Delete)
            self.wait_for(lambda: app.graph.get_node_by_id(node.id) is None)
            self.wait_for(lambda: self.window.scene.get(owner.id) is None)
            self.window.scene.replace_shape(other.id, self.geo.make_point((99, 88, 77)))
            later = self.window.scene.add(self.geo.make_point((7, 8, 9)), name='Created after delete')
            QTest.keyClick(viewer, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
            self.wait_for(lambda: app.graph.get_node_by_id(node.id) is not None)
            try:
                self.wait_for(lambda: self.window.scene.get(owner.id) is not None)
            except AssertionError:
                self.fail(str({'models': len(app.point_service.models), 'pending': len(app.point_service.pending),
                    'removals': len(app.point_service.removals), 'node_error': app.evaluation.results[node.id].error,
                    'jobs': [{k: j.get(k) for k in ('state', 'error', 'object_id')} for j in self.bridge.points.jobs.values()]}))
            restored = self.window.scene.get(owner.id)
            self.assertIs(app.graph.get_node_by_id(node.id), node)
            self.assertEqual(attributes(restored), expected)
            self.assertIs(restored._shape, shape)
            self.assertIs(restored._mesh, mesh)
            self.assertIsNotNone(self.window.scene.get(later.id))
            for actual, expected_coordinate in zip(self.geo.bbox(self.window.scene.get(other.id).shape)[0], (99, 88, 77)):
                self.assertAlmostEqual(actual, expected_coordinate, delta=1e-6)
            # Redo captures the latest native attributes, not a stale first backup.
            restored = self.window.scene.update(owner.id, name='Edited after undo', color=(.8, .1, .2))
            expected = attributes(restored)
            QTest.keyClick(viewer, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
            self.wait_for(lambda: self.window.scene.get(owner.id) is None)
            QTest.keyClick(viewer, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
            self.wait_for(lambda: self.window.scene.get(owner.id) is not None)
            self.assertEqual(attributes(self.window.scene.get(owner.id)), expected)
            self.assertEqual(len(self.window.scene.objects), 3)
        finally:
            self.close_editor(app)

    def test_busy_delete_is_retried_and_undo_cancels_pending_delete(self):
        app, node, owner = self.editor('CircleNode')
        try:
            owner = self.style(owner)
            expected = attributes(owner)
            self.window.processor.busy = True
            app.graph.delete_node(node)
            self.wait_for(lambda: node.id in app.point_service.removals)
            QTest.qWait(100)
            self.assertIsNotNone(self.window.scene.get(owner.id))
            published = []
            app.point_service.result.connect(lambda key, kind, data: published.append(kind) if key == node.id else None)
            app.graph.undo_stack().undo()
            self.wait_for(lambda: node.id in app.point_service.models)
            self.window.processor.busy = False
            self.wait_for(lambda: 'published' in published and self.window.scene.get(owner.id) is not None)
            self.assertEqual(attributes(self.window.scene.get(owner.id)), expected)
            self.window.processor.busy = True
            app.graph.undo_stack().redo()
            self.wait_for(lambda: node.id in app.point_service.removals)
            QTest.qWait(80)
            self.assertIsNotNone(self.window.scene.get(owner.id))
            self.window.processor.busy = False
            self.wait_for(lambda: self.window.scene.get(owner.id) is None)
            app.graph.undo_stack().undo()
            self.wait_for(lambda: self.window.scene.get(owner.id) is not None)
            self.assertEqual(attributes(self.window.scene.get(owner.id)), expected)
        finally:
            self.window.processor.busy = False
            self.close_editor(app)

    def test_offline_delete_and_offline_undo_apply_latest_intent_after_reconnect(self):
        app, node, owner = self.editor('PointNode')
        try:
            owner = self.style(owner)
            expected = attributes(owner)
            app.point_service.stop()
            app.graph.delete_node(node)
            self.app.processEvents()
            self.assertIsNotNone(self.window.scene.get(owner.id))
            app.point_service.start()
            self.wait_for(lambda: self.window.scene.get(owner.id) is None)
            app.point_service.stop()
            app.graph.undo_stack().undo()
            self.app.processEvents()
            app.point_service.start()
            self.wait_for(lambda: self.window.scene.get(owner.id) is not None)
            self.assertEqual(attributes(self.window.scene.get(owner.id)), expected)
        finally:
            self.close_editor(app)

    def test_deleted_layers_are_restored_without_overwriting_other_layers_or_current_layer(self):
        model = self.model('box')
        owner = self.style(self.publish(model))
        expected = attributes(owner)
        parent = self.window.scene.layers.get(owner.layer_id).parent
        self.call('geometry.remove', model)
        self.window.scene.remove_layer(parent)
        layer = self.window.scene.layers.create('New layer', color=(.9, .2, .3))
        self.window.scene.layers.current_id = layer.id
        restored = self.publish(model)
        self.assertEqual(attributes(restored), expected)
        self.assertEqual(self.window.scene.layers.current_id, layer.id)
        self.assertEqual(self.window.scene.layers.get(layer.id).color, (.9, .2, .3))
        self.assertEqual(self.window.scene.layers.get(owner.layer_id).parent, parent)

    def test_deleted_owner_survives_adapter_refresh_but_does_not_cross_native_documents(self):
        model = self.model('cylinder')
        owner = self.style(self.publish(model))
        expected = attributes(owner)
        self.call('geometry.remove', model)
        descriptor = self.bridge.descriptor
        self.bridge.stop()
        self.bridge = BridgeServer(self.ctx, descriptor)
        self.bridge.start()
        self.client = BridgeClient(descriptor, timeout=1)
        self.assertEqual(attributes(self.publish(model)), expected)
        self.call('geometry.remove', model)
        self.window.scene = self.Scene()
        fresh = self.publish(model)
        self.assertNotEqual(fresh.id, owner.id)
        self.assertNotEqual(fresh.name, expected['name'])

    def test_remove_failure_rolls_back_only_the_owned_object(self):
        model = self.model('sphere')
        owner = self.style(self.publish(model))
        before = attributes(owner)
        other = self.window.scene.add(self.geo.make_point((1, 2, 3)))
        original_remove = self.window.scene.remove
        def fail(oid):
            original_remove(oid)
            raise RuntimeError('Injected remove failure')
        with patch.object(self.window.scene, 'remove', side_effect=fail):
            with self.assertRaises(BridgeRemoteError):
                self.call('geometry.remove', model)
        self.assertEqual(attributes(self.window.scene.get(owner.id)), before)
        self.assertIsNotNone(self.window.scene.get(other.id))

    def test_lost_remove_ack_is_retried_idempotently_and_keeps_the_original_undo_record(self):
        app, node, owner = self.editor('CylinderNode')
        try:
            owner = self.style(owner)
            expected = attributes(owner)
            original_call = app.point_service.client.call
            attempts = []
            def interrupted(method, params=None):
                result = original_call(method, params)
                if method.endswith('.remove'):
                    attempts.append(method)
                    if len(attempts) == 1:
                        raise BridgeError('Injected lost response after native deletion')
                return result
            with patch.object(app.point_service.client, 'call', side_effect=interrupted):
                app.graph.delete_node(node)
                self.wait_for(lambda: len(attempts) >= 2 and self.window.scene.get(owner.id) is None)
                app.graph.undo_stack().undo()
                self.wait_for(lambda: self.window.scene.get(owner.id) is not None)
            self.assertEqual(attributes(self.window.scene.get(owner.id)), expected)
            self.assertEqual(len(self.window.scene.objects), 1)
        finally:
            self.close_editor(app)
