"""OCC topology, braced-grid trims and the connected Qt graph."""
import math
import unittest

from test_point_native import NativePointTests as NativeFixture
from noodles.backend.point import object_from_wire
from noodles.backend.surface_structure_native import braced_grid, brep_parts, brep_vertices


class SurfaceStructureTests(unittest.TestCase):
    setUpClass = classmethod(NativeFixture.setUpClass.__func__)
    setUp = NativeFixture.setUp
    tearDown = NativeFixture.tearDown
    call = NativeFixture.call
    wait_for = NativeFixture.wait_for

    def test_unique_native_topology_and_trimmed_uv_members(self):
        from noodles.backend.surface_native import planar_surface_shape
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder

        box = BRepPrimAPI_MakeBox(3., 4., 5.).Shape()
        parts, faces = brep_parts(box)
        self.assertEqual((faces, len(parts) - faces, len(brep_vertices(box))), (6, 12, 8))

        outer = self.geo.make_rectangle((0, 0, 0), (10, 10, 0))
        hole = self.geo.make_rectangle((4, 4, 0), (6, 6, 0))
        face = self.geo.faces_of(planar_surface_shape([outer]))[0]
        parts, faces = brep_parts(face)
        self.assertEqual((faces, len(parts) - faces, len(brep_vertices(face))), (1, 4, 4))
        points, primary, braces = braced_grid(face, 2, 3)
        self.assertEqual((len(points), len(primary), len(braces)), (12, 17, 6))

        trimmed = self.geo.faces_of(planar_surface_shape([outer, hole]))[0]
        points, primary, braces = braced_grid(trimmed, 2, 2)
        self.assertLess(len(braces), 4)
        for i, j in primary + braces:
            for t in (.25, .5, .75):
                x, y, _ = (a + (b-a)*t for a, b in zip(points[i], points[j]))
                self.assertFalse(4 < x < 6 and 4 < y < 6)

        cyl = self.geo.faces_of(BRepPrimAPI_MakeCylinder(10., 20.).Shape())[0]
        points, primary, braces = braced_grid(cyl, 8, 4)
        used = {p for pair in primary + braces for p in pair}
        self.assertEqual((len(used), len(primary), len(braces)), (40, 72, 32))
        self.assertTrue(all(math.isclose(math.hypot(*points[i][:2]), 10.) for i in used))

    def test_loft_graph_feeds_braced_grid_and_keeps_one_owner(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        try:
            def add(name):
                return editor.add_node('NoodleS.Geometry.' + name + 'Node')

            lower, upper = add('Circle'), add('Circle')
            upper.set_property('parameters', {**upper.curve_state()['parameters'], 'C': [0, 0, 20], 'R': 7})
            merge = editor.add_node('NoodleS.Data.MergeNode')
            lower.outputs()['C'].connect_to(merge.inputs()['A'])
            upper.outputs()['C'].connect_to(merge.inputs()['B'])
            loft, deconstruct, grid = add('Loft'), add('DeconstructBrep'), add('BracedGrid1DStructure')
            merge.outputs()['D'].connect_to(loft.inputs()['C'])
            loft.outputs()['G'].connect_to(deconstruct.inputs()['B'])
            deconstruct.outputs()['F'].connect_to(grid.inputs()['S'])
            grid.set_property('parameters', {'U': 6, 'V': 4})
            scene = self.window.scene
            label = 'Braced Grid 1-D Structure'
            owner = lambda: next((o for o in scene.all() if o.name == label), None)
            self.wait_for(lambda: owner() is not None, timeout=10)
            self.assertFalse(any(o.name == 'Deconstruct Brep' for o in scene.all()))
            result = editor.evaluation.results[deconstruct.id]
            self.assertEqual(result.outputs['F'].count, 1)
            self.assertIsNone(result.parametric_object)
            result = editor.evaluation.results[grid.id]
            self.assertEqual(set(result.outputs), {'A', 'B', 'N'})
            model = result.parametric_object
            self.assertEqual(model.parts.count, result.outputs['A'].count + result.outputs['B'].count)
            self.assertEqual(len(self.geo.edges_of(owner().shape)), model.parts.count)
            self.assertEqual(object_from_wire(model.to_wire()), model)
            self.assertEqual(set(result.bindings), {'A', 'B'})
            before_id, before_shape = owner().id, owner().shape
            grid.set_property('parameters', {'U': 8, 'V': 4})
            self.wait_for(lambda: owner().shape is not before_shape, timeout=10)
            self.assertEqual(owner().id, before_id)
            self.assertEqual(sum(o.name == label for o in scene.all()), 1)
            box = add('Box')
            loft.outputs()['G'].disconnect_from(deconstruct.inputs()['B'])
            box.outputs()['G'].connect_to(deconstruct.inputs()['B'])
            grid.set_property('parameters', {'U': 2, 'V': 3})
            self.wait_for(lambda: len(self.geo.edges_of(owner().shape)) == 6 * 23, timeout=10)
            self.assertEqual(owner().id, before_id)
            result = editor.evaluation.results[grid.id]
            self.assertEqual(tuple(len(b.items) for b in result.outputs['B'].branches), (6,) * 6)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_native_command_creates_one_compound_without_editor(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.surface_structure_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        face = scene.add(self.geo.planar_face(self.geo.make_rectangle((0, 0, 0), (10, 20, 0))))
        command = base.resolve('bracedgrid1d').fn(SimpleNamespace(echo=lambda _: None))
        next(command)
        command.send([face])
        command.send(2)
        with self.assertRaises(StopIteration):
            command.send(3)
        self.wait_for(lambda: len(scene.all()) == 2)
        self.assertEqual(len(self.geo.edges_of(scene.all()[-1].shape)), 23)
