"""Mesh topology and the live native reference-to-Pipe workflow."""
from collections import Counter
from itertools import combinations
import math
import random
import unittest

import test_point_native as fixture
from noodles.backend.curves import PlaneValue, rectangle
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.mesh_nodes import mesh_from_wire
from noodles.backend.point import PointValue
from noodles.core import compute


def edge_counts(mesh):
    return Counter(tuple(sorted((a, b))) for face in mesh.triangles
                   for a, b in zip(face, (*face[1:], face[0])))


class MeshDataTests(unittest.TestCase):
    def test_mesh_join_weld_and_face_neighbours_preserve_crease_and_paths(self):
        a = mesh_from_wire({'key': 'a', 'kind': 'mesh', 'vertices': [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                            'triangles': [(0, 1, 2)]})
        b = mesh_from_wire({'key': 'b', 'kind': 'mesh', 'vertices': [(0, 0, 0), (1.0001, 0, 0), (0, 0, 1)],
                            'triangles': [(1, 0, 2)]})
        tree = DataTree((Branch((4, 2), (a, b)), Branch((7,), ())))
        joined = compute('mesh_join', {}, {'M': tree})['M']
        self.assertEqual(joined.values()[0].triangles, ((0, 1, 2), (4, 3, 5)))
        preserved = compute('weld_mesh', {}, {'M': joined, 'T': .001, 'A': 30})['M']
        self.assertEqual(len(preserved.values()[0].vertices), 6)
        exact = compute('weld_mesh', {}, {'M': joined, 'T': 0, 'A': 180})['M']
        self.assertEqual(len(exact.values()[0].vertices), 5)
        self.assertEqual(compute('face_neighbours', {}, {'M': exact})['B'].values(), (3, 3))
        welded = compute('weld_mesh', {}, {'M': joined, 'T': .001, 'A': 100})['M']
        self.assertEqual(welded.values()[0].triangles, ((0, 1, 2), (1, 0, 3)))
        result = compute('face_neighbours', {}, {'M': welded})
        self.assertEqual(result['N'].branches, (Branch((4, 2, 0), (1,)), Branch((4, 2, 1), (0,)), Branch((7, 0), ())))
        self.assertEqual(result['B'].values(), (2, 2))
        self.assertEqual(result['X'].values(), (0, 0))
        self.assertEqual(result['B'].branches[-1], Branch((7,), ()))

    def test_face_neighbours_reports_nonmanifold_edges(self):
        mesh = mesh_from_wire({'key': 'fan', 'kind': 'mesh', 'vertices': [
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0)],
            'triangles': [(0, 1, 2), (1, 0, 3), (0, 1, 4)]})
        result = compute('face_neighbours', {}, {'M': mesh})
        self.assertEqual([b.items for b in result['N'].branches], [(1, 2), (0, 2), (0, 1)])
        self.assertEqual(result['B'].values(), (2, 2, 2))
        self.assertEqual(result['X'].values(), (1, 1, 1))

    def test_face_boundaries_match_face_indices_and_comparison_mask(self):
        mesh = mesh_from_wire({'key': 'two', 'kind': 'mesh',
                               'vertices': [(0, 0, 0), (3, 0, 0), (0, 4, 0), (0, 0, 5)],
                               'triangles': [(0, 1, 2), (0, 2, 3)]})
        tree = DataTree((Branch((2,), (mesh, mesh)), Branch((7,), ())))
        faces = compute('deconstruct_mesh', {}, {'M': tree})['F']
        outlines = compute('face_boundaries', {}, {'M': tree})['B']
        self.assertEqual([b.path for b in outlines.branches], [b.path for b in faces.branches])
        self.assertEqual([b.keys for b in outlines.branches], [b.keys for b in faces.branches])
        self.assertTrue(all(curve.closed for curve in outlines.values()))
        lengths = DataTree(tuple(Branch(b.path, tuple(curve.length for curve in b.items), b.keys)
                                 for b in outlines.branches))
        masks = compute('larger_than', {}, {'A': lengths, 'B': 12})
        self.assertEqual(masks['>'].values(), (False, True, False, True))
        self.assertEqual(masks['≥'].values(), (True, True, True, True))
        chosen = compute('dispatch', {}, {'L': faces, 'P': masks['>']})
        self.assertEqual(chosen['A'].values(), ((0, 2, 3),)*2)
        self.assertEqual(chosen['B'].values(), ((0, 1, 2),)*2)

    def test_periodic_delaunay_keeps_shared_indices_across_the_uv_seam(self):
        frame = PlaneValue((2, 3, 4), (0, 1, 0), (1, 0, 0))
        boundary = rectangle('boundary', 20, 5, frame.origin, frame)
        rng = random.Random(11)
        points = tuple(PointValue(str(i), frame.at(rng.uniform(-10, 10), rng.uniform(-2.5, 2.5)))
                       for i in range(60))
        params = {'parameters': {'periodic_u': True}}
        inputs = {'P': DataTree((Branch((2,), points), Branch((5,), ())))}
        with self.assertRaisesRegex(ValueError, 'Rectangle at B'):
            compute('delaunay_mesh', params, inputs)
        result = compute('delaunay_mesh', params, {**inputs, 'B': boundary})
        mesh, = result['M'].values()
        u, v = (result[port].values() for port in 'UV')
        self.assertEqual(tuple(b.path for b in result['U'].branches), ((2,), (5,)))
        self.assertEqual(len(u), len(v))
        self.assertEqual(len(u), len(mesh.vertices))
        self.assertEqual(len(set(zip(u, v))), len(u))
        self.assertTrue(all(0 <= value < 1 for value in u))
        edges = edge_counts(mesh)
        self.assertTrue(any(abs(u[a] - u[b]) > .5 and count == 2 for (a, b), count in edges.items()))
        self.assertEqual({v[a] for (a, b), count in edges.items() if count == 1}, {0., 1.})
        self.assertTrue(all(count == 2 or count == 1 and v[a] == v[b] in (0., 1.)
                            for (a, b), count in edges.items()))

    def test_face_tools_preserve_mesh_slots_winding_and_zero_based_indices(self):
        mesh = mesh_from_wire({'key': 'pair', 'kind': 'mesh',
                               'vertices': [(0, 0, 0), (3, 0, 0), (0, 3, 0)],
                               'triangles': [(0, 1, 2), (0, 2, 1)]})
        tree = DataTree((Branch((3,), (mesh, mesh)), Branch((8,), ())))
        parts = compute('deconstruct_mesh', {}, {'M': tree})
        normals = compute('face_normals', {}, {'M': tree})
        self.assertEqual([b.path for b in normals['C'].branches], [b.path for b in parts['F'].branches])
        self.assertEqual([b.keys for b in normals['N'].branches], [b.keys for b in parts['F'].branches])
        self.assertEqual([p.xyz for p in normals['C'].values()], [(1, 1, 0)] * 4)
        self.assertEqual([n.xyz for n in normals['N'].values()], [(0, 0, 1), (0, 0, -1)] * 2)
        indices = compute('deconstruct_face', {}, {'F': parts['F']})
        self.assertEqual(indices['C'], indices['D'])
        roundtrip = compute('triangle_face', {}, {port: indices[port] for port in 'ABC'})['F']
        self.assertEqual([b.items for b in roundtrip.branches], [b.items for b in parts['F'].branches])
        with self.assertRaisesRegex(ValueError, 'distinct'):
            compute('triangle_face', {}, {'A': 1, 'B': 1, 'C': 2})
        with self.assertRaisesRegex(ValueError, 'matching list lengths'):
            compute('triangle_face', {}, {'A': [0, 1], 'B': [2, 3, 4], 'C': 5})

    def test_terrain_keeps_faces_and_vertex_order_across_tree_branches(self):
        points = tuple(PointValue(str(i), xyz) for i, xyz in enumerate(
            ((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0))))
        data = DataTree((Branch((2,), points), Branch((5,), points), Branch((9,), ())))
        meshes = compute('delaunay_mesh', {}, {'P': data})['M']
        parts = compute('deconstruct_mesh', {}, {'M': meshes})
        numbers = compute('random', {'parameters': {'S': 17}},
                          {'R': DomainValue(1, 3), 'N': compute('list_length', {}, {'L': parts['V']})['L']})['R']
        axes = compute('deconstruct_point', {}, {'P': parts['V']})
        displaced = compute('point', {'mode': 'generate'}, {**axes, 'Z': numbers})['P']
        terrain = compute('construct_mesh', {}, {'V': displaced, 'F': parts['F'], 'C': parts['C']})['M']
        self.assertEqual(tuple(b.path for b in terrain.branches), ((2,), (5,), (9,)))
        for mesh, original in zip(terrain.values(), meshes.values(), strict=True):
            self.assertEqual(mesh.triangles, original.triangles)
            self.assertEqual(tuple(p[:2] for p in mesh.vertices), tuple(p.xyz[:2] for p in points))
            self.assertTrue(all(1 <= p[2] <= 3 for p in mesh.vertices))
        self.assertEqual(numbers.branches[0].items, numbers.branches[1].items)
        with self.assertRaisesRegex(ValueError, 'matching'):
            compute('construct_mesh', {'tree_modes': {'F': 'flatten'}}, {'V': displaced, 'F': parts['F']})
        with self.assertRaisesRegex(ValueError, 'vertex indices'):
            compute('construct_mesh', {}, {'V': list(points), 'F': [(0, 1, 4)]})
        quad = compute('construct_mesh', {}, {'V': list(points), 'F': [(0, 1, 2, 3)]})['M'].values()[0]
        self.assertEqual(quad.triangles, ((0, 1, 2), (0, 2, 3)))

    def test_deconstruct_keeps_local_indices_and_vertex_normals_per_mesh(self):
        data = {
            'key': 'mesh', 'kind': 'mesh',
            'vertices': [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0), (0, -2, 0), (0, 0, 2)],
            'triangles': [(0, 1, 2), (3, 1, 4), (0, 3, 5)],
        }
        implicit = mesh_from_wire(data)
        explicit = mesh_from_wire({**data, 'normals': [(1, 0, 0)] * 6})
        self.assertNotIn('normals', implicit.to_wire())
        self.assertEqual(mesh_from_wire(explicit.to_wire()), explicit)
        tree = DataTree((Branch((2,), (implicit, explicit)), Branch((2, 0), ())))
        out = compute('deconstruct_mesh', {}, {'M': tree})
        for port in ('V', 'F', 'C', 'N'):
            self.assertEqual(tuple(branch.path for branch in out[port].branches), ((2, 0), (2, 1), (2, 0, 0)))
        self.assertEqual(tuple(p.xyz for p in out['V'].branches[0].items), implicit.vertices)
        self.assertEqual(out['F'].branches[0].items, implicit.triangles)
        self.assertEqual(out['F'].branches[1].items, explicit.triangles)
        self.assertEqual(out['C'].count, 0)
        self.assertEqual(tuple(n.xyz for n in out['N'].branches[0].items),
                         ((0, 0, 1), (0, 0, 0), (0, 0, 1), (0, 0, -1), (0, 0, -1), (0, 0, 0)))
        self.assertEqual(tuple(n.xyz for n in out['N'].branches[1].items), explicit.normals)
        self.assertEqual(out['V'].branches[0].keys, out['N'].branches[0].keys)
        grafted = compute('deconstruct_mesh', {'tree_modes': {'M': 'graft'}}, {'M': tree})
        self.assertEqual(tuple((b.path, b.items) for b in grafted['F'].branches),
                         tuple((b.path, b.items) for b in out['F'].branches))

    def test_classifies_edges_after_welding_duplicate_vertex_indices(self):
        mesh = mesh_from_wire({
            'key': 'mesh', 'kind': 'mesh',
            'vertices': [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0),
                         (2, 0, 0), (0, -2, 0), (0, 0, 2)],
            'triangles': [(0, 1, 2), (4, 3, 5), (3, 4, 6), (0, 3, 6)],
        })
        tree = DataTree((Branch((3,), (mesh,)), Branch((9,), ())))
        out = compute('mesh_edges', {'tree_modes': {'M': 'graft'}}, {'M': tree})
        self.assertEqual(tuple(out[port].count for port in ('E1', 'E2', 'E3')), (6, 0, 1))
        self.assertEqual(out['E3'].values()[0].points, ((0, 0, 0), (2, 0, 0)))
        self.assertEqual(tuple(branch.path for branch in out['E1'].branches), ((3, 0), (9, 0)))


class MeshNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def test_native_brep_meshing_density_and_closed_box(self):
        from noodles.backend.mesh_native import brep_to_mesh
        from noodles.backend.scene_curves import materialize

        box = self.geo.make_box((1, 2, 3), 2., 3., 4.)
        mesh = brep_to_mesh(box, (.005, 20., True))
        self.assertEqual((len(mesh.vertices), len(mesh.triangles)), (8, 12))
        self.assertEqual(set(edge_counts(mesh).values()), {2})
        sphere = self.geo.make_sphere((10, 20, 30), 5.)
        coarse = brep_to_mesh(sphere, (.08, 45., True))
        fine = brep_to_mesh(sphere, (.003, 15., True))
        self.assertGreater(len(fine.triangles), len(coarse.triangles))
        self.assertTrue(all(math.isclose(math.dist(p, (10, 20, 30)), 5., abs_tol=1e-7) for p in fine.vertices))
        cylinder = brep_to_mesh(self.geo.make_cylinder((0, 0, 0), 5., 10.), (.005, 20., True))
        self.assertEqual(set(edge_counts(cylinder).values()), {2})
        frame = PlaneValue()
        outer = materialize(rectangle('outer', 10., 10., (0, 0, 0), frame))
        hole = materialize(rectangle('hole', 4., 4., (0, 0, 0), frame))
        face, = self.geo.planar_regions([outer, hole])
        trimmed = brep_to_mesh(face, (.005, 20., True))
        self.assertAlmostEqual(sum(abs((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]))/2
                                   for a, b, c in (tuple(trimmed.vertices[i] for i in face)
                                                   for face in trimmed.triangles)), 84.)

    def test_two_terrain_patches_join_weld_and_publish_in_qt(self):
        from serpentine3d.core.mesh import MeshShape
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            merge = editor.add_node('NoodleS.Data.MergeNode')
            for port, x in zip('AB', (1., 3.0001), strict=True):
                outline = editor.add_node('NoodleS.Geometry.RectangleNode')
                surface = editor.add_node('NoodleS.Geometry.PlanarSurfaceNode')
                outline.set_property('parameters', {'X': 2., 'Y': 2., 'C': [x, 1., 0.]})
                outline.outputs()['C'].connect_to(surface.inputs()['C'])
                surface.outputs()['G'].connect_to(merge.inputs()[port])
            convert = editor.add_node('NoodleS.Operations.BrepToMeshNode')
            join = editor.add_node('NoodleS.Operations.MeshJoinNode')
            weld = editor.add_node('NoodleS.Operations.WeldMeshNode')
            before = editor.add_node('NoodleS.Operations.FaceNeighboursNode')
            after = editor.add_node('NoodleS.Operations.FaceNeighboursNode')
            merge.outputs()['D'].connect_to(convert.inputs()['B'])
            for source, target in ((convert, join), (join, weld), (join, before), (weld, after)):
                source.outputs()['M'].connect_to(target.inputs()['M'])

            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))

            self.wait_for(lambda: all(owner(node) for node in (convert, join, weld)), timeout=10)
            self.assertTrue(all(isinstance(owner(node).shape, MeshShape) for node in (convert, join, weld)))
            self.assertEqual(len(owner(join).shape.vertices), 8)
            self.assertEqual(len(owner(weld).shape.vertices), 6)
            results = editor.evaluation.results
            self.assertEqual(sum(results[before.id].outputs['B'].values()), 8)
            self.assertEqual(sum(results[after.id].outputs['B'].values()), 6)
            self.assertEqual(results[after.id].outputs['N'].count, results[before.id].outputs['N'].count + 2)
            self.assertIsNone(owner(after))
            previous = owner(weld)
            weld.set_property('parameters', {'T': 0.})
            self.wait_for(lambda: len(owner(weld).shape.vertices) == 8)
            self.assertEqual(owner(weld).id, previous.id)
            self.assertEqual(sum(editor.evaluation.results[after.id].outputs['B'].values()), 8)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_face_perimeters_drive_dispatch_in_editor(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from serpentine3d.core.mesh import MeshShape
        from noodles.window import MainWindow

        source = self.window.scene.add(MeshShape(
            [(0, 0, 0), (3, 0, 0), (0, 4, 0), (0, 0, 5)], [(0, 1, 2), (0, 2, 3)]))
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            mesh = editor.add_node('NoodleS.Geometry.MeshNode')
            capture = editor.properties.curve_properties.capture
            self.wait_for(capture.isVisible)
            QTest.mouseClick(capture, Qt.LeftButton)
            self.wait_for(lambda: len(mesh.get_property('references')) == 1)
            parts = editor.add_node('NoodleS.Operations.DeconstructMeshNode')
            boundaries = editor.add_node('NoodleS.Operations.FaceBoundariesNode')
            length = editor.add_node('NoodleS.Operations.CurveLengthNode')
            compare = editor.add_node('NoodleS.Math.LargerThanNode')
            dispatch = editor.add_node('NoodleS.Data.DispatchNode')
            compare.set_property('b', 12.)
            for node, output, target, port in (
                (mesh, 'M', parts, 'M'), (mesh, 'M', boundaries, 'M'),
                (boundaries, 'B', length, 'C'), (length, 'L', compare, 'A'),
                (compare, '>', dispatch, 'P'), (parts, 'F', dispatch, 'L'),
            ):
                node.outputs()[output].connect_to(target.inputs()[port])

            def selected():
                result = editor.evaluation.results.get(dispatch.id)
                return result and not result.error and result.outputs.get('B')

            self.wait_for(lambda: selected() and selected().values() == ((0, 1, 2),))
            self.assertEqual(set(self.window.scene.objects), {source.id})
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_book_stellation_rebuilds_icosahedron_as_one_live_mesh(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from serpentine3d.core.mesh import MeshShape
        from noodles.backend.curves import cross, dot, sub
        from noodles.window import MainWindow

        phi = (1 + math.sqrt(5)) / 2
        vertices = [(a, b, c) for i in (-1, 1) for j in (-phi, phi)
                    for a, b, c in ((0, i, j), (j, 0, i), (i, j, 0))]
        faces = []
        for a, b, c in combinations(range(len(vertices)), 3):
            p, q, r = vertices[a], vertices[b], vertices[c]
            if all(math.isclose(math.dist(u, v), 2) for u, v in ((p, q), (q, r), (r, p))):
                faces.append((a, b, c) if dot(cross(sub(q, p), sub(r, p)), p) > 0 else (a, c, b))
        self.assertEqual(len(faces), 20)
        source = self.window.scene.add(MeshShape(vertices, faces), name='Icosahedron')
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            mesh = editor.add_node('NoodleS.Geometry.MeshNode')
            capture = editor.properties.curve_properties.capture
            self.wait_for(capture.isVisible)
            QTest.mouseClick(capture, Qt.LeftButton)
            self.wait_for(lambda: len(mesh.get_property('references')) == 1)
            parts = editor.add_node('NoodleS.Operations.DeconstructMeshNode')
            indices = editor.add_node('NoodleS.Operations.DeconstructFaceNode')
            normals = editor.add_node('NoodleS.Operations.FaceNormalsNode')
            vertex_count = editor.add_node('NoodleS.Data.ListLengthNode')
            face_count = editor.add_node('NoodleS.Data.ListLengthNode')
            sequence = editor.add_node('NoodleS.Math.SeriesNode')
            scale = editor.add_node('NoodleS.Math.MultiplicationNode')
            apex = editor.add_node('NoodleS.Math.AdditionNode')
            merge_vertices = editor.add_node('NoodleS.Data.MergeNode')
            merge_faces = editor.add_node('NoodleS.Data.MergeNode')
            final = editor.add_node('NoodleS.Operations.ConstructMeshNode')
            slider = editor.add_node('NoodleS.Inputs.SliderNode')
            slider.set_property('value', 1.5)

            def connect(source, output, target, port):
                source.outputs()[output].connect_to(target.inputs()[port])

            for edge in (
                (mesh, 'M', parts, 'M'), (mesh, 'M', normals, 'M'), (parts, 'F', indices, 'F'),
                (parts, 'V', vertex_count, 'L'), (parts, 'F', face_count, 'L'),
                (vertex_count, 'L', sequence, 'S'), (face_count, 'L', sequence, 'C'),
                (normals, 'N', scale, 'A'), (slider, 'Number', scale, 'B'),
                (normals, 'C', apex, 'A'), (scale, 'R', apex, 'B'),
                (parts, 'V', merge_vertices, 'A'), (apex, 'R', merge_vertices, 'B'),
                (merge_vertices, 'D', final, 'V'), (merge_faces, 'D', final, 'F'),
            ):
                connect(*edge)
            for a, b, slot in (('A', 'B', 'A'), ('B', 'C', 'B'), ('C', 'A', 'C')):
                triangle = editor.add_node('NoodleS.Operations.TriangleFaceNode')
                connect(sequence, 'S', triangle, 'A')
                connect(indices, a, triangle, 'B')
                connect(indices, b, triangle, 'C')
                connect(triangle, 'F', merge_faces, slot)
            identity = editor.project_uuid, final.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None and len(owner().shape.triangles) == 60, timeout=10)
            initial = owner()
            self.assertIsInstance(initial.shape, MeshShape)
            self.assertEqual(len(initial.shape.vertices), 32)
            self.assertEqual(set(self.window.scene.objects), {source.id, initial.id})
            edges = Counter(tuple(sorted((a, b))) for triangle in initial.shape.triangles
                            for a, b in zip(triangle, (*triangle[1:], triangle[0])))
            self.assertEqual(len(edges), 90)
            self.assertEqual(set(edges.values()), {2})
            slider.set_property('value', 3.12)
            self.wait_for(lambda: owner().shape is not initial.shape, timeout=10)
            self.assertEqual(owner().id, initial.id)
            self.assertTrue((owner().shape.triangles == initial.shape.triangles).all())
            self.assertTrue((owner().shape.vertices[:12] == initial.shape.vertices[:12]).all())
            for face, old_tip, new_tip in zip(faces, initial.shape.vertices[12:], owner().shape.vertices[12:], strict=True):
                a, b, c = (vertices[i] for i in face)
                center = tuple((x + y + z) / 3 for x, y, z in zip(a, b, c))
                self.assertAlmostEqual(math.dist(center, new_tip), 3.12)
                self.assertGreater(dot(sub(new_tip, old_tip), center), 0)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_periodic_cylinder_has_two_open_rims_after_random_displacement(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QStyle, QStyleOptionButton
        from serpentine3d.core.mesh import MeshShape
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            boundary = editor.add_node('NoodleS.Geometry.RectangleNode')
            cylinder = editor.add_node('NoodleS.Geometry.CylinderNode')
            populate = editor.add_node('NoodleS.Geometry.Populate2DNode')
            sample = editor.add_node('NoodleS.Operations.SurfaceEvaluateNode')
            parts = editor.add_node('NoodleS.Operations.DeconstructMeshNode')
            length = editor.add_node('NoodleS.Data.ListLengthNode')
            random_values = editor.add_node('NoodleS.Math.RandomNode')
            scale = editor.add_node('NoodleS.Math.MultiplicationNode')
            offset = editor.add_node('NoodleS.Math.AdditionNode')
            final = editor.add_node('NoodleS.Operations.ConstructMeshNode')
            delaunay = editor.add_node('NoodleS.Operations.DelaunayMeshNode')
            boundary.set_property('parameters', {'X': math.tau*5, 'Y': 8.})
            cylinder.set_property('parameters', {'R': 5., 'H': 8., 'S': False})
            populate.set_property('parameters', {'N': 80, 'S': 11})
            sample.set_property('parameters', {'N': True})
            panel = editor.properties.curve_properties
            periodic = panel.periodic_u
            self.wait_for(lambda: editor.properties.node_id == delaunay.id and periodic.isVisible())
            option = QStyleOptionButton()
            periodic.initStyleOption(option)
            indicator = periodic.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, periodic)
            QTest.mouseClick(periodic, Qt.LeftButton, pos=indicator.center())
            self.assertTrue(delaunay.curve_state()['parameters']['periodic_u'])
            for source, out, target, port in (
                (boundary, 'C', populate, 'R'), (boundary, 'C', delaunay, 'B'),
                (populate, 'P', delaunay, 'P'), (delaunay, 'M', parts, 'M'),
                (cylinder, 'G', sample, 'S'), (delaunay, 'U', sample, 'U'), (delaunay, 'V', sample, 'V'),
                (sample, 'P', length, 'L'), (length, 'L', random_values, 'N'), (sample, 'N', scale, 'A'),
                (random_values, 'R', scale, 'B'), (sample, 'P', offset, 'A'), (scale, 'R', offset, 'B'),
                (offset, 'R', final, 'V'), (parts, 'F', final, 'F'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])

            identity = editor.project_uuid, final.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=10)
            original = owner()
            self.assertIsInstance(original.shape, MeshShape)
            edges = edge_counts(original.shape)
            rim_degrees = Counter()
            for (a, b), count in edges.items():
                self.assertIn(count, (1, 2))
                if count == 1:
                    self.assertEqual(original.shape.vertices[a, 2], original.shape.vertices[b, 2])
                    rim_degrees.update((a, b))
            self.assertEqual(set(rim_degrees.values()), {2})
            self.assertEqual({original.shape.vertices[i, 2] for i in rim_degrees}, {0., 8.})
            self.assertEqual(len(original.shape.vertices) - len(edges) + len(original.shape.triangles), 0)
            self.assertTrue(all(5. <= math.hypot(x, y) <= 6. for x, y, _ in original.shape.vertices))
            self.assertEqual([obj.id for obj in self.window.scene.objects.values() if obj.kind == 'mesh'],
                             [original.id])

            random_values.set_property('parameters', {'S': 7})
            self.wait_for(lambda: owner().shape is not original.shape, timeout=10)
            self.assertEqual(owner().id, original.id)
            self.assertTrue((owner().shape.triangles == original.shape.triangles).all())
            self.assertFalse((owner().shape.vertices == original.shape.vertices).all())
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_book_terrain_updates_one_native_mesh_without_changing_faces(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from serpentine3d.core.mesh import MeshShape
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            plane = editor.add_node('NoodleS.Operations.PlaneSurfaceNode')
            populate = editor.add_node('NoodleS.Geometry.Populate2DNode')
            delaunay = editor.add_node('NoodleS.Operations.DelaunayMeshNode')
            parts = editor.add_node('NoodleS.Operations.DeconstructMeshNode')
            length = editor.add_node('NoodleS.Data.ListLengthNode')
            coords = editor.add_node('NoodleS.Math.DeconstructPointNode')
            points = editor.add_node('NoodleS.Geometry.PointNode')
            terrain = editor.add_node('NoodleS.Operations.ConstructMeshNode')
            random = editor.add_node('NoodleS.Math.RandomNode')
            populate.set_property('parameters', {'N': 40})
            for source, out, target, port in (
                (plane, 'P', populate, 'R'), (populate, 'P', delaunay, 'P'), (delaunay, 'M', parts, 'M'),
                (parts, 'V', length, 'L'), (parts, 'V', coords, 'P'), (length, 'L', random, 'N'),
                (coords, 'X', points, 'X'), (coords, 'Y', points, 'Y'), (random, 'R', points, 'Z'),
                (points, 'P', terrain, 'V'), (parts, 'F', terrain, 'F'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])
            identity = editor.project_uuid, terrain.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=10)
            original = owner()
            self.assertIsInstance(original.shape, MeshShape)
            self.assertEqual(len(original.shape.vertices), 40)
            self.assertTrue((original.shape.vertices[:, 2] > 0).all())
            self.assertGreater(len(original.shape.triangles), 40)
            self.assertEqual([obj.id for obj in self.window.scene.objects.values() if obj.kind == 'mesh'],
                             [original.id])
            self.assertIsNotNone(original._mesh)
            seed = editor.properties.curve_properties.editors['S'][0]
            self.assertTrue(seed.isVisible())
            seed.setFocus()
            seed.selectAll()
            QTest.keyClicks(seed, '7')
            QTest.keyClick(seed, Qt.Key_Return)
            self.wait_for(lambda: owner().shape is not original.shape, timeout=10)
            self.assertEqual(owner().id, original.id)
            self.assertTrue((owner().shape.triangles == original.shape.triangles).all())
            self.assertTrue((owner().shape.vertices[:, :2] == original.shape.vertices[:, :2]).all())
            self.assertFalse((owner().shape.vertices[:, 2] == original.shape.vertices[:, 2]).all())
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_mesh_reference_edges_feed_pipe_and_follow_native_edits(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from serpentine3d.core.mesh import MeshShape
        from noodles.backend.grid_reference_native import children
        from noodles.window import MainWindow

        shape = MeshShape([(0, 0, 0), (10, 0, 0), (0, 10, 0), (0, 0, 10)],
                          [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
                          [(0, 1, 0)] * 4)
        scene = self.window.scene
        source = scene.add(shape, name='Tetrahedron')
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            mesh = editor.add_node('NoodleS.Geometry.MeshNode')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: editor.properties.node_id == mesh.id and panel.capture.isVisible())
            QTest.mouseClick(panel.capture, Qt.LeftButton)
            self.wait_for(lambda: len(mesh.get_property('references')) == 1)
            edges = editor.add_node('NoodleS.Geometry.MeshEdgesNode')
            deconstruct = editor.add_node('NoodleS.Operations.DeconstructMeshNode')
            pipe = editor.add_node('NoodleS.Geometry.PipeNode')
            radius = editor.add_node('NoodleS.Inputs.NumberNode')
            radius.set_property('value', .25)
            mesh.outputs()['M'].connect_to(edges.inputs()['M'])
            mesh.outputs()['M'].connect_to(deconstruct.inputs()['M'])
            edges.outputs()['E2'].connect_to(pipe.inputs()['C'])
            radius.outputs()['Number'].connect_to(pipe.inputs()['R'])

            identity = editor.project_uuid, pipe.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=10)
            self.assertEqual(set(scene.objects), {source.id, owner().id})
            out = editor.evaluation.results[edges.id].outputs
            self.assertEqual(tuple(out[port].count for port in ('E1', 'E2', 'E3')), (0, 6, 0))
            parts = editor.evaluation.results[deconstruct.id].outputs
            self.assertEqual(tuple(p.xyz for p in parts['V'].values()), tuple(map(tuple, shape.vertices)))
            self.assertEqual(parts['F'].values(), tuple(map(tuple, shape.triangles)))
            self.assertEqual(parts['C'].count, 0)
            self.assertEqual(tuple(n.xyz for n in parts['N'].values()), ((0, 1, 0),) * 4)
            self.assertEqual(len(tuple(children(owner().shape))), 6)
            self.assertIs(scene.get(source.id).shape, shape)
            before_id, before_shape = owner().id, owner().shape

            shifted = shape.translated((5, 2, 3))
            scene.replace_shape(source.id, shifted)
            self.wait_for(lambda: owner().shape is not before_shape, timeout=10)
            self.assertEqual(owner().id, before_id)
            self.assertIs(scene.get(source.id).shape, shifted)
            moved = editor.evaluation.results[edges.id].outputs['E2'].values()
            self.assertEqual(moved[0].points[0], (5, 2, 3))
            parts = editor.evaluation.results[deconstruct.id].outputs
            self.assertEqual(parts['V'].values()[0].xyz, (5, 2, 3))

            editor.preview_service.client = self.client
            editor.preview_service.start()
            hide = editor.add_node('NoodleS.VisualHelpers.HideNode')
            mesh.outputs()['M'].connect_to(hide.inputs()['G'])
            self.wait_for(lambda: not scene.get(source.id).visible)
            self.assertTrue(owner().visible)
            editor.graph.delete_node(hide)
            self.wait_for(lambda: scene.get(source.id).visible)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
