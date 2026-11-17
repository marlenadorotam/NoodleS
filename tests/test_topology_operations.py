"""Topology operations from the graph through the shared OCC worker."""
from collections import OrderedDict
import unittest

from noodles.backend.curves import PlaneValue, line
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.operations import evaluate_operation, operation_object_from_outputs
from noodles.backend.point import PointValue
from noodles.backend.scene_curves import materialize
from noodles.backend.solids import SolidValue
from noodles.backend.splines import PendingGeometry
from noodles.backend.topology_native import measure
from test_operations import state
import test_operation_native as native


class TopologyNativeTests(unittest.TestCase):
    setUpClass = classmethod(native.NativeOperationTests.setUpClass.__func__)
    setUp = native.NativeOperationTests.setUp
    tearDown = native.NativeOperationTests.tearDown
    call = native.NativeOperationTests.call
    wait_for = native.NativeOperationTests.wait_for
    publish = native.NativeOperationTests.publish

    def test_split_shared_cutter_preserves_paths_and_publishes_one_owner(self):
        lower = line('lower', (0, 0, 0), (10, 0, 0))
        upper = line('upper', (0, 1, 0), (10, 1, 0))
        cutter = line('cutter', (4, -1, 0), (4, 2, 0))
        targets = DataTree((Branch((3,), (lower,)), Branch((7,), (upper,))))
        pieces = self.output('split', {'G': targets, 'C': cutter})
        self.assertEqual([b.path for b in pieces['G'].branches], [(3,), (7,)])
        self.assertEqual([len(b.items) for b in pieces['G'].branches], [2, 2])
        obj = self.publish(operation_object_from_outputs(state('split'), pieces).to_wire())
        self.assertAlmostEqual(self.geo.curve_length(obj.shape), 20)
        self.assertEqual(len(self.window.scene.objects), 1)

    def test_split_solid_with_curve_swept_along_world_z(self):
        box = SolidValue('box', 'box', PlaneValue(), (10, 10, 10))
        cutter = line('cutter', (4, -1, 0), (4, 11, 0))
        pieces = self.output('split', {'G': box, 'C': cutter})
        self.assertEqual([p.result_kind for p in pieces['G'].values()], ['solid', 'solid'])
        volumes = sorted(round(self.geo.volume(materialize(p))) for p in pieces['G'].values())
        self.assertEqual(volumes, [400, 600])

    def test_trim_selects_by_geometry_and_rejects_a_point_on_the_cut(self):
        from noodles.backend.topology_native import split_shapes, trim_pieces
        target = self.geo.make_line((0, 0, 0), (10, 0, 0))
        cutter = self.geo.make_line((4, -1, 0), (4, 1, 0))
        parts = split_shapes((target, cutter))
        kept, = trim_pieces(parts, (2, 0, 0))
        self.assertAlmostEqual(self.geo.curve_length(kept), 6)
        kept, = trim_pieces(parts, (8, 0, 0))
        self.assertAlmostEqual(self.geo.curve_length(kept), 4)
        self.assertAlmostEqual(self.geo.curve_length(target), 10)
        with self.assertRaisesRegex(ValueError, 'equally close'):
            trim_pieces(parts, (4, 0, 0))

    def test_trim_matches_remove_points_and_keeps_pieces_in_target_branches(self):
        lower = line('lower', (0, 0, 0), (10, 0, 0))
        upper = line('upper', (0, 1, 0), (10, 1, 0))
        cutter = line('cutter', (4, -1, 0), (4, 2, 0))
        left, right = PointValue('left', (2, 0, 0)), PointValue('right', (8, 1, 0))
        targets = DataTree((Branch((3,), (lower, upper)), Branch((7,), (upper,))))
        points = DataTree((Branch((7,), (left,)), Branch((3,), (left, right))))
        data = {'G': targets, 'C': cutter, 'P': points}
        pieces = self.output('trim', data)
        self.assertEqual([branch.path for branch in pieces['G'].branches], [(3,), (7,)])
        self.assertEqual([piece.remove_at for piece in pieces['G'].values()],
                         [left.xyz, right.xyz, left.xyz])
        obj = self.publish(operation_object_from_outputs(state('trim'), pieces).to_wire())
        self.assertAlmostEqual(self.geo.curve_length(obj.shape), 16)
        self.assertEqual(len(self.window.scene.objects), 1)
        with self.assertRaisesRegex(ValueError, 'one point per target'):
            evaluate_operation('trim', state('trim'), {**data, 'P': [left, right]})

    def test_trim_solid_uses_interior_remove_point(self):
        box = SolidValue('box', 'box', PlaneValue(), (10, 10, 10))
        cutter = line('cutter', (4, -1, 0), (4, 11, 0))
        pieces = self.output('trim', {'G': box, 'C': cutter, 'P': PointValue('pick', (2, 5, 5))})
        kept, = pieces['G'].values()
        self.assertAlmostEqual(self.geo.volume(materialize(kept)), 600)

    def test_live_trim_preserves_owner_when_pick_crosses_the_cut(self):
        from noodles.window import MainWindow
        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            target = gui.add_node('NoodleS.Geometry.LineNode')
            cutter = gui.add_node('NoodleS.Geometry.LineNode')
            cutter.set_property('parameters', {'A': [4, -1, 0], 'B': [4, 1, 0]})
            point = gui.add_node('NoodleS.Geometry.PointNode')
            point.set_property('x', 2)
            trim = gui.add_node('NoodleS.Geometry.TrimNode')
            target.outputs()['C'].connect_to(trim.inputs()['G'])
            cutter.outputs()['C'].connect_to(trim.inputs()['C'])
            point.outputs()['P'].connect_to(trim.inputs()['P'])
            adapter = self.bridge.points
            trim_id = adapter.identity(trim.curve_state())
            target_id = adapter.identity(target.curve_state())

            def length_is(length):
                owner = adapter.owner(trim_id)
                return owner and abs(self.geo.curve_length(owner.shape) - length) < 1e-9

            self.wait_for(lambda: length_is(6) and adapter.owner(target_id), timeout=8)
            owner, source = adapter.owner(trim_id), adapter.owner(target_id)
            point.set_property('x', 4)
            self.wait_for(lambda: 'equally close' in (gui.evaluation.results[trim.id].error or ''), timeout=8)
            self.assertIs(adapter.owner(trim_id)._shape, owner._shape)
            point.set_property('x', 8)
            self.wait_for(lambda: length_is(4), timeout=8)
            self.assertEqual(adapter.owner(trim_id).id, owner.id)
            self.assertIs(adapter.owner(target_id)._shape, source._shape)
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    def output(self, operation, data, parameters=None):
        parameters = parameters or state(operation)
        pending = evaluate_operation(operation, parameters, data)
        self.assertIsInstance(pending['Count'], PendingGeometry)
        request = pending['_sampling']
        job = self.call('geometry.topology', request)
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing')
        reply = self.call('geometry.job', job)
        self.assertEqual(reply['state'], 'complete', reply)
        completed = {**parameters, 'sampling_details': {
            'signature': request['signature'], 'values': reply['measurements']}}
        return evaluate_operation(operation, completed, data)

    def test_join_unordered_curves_keeps_exact_edge_lengths_and_explode_order(self):
        a = line('a', (0, 0, 0), (10, 0, 0))
        b = line('b', (10, 10, 0), (10, 0, 0))
        joined = self.output('join', {'G': DataTree((Branch((3,), (b, a)),))})
        value, = joined['G'].values()
        self.assertEqual(value.result_kind, 'curve')
        exploded = self.output('explode', {'G': joined['G']})
        self.assertEqual(exploded['Count'], 2)
        self.assertEqual(exploded['G'].branches[0].path, (3,))
        obj = self.publish(operation_object_from_outputs(state('explode'), exploded).to_wire())
        self.assertEqual(len(self.geo.edges_of(obj.shape)), 2)
        self.assertAlmostEqual(self.geo.curve_length(obj.shape), 20)
        self.assertEqual(len(self.window.scene.objects), 1)

    def test_join_box_faces_seals_to_solid_and_explode_keeps_face_types(self):
        box = SolidValue('box', 'box', PlaneValue(), (2, 3, 4))
        faces = self.output('explode', {'G': box})
        self.assertEqual(faces['Count'], 6)
        self.assertTrue(all(piece.result_kind == 'surface' for piece in faces['G'].values()))
        joined = self.output('join', {'G': faces['G']})
        self.assertEqual(joined['Count'], 1)
        self.assertEqual(joined['G'].values()[0].result_kind, 'solid')
        obj = self.publish(operation_object_from_outputs(state('join'), joined).to_wire())
        self.assertAlmostEqual(self.geo.volume(obj.shape), 24)

    def test_disconnected_join_and_single_edge_explode(self):
        a = line('a', (0, 0, 0), (10, 0, 0))
        b = line('b', (20, 0, 0), (30, 0, 0))
        with self.assertRaisesRegex(self.geo.GeometryError, 'connect end-to-end'):
            measure({'operation': 'join', 'rows': [[a.to_wire(), b.to_wire()]]}, lambda: True, OrderedDict())
        output = self.output('explode', {'G': a})
        self.assertEqual(output['Count'], 0)
        self.assertEqual(output['G'].branches[0].items, ())

    def test_live_join_explode_list_item_and_curve_domain(self):
        from noodles.window import MainWindow
        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            a = gui.add_node('NoodleS.Geometry.LineNode')
            b = gui.add_node('NoodleS.Geometry.LineNode')
            b.set_property('parameters', {'A': [10, 0, 0], 'B': [10, 10, 0]})
            merge = gui.add_node('NoodleS.Data.MergeNode')
            join = gui.add_node('NoodleS.Geometry.JoinNode')
            explode = gui.add_node('NoodleS.Geometry.ExplodeNode')
            select = gui.add_node('NoodleS.Data.ListItemNode')
            domain = gui.add_node('NoodleS.Operations.CurveDomainNode')
            a.outputs()['C'].connect_to(merge.inputs()['A'])
            b.outputs()['C'].connect_to(merge.inputs()['B'])
            merge.outputs()['D'].connect_to(join.inputs()['G'])
            join.outputs()['G'].connect_to(explode.inputs()['G'])
            explode.outputs()['G'].connect_to(select.inputs()['L'])
            select.outputs()['I'].connect_to(domain.inputs()['C'])

            def published(length):
                nodes = gui.evaluation.results
                measured = nodes.get(domain.id)
                owner = self.bridge.points.owner(self.bridge.points.identity(join.curve_state()))
                values = measured.outputs['L'].values() if measured and 'L' in measured.outputs else ()
                return (owner and abs(self.geo.curve_length(owner.shape) - length) < 1e-9
                        and values and isinstance(values[0], (float, int)))

            self.wait_for(lambda: published(20))
            first = self.bridge.points.owner(self.bridge.points.identity(join.curve_state()))
            b.set_property('parameters', {'A': [10, 0, 0], 'B': [10, 15, 0]})
            self.wait_for(lambda: published(25))
            updated = self.bridge.points.owner(self.bridge.points.identity(join.curve_state()))
            self.assertEqual(updated.id, first.id)
            self.assertEqual(gui.evaluation.results[explode.id].outputs['Count'], 2)
            self.assertEqual(len(self.window.scene.objects), 4)
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()
