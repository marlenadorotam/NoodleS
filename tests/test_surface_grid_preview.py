"""Trim-aware UV overlays on the native worker and in the live graph."""
import math
import unittest

from noodles.backend.curves import PlaneValue, circle
from noodles.backend.operations import evaluate_operation
from noodles.backend.previews import UV_GRID_PREVIEW, evaluate_preview, preview_payload
from noodles.backend.solids import SolidValue
from noodles.backend.surface_uv import Domain2Value, SurfaceUvView, UNIT_DOMAIN
from test_surface_uv import NativeSurfaceUvTests as fixture


class SurfaceGridPreviewTests(unittest.TestCase):
    setUpClass = classmethod(fixture.setUpClass.__func__)
    setUp = fixture.setUp
    tearDown = fixture.tearDown
    call = fixture.call
    wait_for = fixture.wait_for
    complete = fixture.complete

    def preview(self, surface, **inputs):
        values = {'S': surface, 'U': 2, 'V': 2, **inputs}
        outputs = evaluate_preview(UV_GRID_PREVIEW, self.parameters, values)
        request = outputs['_sampling']
        reply = self.complete('geometry.uv_grid', request)
        self.assertEqual(reply['state'], 'complete', reply)
        state = {**self.parameters, 'sampling_details': {'signature': request['signature'],
                                                         'values': reply['measurements']}}
        return preview_payload(state, evaluate_preview(UV_GRID_PREVIEW, state, values))

    def test_trimmed_uv_grid_clips_at_hole_and_native_boundary(self):
        from uuid import uuid4
        borders = [circle(str(r), (0, 0, 0), r, PlaneValue()) for r in (8, 3)]
        surface = evaluate_operation('planar_surface', self.parameters, {'C': borders})['G'].values()[0]
        view = SurfaceUvView(surface, 0, Domain2Value(UNIT_DOMAIN, UNIT_DOMAIN))
        payload = self.preview(view)
        item, = payload['items']
        for axis in ('u', 'v'):
            self.assertEqual(len(item[axis]), 2)
            for line in item[axis]:
                self.assertEqual(sorted(round(math.hypot(x, y), 6) for x, y, _ in (line[0], line[-1])), [3, 8])
        revision = self.window.scene.revision
        self.call('previews.sync', {'schema': 1, 'revision': 1, 'client_uuid': str(uuid4()), 'nodes': [payload]})
        self.assertEqual(self.window.scene.revision, revision)
        self.assertFalse(self.window.scene.objects)

    def test_cylinder_grid_follows_curved_face_and_seam(self):
        shell = SolidValue('cylinder', 'cylinder', PlaneValue(), (5, 10), False)
        item, = self.preview(shell, U=3, V=2)['items']
        self.assertEqual(len(item['u']), 2)
        self.assertEqual(len(item['v']), 1)
        ring = item['v'][0]
        self.assertGreater(len(ring), 12)
        self.assertLess(math.dist(ring[0], ring[-1]), 1e-8)
        self.assertTrue(all(abs(math.hypot(x, y) - 5) < 1e-8 and abs(z - 5) < 1e-8 for x, y, z in ring))

    def test_live_graph_hides_grid_without_changing_scene(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = editor.preview_service.client = self.client
        editor.point_service.start()
        editor.preview_service.start()
        editor.show()
        try:
            outline = editor.add_node('NoodleS.Geometry.RectangleNode')
            surface = editor.add_node('NoodleS.Geometry.PlanarSurfaceNode')
            reparam = editor.add_node('NoodleS.Operations.ReparameterizeSurfaceNode')
            preview = editor.add_node('NoodleS.Geometry.ReparameterizeSurfacePreviewNode')
            outline.outputs()['C'].connect_to(surface.inputs()['C'])
            surface.outputs()['G'].connect_to(reparam.inputs()['S'])
            reparam.outputs()['S'].connect_to(preview.inputs()['S'])
            self.wait_for(lambda: len(self.window.scene.objects) == 2 and self.bridge.previews.visible(self.window.scene))
            self.assertNotIn(preview.id, editor.point_service.models)
            grid = self.bridge.previews.visible(self.window.scene)[0]['uv_grid']
            self.assertTrue(all(grid))
            revision = self.window.scene.revision
            checkbox = editor.properties.curve_properties.editors['E'][0]
            QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(7, checkbox.height() // 2))
            self.wait_for(lambda: not self.bridge.previews.visible(self.window.scene))
            self.assertEqual(self.window.scene.revision, revision)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
