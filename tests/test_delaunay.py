"""Delaunay boundaries, native indexed publication and graph workflow."""
import math
import random
import unittest

import test_curve_native as fixture

from noodles.backend.curves import PlaneValue, rectangle
from noodles.backend.delaunay import area2, bounded, periodic_u
from noodles.backend.delaunay_node import evaluate, normalize_state, object_from_outputs
from noodles.backend.point import PointValue, object_from_wire


def cloud(n, width=20., height=12.):
    rng = random.Random(235)
    return [(rng.random()*width, rng.random()*height, 0.) for _ in range(n)]


class DelaunayDataTests(unittest.TestCase):
    def test_concave_boundary_contains_corners_and_sites(self):
        ring = [(0.,0.),(1.,0.),(1.,.4),(.4,.4),(.4,1.),(0.,1.)]
        sites = [(.1,.1),(.2,.8),(.8,.3),(.4,.7),(0.,0.)]
        points, faces = bounded(sites, ring, lambda: None)
        used = {points[i] for face in faces for i in face}
        self.assertTrue(set(sites + ring) <= used)
        self.assertAlmostEqual(sum(area2(*(points[i] for i in tri))/2. for tri in faces), .64)
        with self.assertRaisesRegex(ValueError, 'outside'):
            bounded(sites + [(.8,.8)], ring, lambda: None)

    def test_periodic_triangle_pieces_reach_both_matching_seam_edges(self):
        points, faces = periodic_u([p[:2] for p in cloud(100,1.,.6)], 1., .6, lambda: None)
        self.assertTrue({(0.,0.),(1.,0.),(1.,.6),(0.,.6)} <= set(points))
        self.assertAlmostEqual(sum(area2(*(points[i] for i in tri))/2. for tri in faces), .6)
        self.assertEqual(*(sorted(round(y,8) for x,y in points if x == boundary) for boundary in (0.,1.)))


class DelaunayNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp = fixture.NativeCurveTests.setUp
    tearDown = fixture.NativeCurveTests.tearDown
    call = fixture.NativeCurveTests.call
    wait_for = fixture.NativeCurveTests.wait_for
    publish = fixture.NativeCurveTests.publish

    def test_one_compound_shares_edges_and_preserves_owner_on_point_edit(self):
        from noodles.backend.grid_reference_native import children

        params = normalize_state(self.parameters)
        data = {'P': [PointValue(str(i), p) for i,p in enumerate(cloud(150))],
                'B': rectangle('rectangle',20,12,(10,6,0),PlaneValue())}
        def solve(inputs):
            request = evaluate(params, inputs)['_sampling']
            job = self.call('geometry.tessellation', request)
            self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing')
            reply = self.call('geometry.job', job)
            self.assertEqual(reply['state'], 'complete', reply)
            output = evaluate({**params,'sampling_details':{'signature':request['signature'],
                              'values':reply['measurements']}},inputs)
            return object_from_outputs(params,output).to_wire(), output['Count']
        model, count = solve(data)
        self.assertEqual(object_from_wire(model).to_wire(), model)
        owner = self.publish(model)
        self.assertEqual(len(self.window.scene.objects),1)
        wires = tuple(children(owner.shape))
        self.assertEqual(len(wires),count)
        self.assertTrue(all(self.geo.is_closed_curve(wire) for wire in wires))
        self.assertLess(len(self.geo.edges_of(owner.shape)), count*2)
        self.assertTrue(owner.mesh_ready)
        revised, _ = solve({**data,'P':[PointValue('0',(9.5,5.5,0.)),*data['P'][1:]]})
        updated = self.publish(revised)
        self.assertEqual(updated.id, owner.id)
        self.assertIsNot(updated._shape, owner._shape)

    def test_periodic_native_contours_map_to_sphere_and_cylinder(self):
        from noodles.backend.grid_reference_native import children
        from noodles.backend.map_surface_native import map_shape
        from noodles.backend.scene_curves import materialize
        from noodles.backend.solids import SolidValue
        from noodles.backend.tessellation import contours
        from noodles.backend.tessellation_native import build_wires, triangulate_sites

        g = self.geo
        base = g.planar_face(g.make_rectangle((0,0,0),(20,12,0)))
        vertices, cells = triangulate_sites(cloud(30), base, None, True, lambda: None)
        wires = build_wires(contours(vertices,cells))
        targets = ((g.make_sphere((0,0,0),5), lambda p:math.hypot(*p)),
                   (materialize(SolidValue('cyl','cylinder',PlaneValue(),(5,12),False)),
                    lambda p:math.hypot(*p[:2])))
        for target, radius in targets:
            mapped = [map_shape(wire,base,target) for wire in wires]
            for wire in children(g.make_compound(mapped)):
                self.assertTrue(g.is_closed_curve(wire))
                for p in g.sample_curve(wire,5):
                    self.assertAlmostEqual(radius(p),5,delta=2e-6)

    def test_mapped_tessellation_roundtrips_and_updates_on_target_edit(self):
        from noodles.backend.operations import (evaluate_operation, normalize_operation_state,
                                               operation_object_from_outputs)
        from noodles.backend.solids import SolidValue

        p = normalize_state(self.parameters)
        box = rectangle('region',20,12,(10,6,0),PlaneValue())
        inputs = {'P':[PointValue(str(i),v) for i,v in enumerate(cloud(50))], 'B':box}
        request = evaluate(p,inputs)['_sampling']
        job = self.call('geometry.tessellation',request)
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing')
        raw = self.call('geometry.job',job)['measurements']
        result = evaluate({**p,'sampling_details':{'signature':request['signature'],'values':raw}},inputs)
        surface = normalize_operation_state('planar_surface',self.parameters)
        source = evaluate_operation('planar_surface',surface,{'C':box})['G'].values()[0]
        mapping = normalize_operation_state('map_surface',self.parameters)

        def mapped(radius):
            target = SolidValue('sphere','sphere',PlaneValue(),(radius,))
            outputs = evaluate_operation('map_surface',mapping,{'C':result['C'],'S':source,'T':target})
            return operation_object_from_outputs(mapping,outputs).to_wire()

        model = mapped(5.)
        self.assertEqual(model['kind'],'mapped_tessellation')
        self.assertEqual(len(model['surfaces']),2)
        self.assertEqual(object_from_wire(model).to_wire(),model)
        owner = self.publish(model)
        revised = self.publish(mapped(7.))
        self.assertEqual(revised.id,owner.id)
        self.assertIsNot(revised._shape,owner._shape)
        self.assertLess(len(self.geo.edges_of(revised.shape)),result['Count']*2)

    def test_native_command_builds_one_scene_object(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.tessellation_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        sites = [scene.add(self.geo.make_point(point)) for point in cloud(8)]
        boundary = scene.add(self.geo.make_rectangle((0,0,0),(20,12,0)))
        messages = []
        command = base.resolve('delaunayparam').fn(SimpleNamespace(echo=messages.append))
        next(command)
        command.send('Periodic U')
        command.send(sites)
        with self.assertRaises(StopIteration):
            command.send([boundary])
        self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
        self.assertEqual(len(scene.objects),len(sites)+2)

    def test_populate_2d_drives_periodic_delaunay_through_qt(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            rectangle_node = editor.add_node('NoodleS.Geometry.RectangleNode')
            populate = editor.add_node('NoodleS.Geometry.Populate2DNode')
            triangulation = editor.add_node('NoodleS.Geometry.DelaunayNode')
            populate.set_property('parameters', {'N': 42})
            rectangle_node.outputs()['C'].connect_to(populate.inputs()['R'])
            rectangle_node.outputs()['C'].connect_to(triangulation.inputs()['B'])
            populate.outputs()['P'].connect_to(triangulation.inputs()['P'])
            box = editor.properties.curve_properties.periodic_u
            self.wait_for(box.isVisible)
            QTest.mouseClick(box, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7,box.height()//2))
            self.assertTrue(triangulation.curve_state()['parameters']['periodic_u'])
            identity = (editor.project_uuid, triangulation.curve_state()['node_uuid'], 0)
            self.wait_for(lambda: self.bridge.points.owner(identity) is not None)
            self.assertGreater(editor.evaluation.results[triangulation.id].outputs['Count'], 84)
            self.assertEqual(len(self.window.scene.objects),2)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
