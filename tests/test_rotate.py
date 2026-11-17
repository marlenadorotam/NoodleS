"""Rotate contracts through the graph, Properties and the native OCC bridge."""
from dataclasses import replace
import math
from pathlib import Path
import unittest

from Qt import QtCore
from PySide6.QtTest import QTest
import test_move_native as native
import test_move_ui as ui
from test_moves import grid, state
from noodles.backend.curves import PlaneValue
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.moves import GridEditValue, RigidValue, evaluate_move
from noodles.backend.point import PointValue, object_from_wire
from noodles.core import Connection, GraphEngine, NodeSpec


class RotateDataTests(unittest.TestCase):
    def test_target_point_angle_precedence_and_tree_copy(self):
        p = PointValue('p', (2, 0, 0))
        target = PointValue('target', (0, 1, 0))
        result, *_ = evaluate_move('rotate', state('rotate'), {'G': p, 'To': target})
        self.assertEqual(result['A'].values(), (90.,))
        self.assertLess(math.dist(result['G'].values()[0].xyz, (0, 2, 0)), 1e-12)
        result, *_ = evaluate_move('rotate', state('rotate'), {'G': p, 'To': 'ignored', 'A': 0})
        self.assertEqual(result['G'].values()[0].xyz, p.xyz)
        result, *_ = evaluate_move('rotate', state('rotate'),
            {'G': PointValue('vertical', (1, 0, 0)), 'P': PlaneValue((0, 0, 0), (1, 0, 0), (0, 1, 0)), 'A': 90})
        self.assertLess(math.dist(result['G'].values()[0].xyz, (0, 0, -1)), 1e-12)

        base = GraphEngine().evaluate([grid()]).results['grid']
        angles = DataTree((Branch((0,), (0, 90, 180)), Branch((1,), (90, 180, 270))))
        result, model, _, effects = evaluate_move('rotate', state('rotate', {'Cp': True}),
            {'G': base.outputs['P'], 'A': angles}, base.bindings['P'], 'rotate')
        self.assertEqual(model.parts.count, 6)
        self.assertFalse(effects)
        self.assertEqual([b.path for b in result['G'].branches], [(0,), (1,)])
        self.assertEqual(result['A'].values(), angles.values())

    def test_move_rotate_order_and_shared_grid_conflict(self):
        source = grid()
        moved = NodeSpec('move', 'move', state('move', {'X': 3}), {'G': Connection('grid', 'G')})
        turned = NodeSpec('rotate', 'rotate', state('rotate', {'A': 90}), {'G': Connection('move', 'G')})
        evaluation = GraphEngine().evaluate([source, moved, turned])
        self.assertFalse(evaluation.results['rotate'].error)
        model = evaluation.results['grid'].parametric_object
        rigid = model.parts.values()[0]
        self.assertIsInstance(rigid, RigidValue)
        self.assertLess(math.dist(rigid.motion.offset, (0, 3, 0)), 1e-12)
        self.assertEqual(object_from_wire(model.to_wire()), model)
        member = replace(turned, inputs={'G': Connection('grid', 'P')})
        conflict = GraphEngine().evaluate([source, moved, member])
        self.assertIn(source.id, conflict.frozen_owners)
        self.assertIn('Conflicting', conflict.results[member.id].error)


