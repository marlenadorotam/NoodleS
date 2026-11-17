"""Voronoi coverage, seams and the native publication path."""
import math
import unittest

import test_delaunay as fixture
from noodles.backend.delaunay import polygon_area
from noodles.backend.voronoi import cells


class VoronoiDataTests(unittest.TestCase):
    def test_rectangle_periodic_seam_and_true_nearest_site(self):
        outline = [(0., 0.), (1., 0.), (1., .6), (0., .6)]
        sites = [p[:2] for p in fixture.cloud(100, 1., .6)]
        vertices, faces, owners = cells(sites, outline, 1., lambda: None)
        self.assertTrue(set(outline) <= set(vertices))
        left, right = (sorted(y for x, y in vertices if x == side) for side in (0., 1.))
        self.assertEqual(left, right)
        self.assertGreater(len(faces), len(sites))
        for face, (owner, _) in zip(faces, owners):
            for i in face:
                x, y = vertices[i]
                def distance(seed):
                    dx = abs(x - seed[0])
                    return min(dx, 1.-dx)**2 + (y-seed[1])**2
                self.assertAlmostEqual(distance(sites[owner]), min(map(distance, sites)), delta=2e-10)
        self.assertAlmostEqual(sum(polygon_area([vertices[i] for i in face]) for face in faces), .6)
        with self.assertRaisesRegex(ValueError, 'coincident'):
            cells([(0., .2), (1., .2)], outline, 1., lambda: None)
        _, single, _ = cells([(.2, .3)], outline, 1., lambda: None)
        self.assertEqual(len(single), 1)

    def test_concave_boundary_can_split_one_cell_into_two_contours(self):
        outline = [(0., 0.), (1., 0.), (1., 1.), (.65, 1.), (.65, .3), (.35, .3), (.35, 1.), (0., 1.)]
        sites = [(.34, .9), (.34, .2)]
        vertices, faces, owners = cells(sites, outline, 0., lambda: None)
        self.assertEqual([i for i, _ in owners], [0, 0, 1])
        self.assertTrue(set(outline) <= set(vertices))
        self.assertAlmostEqual(sum(polygon_area([vertices[i] for i in face]) for face in faces), .79)


class VoronoiNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.DelaunayNativeTests.setUpClass.__func__)
    setUp = fixture.DelaunayNativeTests.setUp
    tearDown = fixture.DelaunayNativeTests.tearDown
    call = fixture.DelaunayNativeTests.call
    wait_for = fixture.DelaunayNativeTests.wait_for
    publish = fixture.DelaunayNativeTests.publish

    def test_periodic_1800_sites_publish_as_one_parametric_object(self):
        from noodles.backend.curves import PlaneValue, rectangle
        from noodles.backend.delaunay_node import VORONOI, evaluate, normalize_state, object_from_outputs
        from noodles.backend.point import PointValue

        state = normalize_state({**self.parameters, 'parameters': {'periodic_u': True}}, VORONOI)
        inputs = {'P': [PointValue(str(i), p) for i, p in enumerate(fixture.cloud(1800))],
                  'B': rectangle('boundary', 20, 12, (10, 6, 0), PlaneValue())}
        request = evaluate(state, inputs, VORONOI)['_sampling']
        job = self.call('geometry.tessellation', request)
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing', timeout=10)
        reply = self.call('geometry.job', job)
        self.assertEqual(reply['state'], 'complete', reply)
        state['sampling_details'] = {'signature': request['signature'], 'values': reply['measurements']}
        output = evaluate(state, inputs, VORONOI)
        self.assertGreater(output['Count'], 1800)
        owner = self.publish(object_from_outputs(state, output).to_wire())
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertTrue(owner.mesh_ready)

    def test_populate_voronoi_map_surface_and_update_one_owner(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.backend.grid_reference_native import children
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(kind):
                return editor.add_node(f'NoodleS.Geometry.{kind}Node')

            rectangle, planar, populate, cylinder, mapping, voronoi = map(add, (
                'Rectangle', 'PlanarSurface', 'Populate2D', 'Cylinder', 'MapSurface', 'Voronoi'))
            cylinder.set_property('parameters', {'R': 5., 'H': 12., 'S': False})
            populate.set_property('parameters', {'N': 50})
            rectangle.outputs()['C'].connect_to(populate.inputs()['R'])
            rectangle.outputs()['C'].connect_to(planar.inputs()['C'])
            planar.outputs()['G'].connect_to(voronoi.inputs()['B'])
            planar.outputs()['G'].connect_to(mapping.inputs()['S'])
            populate.outputs()['P'].connect_to(voronoi.inputs()['P'])
            cylinder.outputs()['G'].connect_to(mapping.inputs()['T'])
            voronoi.outputs()['C'].connect_to(mapping.inputs()['C'])
            box = editor.properties.curve_properties.periodic_u
            self.wait_for(box.isVisible)
            self.assertFalse(box.isChecked())
            QTest.mouseClick(box, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, box.height()//2))
            self.assertTrue(voronoi.curve_state()['parameters']['periodic_u'])

            def owner(node):
                identity = editor.project_uuid, node.curve_state()['node_uuid'], 0
                return self.bridge.points.owner(identity)

            self.wait_for(lambda: owner(mapping) is not None and owner(voronoi) is not None
                          and len(tuple(children(owner(voronoi).shape))) > 50, timeout=12)
            planar_owner = owner(voronoi)
            contours = tuple(children(planar_owner.shape))
            self.assertGreater(len(contours), 50)
            self.assertTrue(all(self.geo.is_closed_curve(wire) for wire in contours))
            for wire in children(owner(mapping).shape):
                for point in self.geo.sample_curve(wire, 4):
                    self.assertAlmostEqual(math.hypot(*point[:2]), 5., delta=2e-6)
            previous = owner(mapping).shape
            sphere = add('Sphere')
            sphere.set_property('parameters', {'R': 8.})
            cylinder.outputs()['G'].disconnect_from(mapping.inputs()['T'])
            sphere.outputs()['G'].connect_to(mapping.inputs()['T'])
            self.wait_for(lambda: owner(mapping).shape is not previous, timeout=12)
            for wire in children(owner(mapping).shape):
                for point in self.geo.sample_curve(wire, 4):
                    self.assertAlmostEqual(math.hypot(*point), 8., delta=2e-6)
            populate.set_property('parameters', {'N': 53})
            self.wait_for(lambda: owner(voronoi).shape is not planar_owner.shape, timeout=12)
            self.assertEqual(owner(voronoi).id, planar_owner.id)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_native_command_publishes_one_compound(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.tessellation_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        sites = [scene.add(self.geo.make_point(p)) for p in fixture.cloud(8)]
        boundary = scene.add(self.geo.make_rectangle((0, 0, 0), (20, 12, 0)))
        messages = []
        command = base.resolve('voronoiparam').fn(SimpleNamespace(echo=messages.append))
        next(command)
        command.send('Periodic U')
        command.send(sites)
        with self.assertRaises(StopIteration):
            command.send([boundary])
        self.wait_for(lambda: any(m.startswith('Created ') for m in messages))
        self.assertEqual(len(scene.objects), 10)
