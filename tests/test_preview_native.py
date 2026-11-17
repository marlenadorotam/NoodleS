"""Authenticated bridge overlay frames leave real CAD geometry unchanged."""
import copy
import json
from pathlib import Path
import time
import unittest
import uuid
import test_point_native as fixture
from test_previews import state
from noodles.backend.previews import evaluate_preview,preview_payload
from noodles.backend.arithmetic import VectorValue
from noodles.backend.scene_previews import arrow_geometry,LEASE_SECONDS


class NativePreviewTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp=fixture.NativePointTests.setUp
    tearDown=fixture.NativePointTests.tearDown
    call=fixture.NativePointTests.call
    wait_for=fixture.NativePointTests.wait_for

    def frame(self,revision=1,visible=True):
        output=evaluate_preview('vector_preview',state(),{'V':VectorValue((3,4,0)),'S':visible})
        return {'schema':1,'client_uuid':'1d1b5988-3410-4995-9eab-9910cd6b56bb',
                'revision':revision,'nodes':[preview_payload(state(),output)]}

    def test_native_annotation_frame_renders_tag_and_dimension_and_clears(self):
        import numpy as np
        from PySide6.QtGui import QImage, QPainter
        from noodles.backend.annotation_render import paint_annotations
        from noodles.backend.point import PointValue

        a, b = PointValue('a', (35, 105, 0)), PointValue('b', (165, 105, 0))
        tag_state = {**state(), 'node_uuid': str(uuid.uuid4())}
        dim_state = {**state(), 'node_uuid': str(uuid.uuid4())}
        tag = evaluate_preview('text_tag', tag_state, {'P': PointValue('t', (100, 27, 0)), 'T': 'Panel 7', 'C': '#E37554'})
        dim = evaluate_preview('dimension', dim_state, {'A': a, 'B': b, 'O': VectorValue((0, -35, 0)), 'C': '#56BDA7'})
        payload = {**self.frame(), 'nodes': [preview_payload(tag_state, tag), preview_payload(dim_state, dim)]}
        self.call('previews.sync', payload)
        items = [entry['annotation'] for entry in self.bridge.previews.visible(self.window.scene)]
        self.assertEqual([(item.kind, str(item.color)) for item in items],
                         [('text_tag', '#E37554'), ('dimension', '#56BDA7')])
        rendered = QImage(200, 130, QImage.Format_ARGB32)
        rendered.fill(0)
        painter = QPainter(rendered)
        try:
            paint_annotations(painter, lambda p, w, h: np.column_stack((p[:, :2], np.ones(len(p)))),
                              200, 130, items, self.window.scene.format_length)
        finally:
            painter.end()
        self.assertGreater(rendered.pixelColor(100, 27).alpha(), 0)
        self.assertGreater(rendered.pixelColor(40, 70).green(), rendered.pixelColor(40, 70).red())
        self.assertFalse(self.window.scene.objects)
        self.call('previews.sync', {**payload, 'revision': 2, 'nodes': []})
        self.assertFalse(self.bridge.previews.visible(self.window.scene))

    def test_area_gradient_numbered_labels_and_live_dimension_in_qt(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.preview_service.client = self.client
        editor.point_service.start()
        editor.preview_service.start()
        editor.show()
        try:
            small = editor.add_node('NoodleS.Geometry.RectangleNode')
            large = editor.add_node('NoodleS.Geometry.RectangleNode')
            small.set_property('parameters', {'X': 2., 'Y': 4.})
            large.set_property('parameters', {'X': 3., 'Y': 4., 'C': [10., 0., 0.]})
            merge = editor.add_node('NoodleS.Data.MergeNode')
            area = editor.add_node('NoodleS.Operations.AreaNode')
            gradient = editor.add_node('NoodleS.Math.GradientNode')
            sequence = editor.add_node('NoodleS.Math.SeriesNode')
            sequence.set_property('start', 1.)
            sequence.set_property('count', 2)
            tag = editor.add_node('NoodleS.VisualHelpers.TextTagNode')
            a = editor.add_node('NoodleS.Geometry.PointNode')
            b = editor.add_node('NoodleS.Geometry.PointNode')
            b.set_property('x', 10.)
            dim = editor.add_node('NoodleS.VisualHelpers.DimensionNode')
            for source, output, target, port in (
                (small, 'C', merge, 'A'), (large, 'C', merge, 'B'), (merge, 'D', area, 'G'),
                (area, 'A', gradient, 'V'), (area, 'C', tag, 'P'), (gradient, 'C', tag, 'C'),
                (sequence, 'S', tag, 'T'), (a, 'P', dim, 'A'), (b, 'P', dim, 'B'),
            ):
                source.outputs()[output].connect_to(target.inputs()[port])

            def visible(kind):
                return [record['annotation'] for record in self.bridge.previews.visible(self.window.scene)
                        if 'annotation' in record and record['annotation'].kind == kind]

            self.wait_for(lambda: len(visible('text_tag')) == 2 and len(visible('dimension')) == 1, timeout=10)
            self.assertEqual([(item.text, str(item.color)) for item in visible('text_tag')],
                             [('1', '#3889C7'), ('2', '#F0AC50')])
            self.assertEqual(visible('dimension')[0].length, 10.)
            large.set_property('parameters', {'X': 1., 'Y': 4., 'C': [10., 0., 0.]})
            b.set_property('x', 15.)
            self.wait_for(lambda: visible('dimension') and visible('dimension')[0].length == 15.
                          and visible('text_tag') and str(visible('text_tag')[0].color) == '#F0AC50', timeout=10)
            self.assertNotIn(tag.id, editor.point_service.models)
            self.assertNotIn(dim.id, editor.point_service.models)
            dim.set_property('parameters', {'S': False})
            self.wait_for(lambda: not visible('dimension'))
            self.assertEqual(editor.evaluation.results[dim.id].outputs['L'].values(), (15.,))
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_sync_replace_hide_remove_and_restore_without_scene_or_history_changes(self):
        adapter=self.bridge.previews
        owner=self.window.scene.add(self.geo.make_point((1,2,3)),name='Untouched source')
        revision=self.window.scene.revision
        self.call('previews.sync',self.frame())
        self.assertEqual(len(adapter.visible(self.window.scene)),1)
        self.call('previews.sync',self.frame(2,False))
        self.assertFalse(adapter.visible(self.window.scene))
        empty={**self.frame(3),'nodes':[]}
        self.call('previews.sync',empty)
        self.assertFalse(adapter.visible(self.window.scene))
        self.call('previews.sync',self.frame(4))
        self.assertEqual(len(adapter.visible(self.window.scene)),1)
        self.assertEqual(self.window.scene.revision,revision)
        self.assertEqual(list(self.window.scene.objects),[owner.id])

    def test_validation_is_atomic_old_frames_rejected_and_client_isolation(self):
        self.call('previews.sync',self.frame(3))
        old={**self.frame(2),'nodes':[]}
        self.assertEqual(self.call('previews.sync',old)['state'],'superseded')
        invalid=self.frame(4)
        invalid['nodes'][0]['items'][0]['vector']=[0,0,0]
        with self.assertRaises(Exception):
            self.call('previews.sync',invalid)
        self.assertEqual(len(self.bridge.previews.visible(self.window.scene)),1)
        second=self.frame()
        second['client_uuid']=str(uuid.uuid4())
        self.call('previews.sync',second)
        self.assertEqual(len(self.bridge.previews.visible(self.window.scene)),2)
        self.call('previews.sync',{**self.frame(4),'nodes':[]})
        self.assertEqual(len(self.bridge.previews.visible(self.window.scene)),1)
        # A displacement may span the full coordinate range; only endpoints
        # are bounded as coordinates, matching the pure node evaluator.
        wide=self.frame(5)
        wide['nodes'][0]['items'][0].update(origin=[-1e9,0,0],vector=[2e9,0,0])
        self.call('previews.sync',wide)

    def test_lease_expiry_and_same_revision_heartbeat_recovery(self):
        self.call('previews.sync',self.frame())
        record=self.bridge.previews.records()[self.frame()['client_uuid']]
        record['seen']=time.monotonic()-LEASE_SECONDS-1
        self.bridge.previews.expire()
        self.assertFalse(self.bridge.previews.visible(self.window.scene))
        self.call('previews.sync',self.frame())
        self.assertEqual(len(self.bridge.previews.visible(self.window.scene)),1)

    def test_hide_uses_whole_owner_and_restores_after_disconnect_delete_and_disable(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.preview_service.client = self.client
        editor.point_service.start()
        editor.preview_service.start()
        try:
            grid = editor.add_node('NoodleS.Geometry.GridRectangleNode')
            hide = editor.add_node('NoodleS.VisualHelpers.HideNode')
            second = editor.add_node('NoodleS.VisualHelpers.HideNode')
            scene = self.window.scene
            identity = (editor.project_uuid, grid.curve_state()['node_uuid'], 0)
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None)
            original = owner()
            layer = scene.layers.create('Grid layer')
            scene.update(original.id, layer_id=layer.id)
            original = owner()
            grid.outputs()['P'].connect_to(hide.inputs()['G'])
            grid.outputs()['G'].connect_to(second.inputs()['G'])
            self.wait_for(lambda: hide.id in editor.preview_service.nodes and second.id in editor.preview_service.nodes
                          and not owner().visible)
            self.assertEqual(editor.evaluation.results[hide.id].outputs['Count'], 1)
            self.assertEqual(len(scene.all()), 1)
            grid.outputs()['P'].disconnect_from(hide.inputs()['G'])
            self.wait_for(lambda: hide.id not in editor.preview_service.nodes)
            self.assertFalse(owner().visible)
            second.set_disabled(True)
            self.wait_for(lambda: owner().visible)
            second.set_disabled(False)
            self.wait_for(lambda: not owner().visible)
            editor.graph.delete_node(second)
            self.wait_for(lambda: owner().visible)
            editor.graph.undo_stack().undo()
            self.wait_for(lambda: not owner().visible)
            self.assertEqual((owner().id, owner().layer_id), (original.id, original.layer_id))
            self.assertIs(owner()._shape, original._shape)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_reopening_scene_does_not_replay_the_previous_documents_hide_lease(self):
        from serpentine3d.core.user_text import with_value
        from serpentine3d.fileio.native import load_scene, save_scene

        scene = self.window.scene
        project, node = state()['project_uuid'], state()['node_uuid']
        obj = scene.add(self.geo.make_point((1, 2, 3)))
        binding = json.dumps({f'{project}:{node}:0': 'point'})
        scene.update(obj.id, user_text=with_value(obj.user_text, 'NoodleS.point_references', binding))
        self.bridge.summary()
        frame = self.frame()
        frame['nodes'].append({**state(), 'node_uuid': str(uuid.uuid4()), 'items': [],
                               'hide_targets': [['reference', project, node, 'point']]})
        self.call('previews.sync', frame)
        self.assertFalse(scene.get(obj.id).visible)
        self.assertTrue(self.bridge.previews.visible(scene))

        path = Path(self.folder.name) / 'model.serp'
        save_scene(scene, str(path))
        load_scene(scene, str(path))
        self.bridge.summary()
        self.assertTrue(scene.all()[0].visible)
        self.assertFalse(self.bridge.previews.visible(scene))

    def test_hide_reference_cooperates_with_show_parent_and_releases_expired_lease(self):
        import json
        from serpentine3d.core.user_text import with_value
        from noodles.backend.parent_visibility import BASELINE, CLAIMS, reconcile

        scene = self.window.scene
        target = ('reference', state()['project_uuid'], state()['node_uuid'], 'point')
        ref = scene.add(self.geo.make_point((1, 2, 3)), name='Referenced point')
        scene.update(ref.id, user_text=with_value(ref.user_text, 'NoodleS.point_references',
                     json.dumps({f'{target[1]}:{target[2]}:0': target[3]})))
        other = scene.add(self.geo.make_point((0, 0, 0)))
        scene.update(other.id, user_text=with_value(other.user_text, CLAIMS, json.dumps([target])))
        reconcile(self.bridge.points)
        frame = {**self.frame(), 'nodes': [{**state(), 'items': [], 'hide_targets': [list(target)]}]}
        self.call('previews.sync', frame)
        scene.remove(other.id)
        reconcile(self.bridge.points)
        self.assertFalse(scene.get(ref.id).visible)
        hidden_snapshot = scene.snapshot()
        record = self.bridge.previews.records()[frame['client_uuid']]
        record['seen'] = time.monotonic() - LEASE_SECONDS - 1
        self.bridge.previews.expire()
        self.assertTrue(scene.get(ref.id).visible)
        self.assertIsNone(self.bridge.points._json(scene.get(ref.id), BASELINE))
        scene.restore(hidden_snapshot)
        self.bridge._attach_scene()
        self.assertTrue(scene.get(ref.id).visible)
        scene.update(ref.id, visible=False)
        self.call('previews.sync', frame)
        self.call('previews.sync', {**frame, 'revision': 2, 'nodes': []})
        self.assertFalse(scene.get(ref.id).visible)

    def test_arrow_tip_head_clamping_and_all_axis_directions(self):
        import numpy as np
        for vector in ((0,0,1),(0,0,-1),(1,0,0),(-1,0,0),(3,4,5),(.00001,0,0)):
            origin=np.asarray((10,20,30),float)
            shaft,head=arrow_geometry(origin,vector,100,100)
            tip=origin+vector
            self.assertEqual(head.shape,(30,3))
            np.testing.assert_allclose(head[::3],np.tile(tip,(10,1)))
            self.assertLessEqual(np.linalg.norm(tip-shaft[-1]),np.linalg.norm(vector)*.350001)
            self.assertTrue(np.isfinite(head).all())

    def test_native_command_origin_is_independent_and_clear_does_not_touch_cad(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.scene_previews import register_commands
        register_commands(self.ctx)
        messages=[]
        context=SimpleNamespace(echo=messages.append)
        generator=base.resolve('vectorpreview').fn(context)
        next(generator)
        for point in ((10.,20.,30.),(0.,0.,0.),(3.,4.,0.)):
            try:
                generator.send(point)
            except StopIteration:
                break
        items=self.bridge.previews.visible(self.window.scene)
        self.assertEqual(items[0]['origin'],(10,20,30))
        self.assertEqual(items[0]['vector'],(3,4,0))
        self.assertFalse(self.window.scene.objects)
        self.assertFalse(base.resolve('vectorpreview').mutates)
        list(base.resolve('vectorpreviewclear').fn(context))
        self.assertFalse(self.bridge.previews.visible(self.window.scene))
        self.assertFalse(self.window.scene.objects)

    def test_plane_preview_uses_oriented_grid_and_shared_overlay_without_objects(self):
        from noodles.backend.curves import PlaneValue
        from noodles.backend.scene_previews import plane_grid
        plane = PlaneValue((10, 20, 30), (0, 1, 0), (1, 0, 0))
        options = {**state(), 'primitive': 'plane_preview'}
        output = evaluate_preview('plane_preview', options, {'P': plane, 'W': 12, 'H': 8, 'D': 2})
        payload = {**self.frame(), 'nodes': [preview_payload(options, output)]}
        self.call('previews.sync', payload)
        stored = self.bridge.previews.visible(self.window.scene)[0]['plane']
        grid, x, y = plane_grid(stored)
        self.assertEqual(x, ((10, 14, 30), (10, 26, 30)))
        self.assertEqual(y, ((10, 20, 26), (10, 20, 34)))
        self.assertTrue(grid and all(p[0] == 10 for p in grid))
        self.assertFalse(self.window.scene.objects)
        self.call('previews.sync', {**payload, 'revision': 2, 'nodes': []})
        self.assertFalse(self.bridge.previews.visible(self.window.scene))
