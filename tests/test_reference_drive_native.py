"""End-to-end native writes through every existing non-Point Reference node."""
from pathlib import Path
import unittest

from Qt import QtCore
from PySide6.QtTest import QTest

import test_curve_native as fixture
from test_curves import inputs_for
from noodles.backend.curves import CURVE_SPECS
from noodles.backend.grids import GRID_SPECS
from noodles.backend.geometry import GEOMETRY_SPECS, evaluate_geometry, normalize_geometry_state
from noodles.backend.scene_curves import materialize
from noodles.backend.solids import SOLID_SPECS
from noodles.window import MainWindow


class NativeReferenceDriveTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeCurveTests.setUpClass.__func__)
    setUp = fixture.NativeCurveTests.setUp
    tearDown = fixture.NativeCurveTests.tearDown
    wait_for = fixture.NativeCurveTests.wait_for

    def capture(self, editor, node, ids):
        self.wait_for(lambda: editor.properties.node_id == node.id)
        self.window.selection.set(ids)
        editor._capture_points()
        self.wait_for(lambda: len(node.get_property('references')) == len(ids))

    def test_every_reference_writes_through_graph_and_rebinds_after_reopen(self):
        from serpentine3d.fileio.native import save_scene, load_scene

        specs = {**CURVE_SPECS, **SOLID_SPECS}
        from noodles.backend.surface_reference import ARCHIVED_REFERENCE_OPS
        self.assertEqual(set(specs) | set(GRID_SPECS),
                         {op for op, spec in GEOMETRY_SPECS.items() if spec.get('reference', True)}
                         - ARCHIVED_REFERENCE_OPS)
        # Port -> new value -> native output check. Point-driven changes use
        # a real CAD Point input and flow through its live Reference binding.
        cases = {
            'circle': ('R', 13, 'R', 13),
            'ellipse': ('A', 3, 'A', 3),  # A crosses B and retains its axis
            'rectangle': ('X', 17, 'X', 17),
            'line': ('B', 'point', 'B', (9, 4, 2)),
            'arc': ('M', 'point', 'M', (9, 4, 2)),
            'arc_center': ('A', -120, 'S', -120),
            'polyline': ('C', 1, 'Closed', True),
            'curve': ('P', 'points', 'V', None),
            'interpcurve': ('P', 'points', 'CP', None),
            'box': ('X', 16, 'X', 16),
            'box_from_center': ('X', 16, 'X', 16),
            'pyramid': ('H', -12, 'H', -12),
            'sphere': ('R', 19, 'R', 19),
            'ellipsoid': ('Y', 13, 'Y', 13),
            'torus': ('r', 7, 'r', 7),
            'cylinder': ('S', 0, 'S', False),
            'cone': ('S', 0, 'S', False),
            'truncated_cone': ('H', -12, 'H', -12),
            'paraboloid': ('H', 30, 'H', 30),
        }
        self.assertEqual(set(cases), set(specs))
        scene = self.window.scene
        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        reopened_editor = None
        nodes = {}
        try:
            for operation, (port, target, output, expected) in cases.items():
                with self.subTest(operation=operation):
                    value = next(iter(evaluate_geometry(operation, normalize_geometry_state(operation, {}),
                                                       inputs_for(operation)).values())).values()[0]
                    obj = scene.add(materialize(value), name=operation)
                    native_before = obj._shape
                    if target in ('point', 'points'):
                        upstream = editor.add_node('NoodleS.Geometry.PointNode')
                        upstream.set_property('mode', 'reference')
                        coords = [(9, 4, 2)] if target == 'point' else [(0, 0, 0), (5, 4, 3), (8, 10, 0), (20, 7, 1)]
                        ids = [scene.add(self.geo.make_point(p)).id for p in coords]
                        self.capture(editor, upstream, ids)
                        out = upstream.outputs()['P']
                    else:
                        upstream = editor.add_node('NoodleS.Inputs.SliderNode')
                        upstream.set_property('minimum', -200)
                        upstream.set_property('value', target)
                        out = upstream.outputs()['Number']
                    node = editor.add_node('NoodleS.Geometry.'+specs[operation]['class'])
                    self.wait_for(lambda: editor.properties.node_id == node.id)
                    panel = editor.properties.curve_properties
                    QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
                    self.assertEqual(node.get_property('mode'), 'reference')
                    self.capture(editor, node, [obj.id])
                    original = scene.get(obj.id)
                    self.wait_for(lambda: not editor.evaluation.results[node.id].error)
                    before = editor.evaluation.results[node.id].outputs[output]
                    scene_ids = set(scene.objects)
                    out.connect_to(node.inputs()[port])
                    self.wait_for(lambda: scene.get(obj.id)._shape is not native_before)
                    self.wait_for(lambda: not editor.evaluation.results[node.id].error and
                                  editor.evaluation.results[node.id].outputs[output] != before)
                    current = editor.evaluation.results[node.id].outputs[output].values()[0]
                    if expected is not None:
                        if isinstance(expected, tuple):
                            for actual, coordinate in zip(current.xyz, expected):
                                self.assertAlmostEqual(actual, coordinate, places=6)
                        else:
                            self.assertAlmostEqual(current, expected, places=6)
                    updated = scene.get(obj.id)
                    self.assertEqual(set(scene.objects), scene_ids)
                    expected_text = original.user_text
                    if operation in ('truncated_cone', 'pyramid'):
                        from noodles.backend.primitive_shapes import HEIGHT_SIGN_KEYS
                        expected_text = {**expected_text, HEIGHT_SIGN_KEYS[operation]: '-1'}
                    self.assertEqual((updated.id, updated.name, updated.user_text),
                                     (original.id, original.name, expected_text))
                    self.assertTrue(updated.mesh_ready)
                    self.assertTrue(node.get_property('references'))
                    if operation == 'sphere':
                        upstream.set_property('value', 21)
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['R'].values() == (21,))
                        out.disconnect_from(node.inputs()[port])
                        upstream.set_property('value', 24)
                        self.assertEqual(node.get_property('references')[0]['recipe']['dimensions'], [21])
                        out.connect_to(node.inputs()[port])
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['R'].values() == (24,))
                        center = editor.add_node('NoodleS.Geometry.PointNode')
                        center.set_property('mode', 'reference')
                        center_obj = scene.add(self.geo.make_point((20, 30, 40)))
                        self.capture(editor, center, [center_obj.id])
                        center.outputs()['P'].connect_to(node.inputs()['O'])
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['O'].values()[0].xyz == (20, 30, 40))
                        self.wait_for(lambda: all('O' in row['values'] for row in
                            editor.point_service.completed_geometry_drives[node.id][-1]['updates']))
                        sphere = evaluate_geometry('sphere', normalize_geometry_state('sphere', {}), {'R': 27})['G'].values()[0]
                        scene.replace_shape(obj.id, materialize(sphere))
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['R'].values() == (27,))
                        scene.replace_shape(center_obj.id, self.geo.make_point((40, 30, 20)))
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['O'].values()[0].xyz == (40, 30, 20))
                        self.assertEqual(editor.evaluation.results[node.id].outputs['R'].values(), (27,))
                        previous_shape = scene.get(obj.id)._shape
                        another = scene.add(materialize(sphere), name='Replacement reference')
                        editor.graph.clear_selection()
                        node.set_selected(True)
                        self.window.selection.set([another.id])
                        self.wait_for(lambda: editor.properties.node_id == node.id)
                        editor._capture_points()
                        self.wait_for(lambda: node.get_property('references')[0]['id'] == another.id)
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['R'].values() == (24,))
                        self.assertIs(scene.get(obj.id)._shape, previous_shape)
                    if operation == 'curve':
                        before_invalid = scene.get(obj.id)._shape
                        with scene.batched():
                            for oid in ids:
                                scene.replace_shape(oid, self.geo.make_point((1, 2, 3)))
                        self.wait_for(lambda: 'distinct control points' in (getattr(node, 'reference_drive_error', '') or ''))
                        self.assertIs(scene.get(obj.id)._shape, before_invalid)
                        out.disconnect_from(node.inputs()['P'])
                        degree = editor.add_node('NoodleS.Inputs.NumberNode')
                        degree.set_property('value', 2)
                        degree.outputs()['Number'].connect_to(node.inputs()['D'])
                        self.wait_for(lambda: editor.evaluation.results[node.id].outputs['D'].values() == (2,))
                    nodes[operation] = (node.get_property('node_uuid'), node.get_property('references')[0])
            graph_path = Path(self.folder.name) / 'reference.noodles'
            editor._save_to(graph_path)
            scene_path = Path(self.folder.name) / 'reference.serp'
            save_scene(scene, str(scene_path))
            editor.point_service.stop()
            reopened = self.Scene()
            load_scene(reopened, str(scene_path))
            self.window.scene = reopened
            descriptor = self.bridge.descriptor
            old_session = self.bridge.session_id
            self.bridge.stop()
            self.bridge = type(self.bridge)(self.ctx, descriptor)
            self.bridge.start()
            self.assertNotEqual(self.bridge.session_id, old_session)
            from noodles.document import read_document
            reopened_editor = MainWindow()
            reopened_editor.point_service.client = self.client
            reopened_editor.load_session(read_document(graph_path, reopened_editor.node_ports), graph_path)
            reopened_editor.point_service.start()
            by_uuid = {n.get_property('node_uuid'): n for n in reopened_editor.graph.all_nodes()
                       if n.has_property('node_uuid')}
            self.assertEqual(set(nodes), set(specs))
            for operation, (uuid, saved) in nodes.items():
                with self.subTest(reopen=operation):
                    node = by_uuid[uuid]
                    self.wait_for(lambda: node.get_property('references')[0]['id'] != saved['id'])
                    self.assertEqual(node.get_property('references')[0]['key'], saved['key'])
                    self.assertIsNotNone(reopened.get(node.get_property('references')[0]['id']))
        finally:
            for window in (editor, reopened_editor):
                if window is not None:
                    window.point_service.stop()
                    window.graph.undo_stack().setClean()
                    window.close()
                    window.deleteLater()
            self.app.processEvents()
