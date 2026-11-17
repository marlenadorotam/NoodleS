"""Scale and Mirror through graph evaluation, Properties and private OCC scenes."""
from dataclasses import replace
from pathlib import Path
import unittest

from Qt import QtCore
from PySide6.QtTest import QTest

from noodles.backend.datatree import Branch, DataTree
from noodles.backend.point import PointValue, object_from_wire
from noodles.core import Connection, GraphEngine, NodeSpec
from noodles.point_service import GeometryService
from test_moves import grid, state
import test_move_native as native
import test_move_ui as ui


class TransformDataTests(unittest.TestCase):
    def test_target_factor_precedence_and_invalid_factor(self):
        from noodles.backend.moves import evaluate_move
        point = PointValue('p', (2, 0, 0))
        target = PointValue('target', (1, 3, 0))
        params = state('scale', {'C': [1, 0, 0], 'F': 2})
        out, *_ = evaluate_move('scale', params, {'G': point, 'To': target})
        self.assertEqual(out['F'].values(), (3.,))
        self.assertEqual(out['G'].values()[0].xyz, (4., 0., 0.))
        out, *_ = evaluate_move('scale', params, {'G': point, 'To': 'ignored', 'F': .5})
        self.assertEqual(out['G'].values()[0].xyz, (1.5, 0., 0.))
        with self.assertRaisesRegex(ValueError, 'greater than zero'):
            evaluate_move('scale', params, {'G': point, 'F': 0})

    def test_data_tree_copy_and_transform_order(self):
        from noodles.backend.moves import evaluate_move
        source = grid()
        base = GraphEngine().evaluate([source]).results['grid']
        factors = DataTree((Branch((0,), (1, 2, 3)), Branch((1,), (4, 5, 6))))
        params = state('scale', {'Cp': True})
        out, model, _, effects = evaluate_move('scale', params,
            {'G': base.outputs['P'], 'F': factors}, base.bindings['P'], 'scale')
        self.assertEqual(model.parts.count, 6)
        self.assertEqual(out['F'].values(), factors.values())
        self.assertEqual([b.path for b in out['G'].branches], [(0,), (1,)])
        self.assertFalse(effects)

        move = NodeSpec('move', 'move', state('move', {'X': 3}), {'G': Connection('grid', 'G')})
        resize = NodeSpec('scale', 'scale', state('scale', {'F': 2}), {'G': Connection('move', 'G')})
        model = GraphEngine().evaluate([source, move, resize]).results['grid'].parametric_object
        self.assertEqual(model.parts.values()[0].motion.point((1, 0, 0)), (8., 0., 0.))
        self.assertEqual(object_from_wire(model.to_wire()), model)

    def test_mirror_line_in_work_plane_and_composition(self):
        from noodles.backend.moves import evaluate_move
        p = PointValue('p', (2, 3, 4))
        out, model, *_ = evaluate_move('mirror', state('mirror', {'K': True, 'P': 'XZ'}), {'G': p})
        self.assertEqual(out['G'].values()[0].xyz, (2., 3., -4.))
        self.assertEqual(model.parts.count, 1)
        with self.assertRaisesRegex(ValueError, 'direction along the work plane'):
            evaluate_move('mirror', state('mirror', {'E': [0, 0, 1]}), {'G': p})

        source = grid()
        resize = NodeSpec('scale', 'scale', state('scale', {'F': 2}), {'G': Connection('grid', 'G')})
        mirror = NodeSpec('mirror', 'mirror', state('mirror'), {'G': Connection('scale', 'G')})
        model = GraphEngine().evaluate([source, resize, mirror]).results['grid'].parametric_object
        self.assertEqual(model.parts.values()[0].motion.point((1, 2, 3)), (2., -4., 6.))
        self.assertEqual(object_from_wire(model.to_wire()), model)