class RotateNativeTests(unittest.TestCase):
    setUpClass = classmethod(native.NativeMoveTests.setUpClass.__func__)
    setUp = native.NativeMoveTests.setUp
    tearDown = native.NativeMoveTests.tearDown
    call = native.NativeMoveTests.call
    wait_for = native.NativeMoveTests.wait_for
    publish = native.NativeMoveTests.publish
    frame = native.NativeMoveTests.frame
    point_reference = native.NativeMoveTests.point_reference

    def test_generated_grid_selective_rotation_preserves_edges_and_owner(self):
        source = grid()
        engine = GraphEngine()
        base = engine.evaluate([source]).results['grid'].parametric_object
        original = self.publish(base.to_wire())
        lines = [self.geo.sample_curve(e, 3) for e in self.geo.edges_of(original.shape)]
        turn = NodeSpec('turn', 'rotate', state('rotate', {'A': 90}), {'G': Connection('grid', 'P')})
        model = engine.evaluate([source, turn]).results['grid'].parametric_object
        self.assertIsInstance(model.parts.values()[0], GridEditValue)
        updated = self.publish(model.to_wire())
        self.assertEqual(updated.id, original.id)
        self.assertEqual([self.geo.sample_curve(e, 3) for e in self.geo.edges_of(updated.shape)], lines)
        self.assertEqual({(round(x), round(y)) for x, y, _ in self.geo.free_points(updated.shape)},
                         {(x, y) for x in (0, -10) for y in (0, 10, 20)})
        self.assertEqual(len(self.window.scene.objects), 1)
        restored = self.publish(base.to_wire())
        copy = replace(turn, inputs={'G': Connection('grid', 'G')},
                       parameters={**turn.parameters, 'parameters': {'A': -90, 'Cp': True}})
        copy_model = engine.evaluate([source, copy]).results['turn'].parametric_object
        duplicate = self.publish(copy_model.to_wire())
        self.assertNotEqual(duplicate.id, original.id)
        self.assertEqual(len(self.window.scene.objects), 2)
        self.assertIs(self.window.scene.get(original.id)._shape, restored._shape)
        self.assertEqual({(round(x), round(y)) for x, y, _ in self.geo.free_points(duplicate.shape)},
                         {(x, y) for x in (0, 10) for y in (0, -10, -20)})

    def test_reference_center_changes_reopen_and_reset_without_drift(self):
        from serpentine3d.fileio.native import load_scene, save_scene
        from noodles.point_service import GeometryService

        obj, source, _ = self.point_reference()
        engine = GraphEngine()
        turn = NodeSpec('turn', 'rotate', state('rotate', {'A': 90}), {'G': Connection('reference', 'P')})

        def point(obj_id):
            return self.geo.point_coords(self.window.scene.get(obj_id).shape)

        def refresh(source):
            return replace(source, parameters={**source.parameters, 'references':
                self.call('points.read', source.parameters)['references']})

        self.frame(engine.evaluate([source, turn]).reference_moves)
        self.assertLess(math.dist(point(obj.id), (-2, 1, 3)), 1e-10)
        source = refresh(source)
        self.assertIn('move_transform', source.parameters['references'][0])
        parameters = {**turn.parameters, 'parameters': {**turn.parameters['parameters'], 'C': [1, 0, 0], 'A': 180}}
        turn = replace(turn, parameters=parameters)
        self.frame(engine.evaluate([source, turn]).reference_moves)
        self.assertLess(math.dist(point(obj.id), (1, -2, 3)), 1e-10)
        path = Path(self.folder.name) / 'rotate.serp'
        save_scene(self.window.scene, str(path))
        reopened = self.Scene()
        load_scene(reopened, str(path))
        self.window.scene = reopened
        source = refresh(source)
        current_id = source.parameters['references'][0]['id']
        evaluation = engine.evaluate([source, turn])
        self.frame(evaluation.reference_moves)
        self.assertLess(math.dist(point(current_id), (1, -2, 3)), 1e-10)
        service = GeometryService()
        service.sync_movements(evaluation.reference_moves)
        service.sync_movements(())
        self.frame(service.motion_request['entries'])
        self.assertLess(math.dist(point(current_id), (1, 2, 3)), 1e-10)
        self.assertEqual(len(reopened.objects), 1)

    def test_reference_line_drive_keeps_rotation_and_attributes(self):
        from test_moves import PROJECT
        from uuid import uuid4
        from noodles.backend.curves import normalize_curve_state
        from noodles.backend.reference_drive import build_reference_drive

        scene = self.window.scene
        obj = scene.add(self.geo.make_line((0, 0, 0), (5, 0, 0)), name='Driven line')
        layer = scene.layers.create('Rotated')
        scene.update(obj.id, layer_id=layer.id, color=(.1, .3, .5))
        params = normalize_curve_state('line', {'mode': 'reference', 'project_uuid': PROJECT, 'node_uuid': str(uuid4())})
        self.window.selection.set([obj.id])
        params['references'] = self.call('geometry.capture', params)['references']
        source = NodeSpec('source', 'line', params)
        turn = NodeSpec('turn', 'rotate', state('rotate', {'A': 90}), {'G': Connection('source', 'C')})
        self.frame(GraphEngine().evaluate([source, turn]).reference_moves)
        drive = build_reference_drive('line', params, {'B': PointValue('end', (8, 0, 0))})
        reply = self.call('geometry.drive', {**params, 'drive': drive})
        self.wait_for(lambda: self.bridge.geometry.jobs[reply['job_id']]['state'] != 'preparing')
        outcome = self.call('geometry.job', reply)
        self.assertEqual(outcome['state'], 'complete', outcome)
        current = scene.get(obj.id)
        self.assertEqual((current.layer_id, current.color, current.name), (layer.id, (.1, .3, .5), 'Driven line'))
        self.assertLess(math.dist(self.geo.sample_curve(current.shape, 2)[-1], (0, 8, 0)), 1e-10)


class RotateUiTests(unittest.TestCase):
    setUpClass = classmethod(ui.MoveUiTests.setUpClass.__func__)
    setUp = ui.MoveUiTests.setUp
    tearDown = ui.MoveUiTests.tearDown
    settle = ui.MoveUiTests.settle

    def test_edit_angle_copy_and_undo_from_properties(self):
        source = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        rotate = self.window.add_node('NoodleS.Geometry.RotateNode')
        source.outputs()['G'].connect_to(rotate.inputs()['G'])
        self.settle()
        panel = self.window.properties.curve_properties
        field = panel.editors['A'][0]
        field.setFocus()
        QTest.keyClick(field, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(field, '90')
        QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[rotate.id].outputs['A'].values(), (90.,))
        self.assertNotIn(rotate.id, self.window.point_service.models)
        checkbox = panel.editors['Cp'][0]
        QTest.mouseClick(checkbox, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, checkbox.height() // 2))
        self.settle()
        self.assertIn(rotate.id, self.window.point_service.models)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertNotIn(rotate.id, self.window.point_service.models)
