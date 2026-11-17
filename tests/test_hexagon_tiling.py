"""Hexagonal coverage, seam continuity and native tessellation publication."""
import math
import unittest

import test_delaunay as fixture

from noodles.backend.curves import PlaneValue, polyline, rectangle
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.delaunay import polygon_area
from noodles.backend.delaunay_node import HEXAGON_TILING, evaluate, normalize_state, object_from_outputs
from noodles.backend.honeycomb import layout


class HexagonDataTests(unittest.TestCase):
    def test_concave_polygon_keeps_its_corners_and_area(self):
        boundary = [(0., 0.), (1., 0.), (1., .3), (.4, .3), (.4, 1.), (0., 1.)]
        vertices, cells, owners = layout(boundary, .123, 0., lambda: None)
        self.assertTrue(set(boundary) <= set(vertices))
        self.assertAlmostEqual(sum(polygon_area([vertices[i] for i in cell]) for cell in cells), .58)
        for cell, owner in zip(cells, owners):
            if owner[-1] is not None:
                # A concave boundary triangulation can leave collinear vertices.
                self.assertAlmostEqual(polygon_area([vertices[i] for i in cell]), .123**2 * math.sqrt(3)/2)

    def test_periodic_column_fit_pairs_every_seam_vertex(self):
        boundary = [(0., 0.), (1., 0.), (1., .75), (0., .75)]
        vertices, cells, owners = layout(boundary, .144, 1., lambda: None)
        left, right = (sorted(y for x, y in vertices if x == side) for side in (0., 1.))
        self.assertGreater(len(left), 3)
        self.assertEqual(left, right)
        self.assertAlmostEqual(sum(polygon_area([vertices[i] for i in cell]) for cell in cells), .75)
        self.assertTrue(any(wrap for _, _, wrap, _, _ in owners))
        for cell, owner in zip(cells, owners):
            if owner[-1] is not None:
                u = [vertices[i][0] for i in cell]
                self.assertAlmostEqual(max(u) - min(u), 1/7)
        with self.assertRaisesRegex(ValueError, 'Increase Cell Size'):
            layout(boundary, .0001, 1., lambda: None)


class HexagonNativeTests(unittest.TestCase):
    NativeFixture = fixture.DelaunayNativeTests
    setUpClass = classmethod(NativeFixture.setUpClass.__func__)
    setUp = NativeFixture.setUp
    tearDown = NativeFixture.tearDown
    call = NativeFixture.call
    wait_for = NativeFixture.wait_for
    publish = NativeFixture.publish

    def test_native_command_needs_no_editor(self):
        from types import SimpleNamespace
        from serpentine3d.commands.base import resolve
        from noodles.backend.tessellation_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        boundary = scene.add(self.geo.make_rectangle((0., 0., 0.), (17., 12., 0.)))
        messages = []
        command = resolve('hexagontiling').fn(SimpleNamespace(echo=messages.append))
        next(command)
        command.send('Periodic U')
        command.send([boundary])
        with self.assertRaises(StopIteration):
            command.send(3.2)
        self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
        self.assertEqual(len(scene.objects), 2)
        self.assertTrue(scene.all()[-1].mesh_ready)

    def test_two_branches_publish_one_native_owner(self):
        from noodles.backend.grid_reference_native import children

        state = normalize_state({**self.parameters, 'parameters': {'periodic_u': True}}, HEXAGON_TILING)
        inputs = {'B': DataTree((Branch((2, 0), (rectangle('small', 17., 10., (0., 0., 0.), PlaneValue()),)),
                                 Branch((2, 1), (rectangle('wide', 21., 9., (0., 0., 2.), PlaneValue()),)))),
                  'S': 3.2}
        request = evaluate(state, inputs, HEXAGON_TILING)['_sampling']
        job = self.call('geometry.tessellation', request)
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing', timeout=10)
        reply = self.call('geometry.job', job)
        self.assertEqual(reply['state'], 'complete', reply)
        state['sampling_details'] = {'signature': request['signature'], 'values': reply['measurements']}
        output = evaluate(state, inputs, HEXAGON_TILING)
        self.assertEqual([branch.path for branch in output['C'].branches], [(2, 0), (2, 1)])
        self.assertGreater(output['H'].count, 0)
        self.assertEqual(output['P'].count, output['H'].count)
        owner = self.publish(object_from_outputs(state, output).to_wire())
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(tuple(children(owner.shape))), output['Count'])
        self.assertTrue(all(self.geo.is_closed_curve(curve) for curve in children(owner.shape)))

    def test_only_a_rectangle_can_be_wrapped(self):
        from noodles.backend.scene_curves import materialize
        from noodles.backend.tessellation_native import hexagon_tiling

        boundary = materialize(polyline('triangle', ((0., 0., 0.), (8., 0., 0.), (0., 10., 0.)), True))
        with self.assertRaisesRegex(ValueError, 'rectangle'):
            hexagon_tiling(boundary, PlaneValue(), 2., True, lambda: None)

    def test_periodic_contours_map_to_cylinder_and_sphere(self):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.GeomAbs import GeomAbs_Cylinder
        from noodles.backend.map_surface_native import map_polygon
        from noodles.backend.scene_curves import materialize
        from noodles.backend.tessellation import contours
        from noodles.backend.tessellation_native import hexagon_tiling

        boundary = materialize(rectangle('uv', 18., 12., (0., 0., 0.), PlaneValue()))
        source = self.geo.planar_face(boundary)
        vertices, cells, _ = hexagon_tiling(source, PlaneValue(), 3.7, True, lambda: None)
        radius = 4.
        cylinder = self.geo.make_cylinder((0., 0., 0.), radius, 12.)
        shell = next(face for face in self.geo.faces_of(cylinder)
                     if BRepAdaptor_Surface(face).GetType() == GeomAbs_Cylinder)
        sphere = self.geo.make_sphere((0., 0., 0.), radius)
        for cell in contours(vertices, cells):
            for target, dimensions in ((shell, 2), (sphere, 3)):
                wire = map_polygon(cell, source, target)
                self.assertTrue(BRepCheck_Analyzer(wire).IsValid())
                for point in self.geo.sample_curve(wire, 3):
                    self.assertAlmostEqual(math.hypot(*point[:dimensions]), radius, delta=2e-6)


if __name__ == '__main__':
    unittest.main()