class TransformNativeTests(unittest.TestCase):
    setUpClass = classmethod(native.NativeMoveTests.setUpClass.__func__)
    setUp = native.NativeMoveTests.setUp
    tearDown = native.NativeMoveTests.tearDown
    call = native.NativeMoveTests.call
    wait_for = native.NativeMoveTests.wait_for
    publish = native.NativeMoveTests.publish
    frame = native.NativeMoveTests.frame
    point_reference = native.NativeMoveTests.point_reference

    def test_scaled_grid_can_still_be_captured(self):
        from noodles.backend.grid_reference_native import inspect_grid
        source = grid()
        engine = GraphEngine()
        base = engine.evaluate([source]).results['grid'].parametric_object
        original = self.publish(base.to_wire())
        resize = NodeSpec('scale', 'scale', state('scale', {'F': 2}), {'G': Connection('grid', 'G')})
        model = engine.evaluate([source, resize]).results['grid'].parametric_object
        updated = self.publish(model.to_wire())
        self.assertEqual(updated.id, original.id)
        self.assertEqual(len(self.window.scene.objects), 1)
        inspected = inspect_grid(updated.shape, model.to_wire(), 'grid_rectangle')
        self.assertEqual(inspected.parts.values()[0].spacing, (20., 20.))

    def test_reference_changes_center_after_reopening_and_resets(self):
        from serpentine3d.fileio.native import load_scene, save_scene
        obj, source, _ = self.point_reference()
        resize = NodeSpec('scale', 'scale', state('scale', {'F': 2}), {'G': Connection('reference', 'P')})
        engine = GraphEngine()
        self.frame(engine.evaluate([source, resize]).reference_moves)
        self.assertEqual(self.geo.point_coords(self.window.scene.get(obj.id).shape), (2., 4., 6.))
        path = str(Path(self.folder.name) / 'scaled.serp')
        save_scene(self.window.scene, path)
        self.window.scene = self.Scene()
        load_scene(self.window.scene, path)
        refs = self.call('points.read', source.parameters)['references']
        source = replace(source, parameters={**source.parameters, 'references': refs})
        resize = replace(resize, parameters={**resize.parameters, 'parameters': {'C': [1, 0, 0], 'F': .5}})
        result = engine.evaluate([source, resize])
        self.frame(result.reference_moves)
        obj = self.window.scene.get(refs[0]['id'])
        self.assertEqual((obj.name, self.geo.point_coords(obj.shape)), ('Native point', (1., 1., 1.5)))
        service = GeometryService()
        service.sync_movements(result.reference_moves)
        service.sync_movements(())
        self.frame(service.motion_request['entries'])
        self.assertEqual(self.geo.point_coords(self.window.scene.get(obj.id).shape), (1., 2., 3.))

    def test_mirror_keep_creates_a_solid_with_the_native_reflection(self):
        from test_moves import PROJECT
        from uuid import uuid4
        from noodles.backend.solids import normalize_solid_state

        box = NodeSpec('box', 'box', normalize_solid_state('box', {
            'project_uuid': PROJECT, 'node_uuid': str(uuid4()), 'parameters': {'O': [1, 2, 3]},
        }))
        mirror = NodeSpec('mirror', 'mirror', state('mirror', {'K': True}), {'G': Connection('box', 'G')})
        results = GraphEngine().evaluate([box, mirror]).results
        original = self.publish(results['box'].parametric_object.to_wire())
        before = original._shape
        mirrored = self.publish(results['mirror'].parametric_object.to_wire())
        self.assertNotEqual(original.id, mirrored.id)
        self.assertIs(self.window.scene.get(original.id)._shape, before)
        self.assertEqual(len(self.window.scene.objects), 2)
        expected = self.geo.mirror(original.shape, (0, 0, 0), (0, 1, 0))
        self.assertAlmostEqual(self.geo.volume(mirrored.shape), self.geo.volume(expected))
        for actual, target in zip(self.geo.bbox(mirrored.shape), self.geo.bbox(expected)):
            for a, b in zip(actual, target):
                self.assertAlmostEqual(a, b)


class TransformUiTests(unittest.TestCase):
    setUpClass = classmethod(ui.MoveUiTests.setUpClass.__func__)
    setUp = ui.MoveUiTests.setUp
    tearDown = ui.MoveUiTests.tearDown
    settle = ui.MoveUiTests.settle

    def test_edit_factor_and_undo_from_properties(self):
        source = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        resize = self.window.add_node('NoodleS.Geometry.ScaleNode')
        source.outputs()['G'].connect_to(resize.inputs()['G'])
        self.settle()
        field = self.window.properties.curve_properties.editors['F'][0]
        field.setFocus()
        QTest.keyClick(field, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QTest.keyClicks(field, '2.5')
        QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[resize.id].outputs['F'].values(), (2.5,))
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(self.window.evaluation.results[resize.id].outputs['F'].values(), (1.,))

    def test_mirror_keep_from_properties(self):
        source = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        mirror = self.window.add_node('NoodleS.Geometry.MirrorNode')
        source.outputs()['G'].connect_to(mirror.inputs()['G'])
        self.settle()
        self.assertNotIn(mirror.id, self.window.point_service.models)
        keep = self.window.properties.curve_properties.editors['K'][0]
        QTest.mouseClick(keep, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, keep.height() // 2))
        self.settle()
        self.assertIn(mirror.id, self.window.point_service.models)
