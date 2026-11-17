"""Native surface capture, exact trim/orientation, and live graph binding."""
import math
from pathlib import Path
import unittest
import uuid

import test_point_native as fixture
from noodles.backend.arithmetic import VectorValue
from noodles.backend.curves import PlaneValue, circle
from noodles.backend.operations import evaluate_operation, operation_object_from_outputs
from noodles.backend.scene_curves import materialize
from noodles.backend.surface_reference import SurfaceReferenceValue, surface_reference_request
from noodles.bridge import BridgeRemoteError


class NativeSurfaceReferenceTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def complete(self, method, params):
        started = self.call(method, params)
        self.wait_for(lambda: self.bridge.geometry.jobs[started['job_id']]['state'] != 'preparing')
        return self.call('geometry.job', started)

    def capture(self, operation, objects):
        self.window.selection.set([obj.id for obj in objects])
        state = {**self.parameters, 'primitive': operation, 'mode': 'reference', 'node_uuid': str(uuid.uuid4())}
        result = self.complete('geometry.capture', surface_reference_request({**state, 'references': []}))
        self.assertEqual(result['state'], 'complete', result)
        return {**state, 'references': result['references']}

    def test_planar_reference_preserves_hole_orientation_and_uv_through_reopen(self):
        from OCP.BRepTools import BRepTools
        from serpentine3d.fileio.native import load_scene, save_scene
        from noodles.backend.surface_native import planar_surface_shape

        rings = [materialize(circle(str(radius), (0, 0, 0), radius, PlaneValue())) for radius in (6, 2)]
        original = self.geo.faces_of(planar_surface_shape(rings))[0]
        reversed_face = self.geo.faces_of(original.Reversed())[0]
        scene = self.window.scene
        obj = scene.add(reversed_face, name='Renamable surface')
        state = self.capture('planar_surface', [obj])
        out = evaluate_operation('planar_surface', state, {})
        model = operation_object_from_outputs(state, out)
        self.assertEqual(model.mode, 'reference')
        self.assertEqual(model.source_refs, ((state['references'][0]['key'], obj.id),))
        self.assertEqual(out['EC'].values(), (2,))
        self.assertEqual(out['N'].values()[0].xyz, self.geo.face_normal(reversed_face))
        copy = materialize(out['G'].values()[0])
        restored_face, = self.geo.faces_of(copy)
        self.assertEqual(restored_face.Orientation(), reversed_face.Orientation())
        self.assertEqual(BRepTools.UVBounds_s(restored_face), BRepTools.UVBounds_s(reversed_face))
        self.assertAlmostEqual(self.geo.surface_area(copy), math.pi*32, delta=1e-6)
        self.assertIs(scene.get(obj.id)._shape, reversed_face)

        scene.update(obj.id, name='Renamed')
        file = Path(self.folder.name) / 'surfaces.serp'
        save_scene(scene, str(file))
        reopened = self.Scene()
        load_scene(reopened, str(file))
        self.window.scene = reopened
        result = self.complete('geometry.read', surface_reference_request(state))
        self.assertEqual(result['state'], 'complete', result)
        record, = result['references']
        self.assertEqual(record['key'], state['references'][0]['key'])
        self.assertNotEqual(record['id'], obj.id)
        self.assertEqual(record['name'], 'Renamed')
        self.assertEqual(len(reopened.objects), 1)

    def test_edge_and_multiface_loft_and_invalid_selection(self):
        from noodles.backend.operation_native import loft_shape
        from noodles.backend.surface_native import edge_surface_shape

        a = self.geo.make_line((0, 0, 0), (6, 0, 0))
        b = self.geo.make_line((0, 5, 0), (6, 5, 3))
        face = edge_surface_shape([a, b])
        scene = self.window.scene
        edge = scene.add(face, name='Edge Surface')
        state = self.capture('edge_surface', [edge])
        outputs = evaluate_operation('edge_surface', state, {})
        self.assertEqual(outputs['EC'].values(), (len(self.geo.edges_of(face)),))
        self.assertAlmostEqual(self.geo.surface_area(materialize(outputs['G'].values()[0])),
                               self.geo.surface_area(face))
        extrude = {**self.parameters, 'primitive': 'extrude'}
        extruded = evaluate_operation('extrude', extrude, {'G': outputs['G'], 'V': VectorValue((0, 0, 4))})
        model = operation_object_from_outputs(extrude, extruded)
        published = self.complete('geometry.prepare', {'model': model.to_wire(), 'name': 'Extruded reference'})
        self.assertEqual(published['state'], 'complete', published)
        self.assertNotEqual(published['object_id'], edge.id)
        self.assertIs(scene.get(edge.id)._shape, face)

        loft = loft_shape([self.geo.make_polyline([(0, 0, z), (6, 0, z), (3, 5, z)], closed=True)
                           for z in (0, 6)])
        self.assertGreater(len(self.geo.faces_of(loft)), 1)
        loft_object = scene.add(loft, name='Loft')
        state = self.capture('loft', [loft_object])
        outputs = evaluate_operation('loft', state, {})
        self.assertEqual(outputs['K'].values(), ('surface',))
        self.assertEqual(outputs['SC'].count, 0)
        self.assertEqual(len(self.geo.faces_of(materialize(outputs['G'].values()[0]))),
                         len(self.geo.faces_of(loft)))
        self.window.selection.set([loft_object.id])
        invalid = {**state, 'primitive': 'edge_surface'}
        self.assertIn('single-face', self.complete('geometry.capture', surface_reference_request(invalid))['error'])
        self.window.selection.set_subobjects([(loft_object.id, 'face', 0)])
        with self.assertRaisesRegex(BridgeRemoteError, 'whole surface'):
            self.call('geometry.capture', surface_reference_request(state))

    def test_properties_capture_updates_live_and_deleting_node_keeps_source(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.backend.surface_native import planar_surface_shape
        from noodles.document import read_document, write_document
        from noodles.window import MainWindow

        scene = self.window.scene
        shape = planar_surface_shape([materialize(circle('source', (0, 0, 0), 4, PlaneValue()))])
        source = scene.add(shape, name='Live plane')
        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            node = editor.add_node('NoodleS.Geometry.PlanarSurfaceNode')
            self.wait_for(lambda: editor.properties.node_id == node.id)
            panel = editor.properties.curve_properties
            QTest.mouseClick(panel.sources['reference'], Qt.LeftButton)
            self.wait_for(lambda: node.get_property('mode') == 'reference' and panel.generate.isHidden())
            self.window.selection.set([source.id])
            QTest.mouseClick(panel.capture, Qt.LeftButton)

            def value():
                result = editor.evaluation.results.get(node.id)
                return result.outputs['G'].values()[0] if result and not result.error else None

            self.wait_for(lambda: isinstance(value(), SurfaceReferenceValue))
            previous = value()
            path = Path(self.folder.name) / 'surface-reference.noodles'
            write_document(path, editor.graph.serialize_session())
            saved = read_document(path, editor.node_ports)
            self.assertEqual(saved['nodes'][node.id]['custom']['references'][0]['recipe'], previous.to_wire())
            shifted = self.geo.translate(shape, (0, 0, 7))
            scene.replace_shape(source.id, shifted)
            self.wait_for(lambda: isinstance(value(), SurfaceReferenceValue) and value().brep != previous.brep)
            self.assertEqual(value().key, previous.key)
            self.assertAlmostEqual(self.geo.bbox(materialize(value()))[0][2], 7, places=5)
            self.assertNotIn(node.id, editor.point_service.models)
            editor.graph.delete_node(node)
            self.app.processEvents()
            self.assertIs(scene.get(source.id)._shape, shifted)
        finally:
            editor.point_service.stop()
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()
