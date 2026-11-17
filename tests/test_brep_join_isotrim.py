"""Native topology, UV trims and connected graph regressions."""
import math
import unittest

import test_operation_native as fixture
from noodles.backend.curves import PlaneValue
from noodles.backend.domain import DomainValue
from noodles.backend.isotrim_native import isotrim_shape
from noodles.backend.scene_curves import materialize
from noodles.backend.solids import SolidValue
from noodles.backend.surface_uv import Domain2Value, SurfaceUvView


class BrepJoinIsotrimTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeOperationTests.setUpClass.__func__)
    setUp = fixture.NativeOperationTests.setUp
    tearDown = fixture.NativeOperationTests.tearDown
    call = fixture.NativeOperationTests.call
    wait_for = fixture.NativeOperationTests.wait_for
    publish = fixture.NativeOperationTests.publish
    model = fixture.NativeOperationTests.model

    def test_both_joins_hide_their_sources_through_merge_and_restore_them_on_undo(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(kind):
                return editor.add_node(f'NoodleS.{kind}Node')

            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))

            merge = add('Data.Merge')
            surfaces = []
            for port, center in (('A', 0), ('B', 10)):
                rectangle = add('Geometry.Rectangle')
                rectangle.set_property('parameters', {'C': [center, 0, 0]})
                surface = add('Geometry.PlanarSurface')
                rectangle.outputs()['C'].connect_to(surface.inputs()['C'])
                surface.outputs()['G'].connect_to(merge.inputs()[port])
                surfaces.append(surface)

            for kind, port in (('Join', 'G'), ('BrepJoin', 'B')):
                with self.subTest(kind=kind):
                    join = add(f'Geometry.{kind}')
                    merge.outputs()['D'].connect_to(join.inputs()[port])
                    move = add('Geometry.Move')
                    move.set_property('parameters', {'X': 20})
                    join.outputs()[port].connect_to(move.inputs()['G'])
                    editor.graph.clear_selection()
                    join.set_selected(True)
                    checkbox = editor.properties.curve_properties.show_parent
                    self.wait_for(lambda: checkbox.isVisible() and owner(join) is not None
                                  and self.geo.bbox(owner(join).shape)[0][0] > 14.9
                                  and all(owner(node) is not None for node in surfaces))
                    joined = owner(join)
                    self.assertTrue(checkbox.isChecked())
                    self.assertTrue(all(owner(node).visible for node in surfaces))

                    QTest.mouseClick(checkbox, QtCore.Qt.LeftButton,
                                     pos=QtCore.QPoint(7, checkbox.height() // 2))
                    self.wait_for(lambda: all(not owner(node).visible for node in surfaces))
                    self.assertEqual(owner(join).id, joined.id)
                    self.assertTrue(owner(join).visible)
                    editor.graph.undo_stack().undo()
                    self.wait_for(lambda: all(owner(node).visible for node in surfaces))
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_brep_join_graph_closes_box_and_passes_unattached_parts(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        try:
            def add(name):
                return editor.add_node(f'NoodleS.Geometry.{name}Node')
            box, deconstruct, join = map(add, ('Box', 'DeconstructBrep', 'BrepJoin'))
            box.outputs()['G'].connect_to(deconstruct.inputs()['B'])
            deconstruct.outputs()['F'].connect_to(join.inputs()['B'])
            identity = editor.project_uuid, join.curve_state()['node_uuid'], 0
            self.wait_for(lambda: self.bridge.points.owner(identity) is not None)
            owner = self.bridge.points.owner(identity)
            self.assertEqual(editor.evaluation.results[join.id].outputs['C'].values(), (True,))
            self.assertAlmostEqual(self.geo.volume(owner.shape), 1000.)
            self.assertEqual(sum(obj.name == 'Brep Join' for obj in self.window.scene.all()), 1)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

        from noodles.backend.topology_native import brep_join_shapes
        g = self.geo
        a = g.planar_face(g.make_rectangle((0, 0, 0), (5, 5, 0)))
        b = g.planar_face(g.make_rectangle((5, 0, 0), (10, 5, 0)))
        loose = g.planar_face(g.make_rectangle((20, 0, 0), (25, 5, 0)))
        solid = g.make_box((30, 0, 0), 2, 3, 4)
        parts = brep_join_shapes([a, b, loose, solid])
        self.assertEqual(sorted(len(g.faces_of(p)) for p in parts), [1, 2, 6])
        self.assertEqual(sum(g.shape_kind(p) == 'solid' for p in parts), 1)

    def test_isotrim_honors_reparameterized_cylinder_and_original_hole(self):
        from noodles.backend.surface_native import planar_surface_shape

        cylinder = SolidValue('cyl', 'cylinder', PlaneValue(), (5, 10), False)
        unit = DomainValue(0, 1)
        view = SurfaceUvView(cylinder, 0, Domain2Value(unit, unit))
        domain = Domain2Value(DomainValue(0, .25), DomainValue(.2, .6))
        owner = self.publish(self.model('isotrim', {'S': view, 'D': domain}))
        self.assertAlmostEqual(self.geo.surface_area(owner.shape), 10 * math.pi, places=5)
        low, high = self.geo.bbox(owner.shape)
        self.assertAlmostEqual(low[2], 2, places=5)
        self.assertAlmostEqual(high[2], 6, places=5)

        g = self.geo
        outline = g.make_rectangle((0, 0, 0), (10, 10, 0))
        hole = g.make_circle((5, 5, 0), 1.)
        face = planar_surface_shape([outline, hole])
        patch = isotrim_shape(face, (-3, 3, -3, 3))
        self.assertAlmostEqual(g.surface_area(patch), 36 - math.pi, places=5)
        with self.assertRaisesRegex(ValueError, 'does not contain'):
            isotrim_shape(face, (-.2, .2, -.2, .2))
        with self.assertRaisesRegex(ValueError, 'outside'):
            isotrim_shape(materialize(cylinder), (-1, 1, 1, 3))

    def test_native_commands_publish_without_editor(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.isotrim_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        cylinder = SolidValue('cyl', 'cylinder', PlaneValue(), (5, 10), False)
        source = scene.add(materialize(cylinder))
        context = SimpleNamespace(echo=lambda _: None)
        action = base.resolve('isotrimparam').fn(context)
        next(action)
        for value in ([source], 0, 0, math.pi/2, 2):
            action.send(value)
        with self.assertRaises(StopIteration):
            action.send(6)
        self.wait_for(lambda: len(scene.all()) == 2)
        trimmed = scene.all()[-1]
        self.assertAlmostEqual(self.geo.surface_area(trimmed.shape), 10 * math.pi, places=5)
        action = base.resolve('brepjoinparam').fn(context)
        next(action)
        with self.assertRaises(StopIteration):
            action.send([trimmed])
        self.wait_for(lambda: len(scene.all()) == 3)
        self.assertAlmostEqual(self.geo.surface_area(scene.all()[-1].shape), 10 * math.pi, places=5)

    def test_uv_panels_publish_once_and_update_cylinder_from_properties(self):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.backend.point import object_from_wire
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            cylinder = editor.add_node('NoodleS.Geometry.CylinderNode')
            cylinder.set_property('parameters', {'R': 5, 'H': 10, 'S': False})
            panels = editor.add_node('NoodleS.Operations.UVPanelsNode')
            panels.set_property('parameters', {'U': 4, 'V': 3})
            cylinder.outputs()['G'].connect_to(panels.inputs()['S'])
            identity = editor.project_uuid, panels.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=10)
            original = owner()
            self.assertEqual(len(self.geo.faces_of(original.shape)), 12)
            self.assertAlmostEqual(self.geo.surface_area(original.shape), 100 * math.pi)
            wire = editor.point_service.models[panels.id]['model']
            self.assertEqual(len(wire['sources']), 1)
            self.assertEqual(object_from_wire(wire).to_wire(), wire)
            self.assertTrue(BRepCheck_Analyzer(original.shape).IsValid())
            field = editor.properties.curve_properties.editors['U'][0]
            field.setFocus()
            field.selectAll()
            QTest.keyClicks(field, '6')
            QTest.keyClick(field, Qt.Key_Return)
            self.wait_for(lambda: len(self.geo.faces_of(owner().shape)) == 18, timeout=10)
            self.assertEqual(owner().id, original.id)
            self.assertEqual(editor.evaluation.results[panels.id].outputs['Count'], 18)
            self.assertEqual(len(self.window.scene.all()), 2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_uv_panels_keep_holes_and_skip_empty_cells(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.isotrim_native import build_uv_panels, register_commands
        from noodles.backend.surface_native import planar_surface_shape
        from noodles.backend.surface_structure import evaluate
        from noodles.backend.surface_uv import SurfaceUvView

        g = self.geo
        outer = g.make_rectangle((0, 0, 0), (10, 10, 0))
        hole = g.make_circle((5, 5, 0), 3)
        face = planar_surface_shape([outer, hole])
        panels = tuple(build_uv_panels(face, 0, 5, 5))
        self.assertEqual(len(panels), 24)
        self.assertNotIn((2, 2), [(i, j) for i, j, _, _ in panels])
        self.assertAlmostEqual(sum(g.surface_area(part) for _, _, _, part in panels), 100 - 9 * math.pi)
        box = SolidValue('box', 'box', PlaneValue(), (5, 5, 5))
        view = SurfaceUvView(box, 2, Domain2Value(DomainValue(0, 1), DomainValue(0, 1)))
        pending = evaluate('uv_panels', {}, {'S': view, 'U': 2, 'V': 2})
        self.assertEqual(pending['_sampling']['plan']['rows'][0]['face'], 2)
        with self.assertRaisesRegex(ValueError, '1,024'):
            evaluate('uv_panels', {}, {'S': view, 'U': 33, 'V': 33})
        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        source = self.window.scene.add(face)
        command = base.resolve('uvpanels').fn(SimpleNamespace(echo=lambda _: None))
        next(command)
        for value in ([source], 0, 5):
            command.send(value)
        with self.assertRaises(StopIteration):
            command.send(5)
        self.wait_for(lambda: len(self.window.scene.all()) == 2)
        result = self.window.scene.all()[-1].shape
        self.assertEqual(len(g.faces_of(result)), sum(len(g.faces_of(part)) for _, _, _, part in panels))
        self.assertAlmostEqual(g.surface_area(result), 100 - 9 * math.pi)
