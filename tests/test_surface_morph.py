"""Exercise the book's relief workflow through the editor, TCP bridge and OCC."""
import math
from types import SimpleNamespace
import unittest

import test_point_native as fixture


class SurfaceMorphTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    wait_for = fixture.NativePointTests.wait_for

    def profile(self):
        from noodles.backend.operation_native import extrude_shape
        from noodles.backend.surface_native import planar_surface_shape

        outer = self.geo.make_rectangle((1, 1.5, 0), (9, 6.5, 0))
        hole = self.geo.make_circle((5, 4, 0), 1)
        return extrude_shape(planar_surface_shape([outer, hole]), (0, 0, 1), True)

    def check_relief(self, shape, thickness):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.TopAbs import TopAbs_IN, TopAbs_OUT
        from OCP.gp import gp_Pnt

        self.assertEqual(self.geo.shape_kind(shape), 'solid')
        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
        low, high = self.geo.bbox(shape)
        self.assertAlmostEqual(low[2], 5., places=5)
        self.assertAlmostEqual(high[2], 12.25, places=5)
        self.assertAlmostEqual(high[0], 10+thickness, places=5)
        solid = self.geo.unwrap_compound(shape)
        radius = 10+thickness/2
        def state(angle):
            point = gp_Pnt(radius*math.cos(angle), radius*math.sin(angle), 8.625)
            return BRepClass3d_SolidClassifier(solid, point, 1e-6).State()
        self.assertEqual(state(.63), TopAbs_OUT)  # The hole survives the morph.
        self.assertEqual(state(.15), TopAbs_IN)

    def test_book_graph_from_a_referenced_solid_updates_one_owner(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        scene = self.window.scene
        source = scene.add(self.profile(), name='Source profile')
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(name):
                return editor.add_node(f'NoodleS.Geometry.{name}Node')
            def connect(node, out, other, port):
                node.outputs()[out].connect_to(other.inputs()[port])
            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))
            reference = add('Loft')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: panel.sources['reference'].isVisible())
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            self.wait_for(panel.capture.isVisible)
            QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(reference.get_property('references')) == 1)
            bounds, morph, cylinder = map(add, ('BoundingBox', 'SurfaceMorph', 'Cylinder'))
            cylinder.set_property('parameters', {'R': 10, 'H': 20, 'S': False})
            connect(reference, 'G', bounds, 'C')
            connect(reference, 'G', morph, 'G')
            connect(bounds, 'B', morph, 'R')
            connect(cylinder, 'G', morph, 'S')
            domains = {}
            for axis, (low, high) in zip('UVW', ((0, 1.26), (5, 12.25), (0, .72))):
                domain = editor.add_node('NoodleS.Math.DomainNode')
                domain.set_property('start', low)
                domain.set_property('end', high)
                connect(domain, 'D', morph, axis)
                domains[axis] = domain
            self.wait_for(lambda: all(owner(node) is not None for node in (bounds, morph, cylinder)), timeout=12)
            before = owner(morph)
            self.check_relief(before.shape, .72)
            self.assertEqual(len(editor.evaluation.results[morph.id].parametric_object.parts.values()), 1)
            self.assertEqual(len(scene.all()), 4)
            domains['W'].set_property('end', 1.2)
            self.wait_for(lambda: owner(morph).shape is not before.shape, timeout=12)
            self.assertEqual(owner(morph).id, before.id)
            self.check_relief(owner(morph).shape, 1.2)
            self.assertIsNotNone(scene.get(source.id))

            divide = editor.add_node('NoodleS.Operations.DivideDomain2Node')
            deconstruct = editor.add_node('NoodleS.Operations.DeconstructDomain2Node')
            divide.set_property('parameters', {'U': 3, 'V': 2})
            connect(cylinder, 'G', divide, 'I')
            connect(divide, 'S', deconstruct, 'I')
            for axis in 'UV':
                domains[axis].outputs()['D'].disconnect_from(morph.inputs()[axis])
                connect(deconstruct, axis, morph, axis)
            from OCP.TopAbs import TopAbs_SOLID
            from OCP.TopExp import TopExp_Explorer
            def solids():
                result = owner(morph)
                if result is None:
                    return []
                items = []
                explorer = TopExp_Explorer(result.shape, TopAbs_SOLID)
                while explorer.More():
                    items.append(explorer.Current())
                    explorer.Next()
                return items
            self.wait_for(lambda: len(solids()) == 6, timeout=12)
            self.assertEqual(owner(morph).id, before.id)
            self.assertTrue(all(self.geo.volume(solid) > 0 for solid in solids()))
            self.assertEqual(editor.evaluation.results[divide.id].outputs['S'].count, 6)
            self.assertIsNone(editor.evaluation.results[divide.id].parametric_object)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_oriented_union_preserves_branches_and_bounds(self):
        from noodles.backend.curves import PlaneValue
        from noodles.backend.datatree import Branch, DataTree
        from noodles.backend.morph_native import _bounds
        from noodles.backend.operations import evaluate_operation
        from noodles.backend.scene_curves import materialize
        from noodles.backend.solids import SolidValue

        frame = PlaneValue((7, -3, 2), (1, 1, 0))
        first = SolidValue('first', 'box', frame, (8, 3, 2))
        second = SolidValue('second', 'box', PlaneValue(frame.at(10, 0), frame.axis_x), (2, 4, 2))
        tree = DataTree((Branch((2,), (first, second)), Branch((5, 1), (first,))))
        inputs = {'C': tree, 'P': frame}
        boxes = evaluate_operation('bounding_box', self.parameters, inputs)['B']
        self.assertEqual(tuple(len(b.items) for b in boxes.branches), (2, 1))
        union = evaluate_operation('bounding_box', {**self.parameters, 'parameters': {
            'box_mode': 'union'}}, inputs)['B']
        self.assertEqual(tuple(b.path for b in union.branches), ((2,), (5, 1)))
        self.assertEqual(tuple(len(b.items) for b in union.branches), (1, 1))
        low, high = _bounds((materialize(union.values()[0]),), frame)
        for expected, actual in zip((0, 0, 0, 12, 4, 2), (*low, *high)):
            self.assertAlmostEqual(expected, actual, places=6)

    def test_book_folded_panels_alternate_in_144_uv_cells(self):
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.BRepCheck import BRepCheck_Analyzer
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow
        from noodles.backend.grid_reference_native import children

        g = self.geo
        ridge = [(4, 0, 2), (4, 5, 2)]
        first = [(0, 0, 0), *ridge, (0, 5, 0)]
        second = [ridge[0], (8, 0, 0), (8, 5, 0), ridge[1]]
        source = self.window.scene.add(g.join_surfaces([
            g.planar_face(g.make_polyline(outline, closed=True)) for outline in (first, second)]))
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(name, category='Geometry'):
                return editor.add_node(f'NoodleS.{category}.{name}Node')
            def link(a, out, b, port):
                a.outputs()[out].connect_to(b.inputs()[port])
            ref = add('Loft')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: panel.sources['reference'].isVisible())
            QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
            QTest.mouseClick(panel.capture, QtCore.Qt.LeftButton)
            self.wait_for(lambda: len(ref.get_property('references')) == 1)
            duplicate, dispatch, weave = (add(name, 'Data') for name in ('DuplicateData', 'Dispatch', 'Weave'))
            xy, w = (add(name, 'Math') for name in ('XYPlane', 'Domain'))
            mirror, box, cylinder, morph = map(add, ('Mirror', 'BoundingBox', 'Cylinder', 'SurfaceMorph'))
            divide, deconstruct = (add(name, 'Operations') for name in ('DivideDomain2', 'DeconstructDomain2'))
            duplicate.set_property('parameters', {'N': 144})
            divide.set_property('parameters', {'U': 16, 'V': 9})
            box.set_property('parameters', {'box_mode': 'union'})
            cylinder.set_property('parameters', {'R': 10, 'H': 20, 'S': False})
            for a, out, b, port in (
                (ref, 'G', duplicate, 'D'), (duplicate, 'D', dispatch, 'L'),
                (dispatch, 'B', mirror, 'G'), (xy, 'P', mirror, 'M'),
                (dispatch, 'A', weave, '0'), (mirror, 'G', weave, '1'),
                (weave, 'W', box, 'C'), (weave, 'W', morph, 'G'),
                (box, 'B', morph, 'R'), (cylinder, 'G', morph, 'S'),
                (cylinder, 'G', divide, 'I'), (divide, 'S', deconstruct, 'I'),
                (deconstruct, 'U', morph, 'U'), (deconstruct, 'V', morph, 'V'),
                (w, 'D', morph, 'W'),
            ):
                link(a, out, b, port)
            identity = editor.project_uuid, morph.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=20)
            parts = tuple(children(owner().shape))
            self.assertEqual(len(parts), 144)
            self.assertEqual(sum(obj.name == 'Surface Morph' for obj in self.window.scene.all()), 1)
            self.assertTrue(all(len(g.faces_of(p)) == 2 and BRepCheck_Analyzer(p).IsValid() for p in parts))
            for index, radius in ((0, 11), (1, 10), (143, 10)):
                angle = (index % 16 + .5) * math.tau / 16
                height = (index // 16 + .5) * 20 / 9
                ridge_point = g.make_point((radius * math.cos(angle), radius * math.sin(angle), height))
                self.assertLess(BRepExtrema_DistShapeShape(ridge_point, parts[index]).Value(), 1e-5)
            self.assertEqual(len(g.faces_of(source.shape)), 2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_native_commands_use_the_same_factories(self):
        from noodles.backend.curves import PlaneValue
        from noodles.backend.morph_native import register_commands
        from noodles.backend.scene_curves import materialize
        from noodles.backend.solids import SolidValue
        from serpentine3d.commands import base

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        source = scene.add(self.profile())
        target = scene.add(materialize(SolidValue('target', 'cylinder', PlaneValue(), (10, 20), False)))
        messages = []
        context = SimpleNamespace(echo=messages.append, cplane=SimpleNamespace(
            origin=(0, 0, 0), xdir=(1, 0, 0), normal=(0, 0, 1)))
        command = base.resolve('boundingboxparam').fn(context)
        next(command)
        command.send([source])
        with self.assertRaises(StopIteration):
            command.send('Per Object')
        self.wait_for(lambda: len(scene.all()) == 3)
        command = base.resolve('surfacemorphparam').fn(context)
        next(command)
        command.send([source])
        command.send([target])
        command.send('Custom UVW')
        for value in (0, 1.26, 5, 12.25, 0):
            command.send(value)
        with self.assertRaises(StopIteration):
            command.send(.72)
        self.wait_for(lambda: len(scene.all()) == 4 or any('Surface Morph:' in msg for msg in messages))
        self.assertEqual(len(scene.all()), 4, messages)
        self.check_relief(scene.all()[-1].shape, .72)
