"""Surface cages and mapped modules through native OCC and the editor."""
import unittest

import test_point_native as fixture


class BoxMorphTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    wait_for = fixture.NativePointTests.wait_for

    def test_trims_seam_and_curves(self):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCP.GeomAbs import GeomAbs_Cylinder
        from noodles.backend.box_morph_native import box_morph_shape, build_surface_boxes
        from noodles.backend.curves import PlaneValue
        from noodles.backend.surface_native import planar_surface_shape

        g = self.geo
        face = planar_surface_shape([g.make_rectangle((0, 0, 0), (10, 10, 0)),
                                     g.make_circle((5, 5, 0), .5)])
        # All four corners of the center cell lie on the face. Its hole still
        # prevents a box, because containment checks the entire cell.
        tiles = tuple(build_surface_boxes(face, 0, 5, 5, 1))
        self.assertEqual(len(tiles), 24)
        self.assertNotIn((2, 2), {(i, j) for i, j, _ in tiles})

        cylinder = BRepPrimAPI_MakeCylinder(10., 12.).Shape()
        shell = next(f for f in g.faces_of(cylinder) if BRepAdaptor_Surface(f).GetType() == GeomAbs_Cylinder)
        boxes = tuple(build_surface_boxes(shell, 0, 8, 2, 1))
        self.assertEqual(len(boxes), 16)
        first, last = boxes[0][2], boxes[7][2]
        self.assertEqual(tuple(first[i] for i in (0, 3, 4, 7)), tuple(last[i] for i in (1, 2, 5, 6)))
        self.assertFalse(tuple(build_surface_boxes(shell, 0, 1, 2, 1)))

        source = BRepPrimAPI_MakeBox(2., 3., 1.).Shape()
        frame = PlaneValue()
        solid = box_morph_shape(source, source, frame, first)
        self.assertEqual(g.shape_kind(solid), 'solid')
        self.assertGreater(g.volume(solid), 0.)
        curve = box_morph_shape(g.make_circle((1, 1, 0), .5), source, frame, first)
        self.assertEqual(g.shape_kind(curve), 'curve')
        self.assertTrue(BRepCheck_Analyzer(curve).IsValid())

    def test_graph_publishes_two_owners_and_reuses_ids_after_height_edit(self):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        try:
            def add(name, category='Operations'):
                return editor.add_node(f'NoodleS.{category}.{name}Node')
            def wire(node, out, other, port):
                node.outputs()[out].connect_to(other.inputs()[port])
            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))
            cylinder, source = add('Cylinder', 'Geometry'), add('Box', 'Geometry')
            bounds = add('BoundingBox', 'Geometry')
            cages, morph = add('SurfaceBox'), add('BoxMorph')
            cylinder.set_property('parameters', {'R': 10, 'H': 12, 'S': False})
            cages.set_property('parameters', {'U': 6, 'V': 2, 'H': 1.})
            wire(source, 'G', bounds, 'C')
            wire(source, 'G', morph, 'G')
            wire(bounds, 'B', morph, 'R')
            wire(cylinder, 'G', cages, 'S')
            wire(cages, 'B', morph, 'T')
            self.wait_for(lambda: owner(morph) is not None and owner(cages) is not None, timeout=15)
            cage_before, morph_before = owner(cages), owner(morph)
            self.assertEqual(len(self.window.scene.all()), 5)
            first_result = editor.evaluation.results[morph.id]
            self.assertEqual(first_result.parametric_object.parts.count, 12)
            first_keys = first_result.outputs['G'].branches[0].keys
            solids = TopExp_Explorer(morph_before.shape, TopAbs_SOLID)
            count = 0
            while solids.More():
                self.assertTrue(BRepCheck_Analyzer(solids.Current()).IsValid())
                count += 1
                solids.Next()
            self.assertEqual(count, 12)
            cages.set_property('parameters', {'U': 6, 'V': 2, 'H': 2.})
            self.wait_for(lambda: owner(morph).shape is not morph_before.shape
                          and owner(cages).shape is not cage_before.shape, timeout=15)
            self.assertEqual((owner(cages).id, owner(morph).id), (cage_before.id, morph_before.id))
            self.assertEqual(editor.evaluation.results[morph.id].outputs['G'].branches[0].keys, first_keys)
            self.assertGreater(self.geo.volume(owner(morph).shape), self.geo.volume(morph_before.shape))
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_native_commands_without_editor(self):
        from types import SimpleNamespace
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from serpentine3d.commands import base
        from noodles.backend.box_morph_native import register_commands
        from noodles.backend.curves import PlaneValue

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        g = self.geo
        scene = self.window.scene
        face = scene.add(g.planar_face(g.make_rectangle((0, 0, 0), (4, 6, 0))))
        source = scene.add(BRepPrimAPI_MakeBox(1., 1., 1.).Shape())
        frame = PlaneValue()
        context = SimpleNamespace(echo=lambda _: None, cplane=SimpleNamespace(
            origin=frame.origin, xdir=frame.axis_x, normal=frame.normal))
        action = base.resolve('surfacebox').fn(context)
        next(action)
        for value in ([face], 0, 2, 3):
            action.send(value)
        with self.assertRaises(StopIteration):
            action.send(1.)
        self.wait_for(lambda: len(scene.all()) == 3)
        self.assertEqual(len(g.edges_of(scene.all()[-1].shape)), 72)
        corners = ((0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0),
                   (0, 0, 2), (2, 0, 2), (2, 3, 2), (0, 3, 2))
        action = base.resolve('boxmorph').fn(context)
        next(action)
        for value in ([source], *corners[:-1]):
            action.send(value)
        with self.assertRaises(StopIteration):
            action.send(corners[-1])
        self.wait_for(lambda: len(scene.all()) == 4)
        self.assertAlmostEqual(g.volume(scene.all()[-1].shape), 12.)
