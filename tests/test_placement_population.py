"""Migration regressions exercised through graph, native OCC and CAD commands."""
import math
from types import SimpleNamespace
import unittest

from test_operations import state
import test_operation_native as fixture
from noodles.backend.arithmetic import VectorValue
from noodles.backend.curves import PlaneValue, line, rectangle
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.operations import evaluate_operation, operation_object_from_outputs
from noodles.backend.point import PointValue
from noodles.backend.scene_curves import materialize
from noodles.backend.solids import SolidValue


def model(op, inputs):
    params = state(op)
    return operation_object_from_outputs(params, evaluate_operation(op, params, inputs)).to_wire()


class PlacementLayoutTests(unittest.TestCase):
    def test_array_keeps_paths_and_existing_slot_keys_when_count_changes(self):
        source = PointValue('base', (2, 3, 4))
        tree = DataTree((Branch((2, 1), (source,)), Branch((9,), (source,))))
        params = state('array')
        data = {'G': tree, 'Ny': 2, 'Dy': 4}
        first = evaluate_operation('array', params, data)
        larger = evaluate_operation('array', params, {**data, 'Nx': 3})
        self.assertEqual([b.path for b in first['G'].branches], [(2, 1, 0), (9, 0)])
        self.assertEqual(first['Count'], 6)
        for original, edited in zip(first['G'].branches, larger['G'].branches):
            self.assertEqual(original.keys, edited.keys[:3])
            self.assertEqual([v.vector for v in original.items], [(0, 4, 0), (10, 0, 0), (10, 4, 0)])

    def test_polar_full_turn_and_partial_sweep(self):
        source = PointValue('base', (2, 0, 0))
        params = state('array_polar')
        for angle, expected in ((360, (0, 90, 180, 270)), (-90, (0, -30, -60, -90))):
            result = evaluate_operation('array_polar', params, {'G': source, 'N': 4, 'A': angle})
            self.assertEqual(tuple(v.angle for v in result['G'].values()), expected)

    def test_scale_follows_repeated_point_and_rejects_wrong_branch_count(self):
        points = DataTree((Branch((2,), (PointValue('p', (5, 1, 0)),)),
                           Branch((9,), (PointValue('q', (1, 5, 0)),))))
        objects = [line('a', (0, 0, 0), (1, 0, 0)), line('b', (0, 0, 0), (2, 0, 0))]
        op = 'objects_on_points'
        params = state(op)
        inputs = {'G': objects, 'P': points, 'T': [1, VectorValue((2, 3, 4))]}
        result = evaluate_operation(op, params, inputs)['G']
        self.assertEqual([b.path for b in result.branches], [(2,), (9,)])
        self.assertEqual([[v.placement[1] for v in b.items] for b in result.branches],
                         [[(1, 1, 1)]*2, [(2, 3, 4)]*2])
        with self.assertRaisesRegex(ValueError, 'Scale'):
            evaluate_operation(op, params, {**inputs, 'T': [1, 2, 3]})


class PlacementNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativeOperationTests.setUpClass.__func__)
    setUp = fixture.NativeOperationTests.setUp
    tearDown = fixture.NativeOperationTests.tearDown
    call = fixture.NativeOperationTests.call
    wait_for = fixture.NativeOperationTests.wait_for
    publish = fixture.NativeOperationTests.publish

    def test_book_closest_pair_radius_drives_one_sphere_owner(self):
        from itertools import combinations
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.backend.grid_reference_native import children
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(category, name):
                return editor.add_node(f'NoodleS.{category}.{name}Node')

            region = add('Geometry', 'Rectangle')
            population = add('Geometry', 'Populate2D')
            cross = add('Data', 'CrossReference')
            self.wait_for(lambda: editor.properties.node_id == cross.id)
            pairing = editor.properties.curve_properties.cross_pairing
            self.assertEqual(pairing.currentText(), 'Holistic')
            QTest.keyClick(pairing, Qt.Key_End)
            self.assertEqual(cross.curve_state()['parameters']['pairing'], 'lower_strict')
            distance = add('Math', 'Vector2Pt')
            bounds = add('Math', 'Bounds')
            deconstruct = add('Math', 'DeconstructDomain')
            half = add('Math', 'Division')
            divisor = add('Inputs', 'Number')
            divisor.set_property('value', 2)
            sphere = add('Geometry', 'Sphere')
            for source, output, target, port in (
                (region, 'C', population, 'R'),
                (population, 'P', cross, 'A'), (population, 'P', cross, 'B'),
                (cross, 'A', distance, 'A'), (cross, 'B', distance, 'B'),
                (distance, 'L', bounds, 'N'), (bounds, 'I', deconstruct, 'I'),
                (deconstruct, 'S', half, 'A'), (divisor, 'Number', half, 'B'),
                (population, 'P', sphere, 'O'), (half, 'R', sphere, 'R'),
            ):
                source.outputs()[output].connect_to(target.inputs()[port])
            identity = editor.project_uuid, sphere.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None and len(tuple(children(owner().shape))) == 100, timeout=15)
            outputs = editor.evaluation.results
            points = tuple(p.xyz for p in outputs[population.id].outputs['P'].values())
            distances = outputs[distance.id].outputs['L'].values()
            self.assertEqual(len(distances), 4950)
            expected = min(math.dist(a, b) for a, b in combinations(points, 2)) / 2
            self.assertGreater(expected, 0)
            self.assertAlmostEqual(outputs[half.id].outputs['R'], expected)
            native_spheres = [BRepAdaptor_Surface(self.geo.faces_of(shape)[0]).Sphere()
                              for shape in children(owner().shape)]
            self.assertEqual({s.Location().Coord() for s in native_spheres}, set(points))
            for native in native_spheres:
                self.assertAlmostEqual(native.Radius(), expected)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_two_hundred_objects_share_one_owner_and_live_revisions_keep_identity(self):
        from noodles.backend.grid_reference_native import children

        box = SolidValue('beam', 'box', PlaneValue(), (3, 1, 1))
        points = [PointValue(str(i), (i*5., 1., 0.)) for i in range(200)]
        scales = [VectorValue((1., 1., 1. + i/200.)) for i in range(200)]
        data = {'G': box, 'P': points, 'T': scales}
        owner = self.publish(model('objects_on_points', data))
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertTrue(owner.mesh_ready)
        shapes = tuple(children(owner.shape))
        self.assertEqual(len(shapes), 200)
        self.assertAlmostEqual(self.geo.volume(shapes[-1]), 3*(1+199/200))
        low, high = self.geo.bbox(shapes[-1])
        self.assertAlmostEqual((low[0] + high[0])/2, points[-1].xyz[0])
        changed = self.publish(model('objects_on_points', {**data, 'P': points[:10], 'T': scales[:10]}))
        self.assertEqual(owner.id, changed.id)
        self.assertEqual(len(tuple(children(changed.shape))), 10)

    def test_population_uses_real_occ_and_keeps_existing_points(self):
        from noodles.backend.population import evaluate, normalize_state

        for operation, inputs, check in (
            ('populate_2d', {'R': rectangle('r', 20, 8, (0, 0, 0), PlaneValue(axis_x=(0, 1, 0), normal=(1, 0, 0)))},
             lambda p: abs(p[0]) < 1e-8 and abs(p[1]) <= 10 and abs(p[2]) <= 4),
            ('populate_geometry', {'G': SolidValue('sphere', 'sphere', PlaneValue(), (5,))},
             lambda p: math.hypot(*p) <= 5.000001),
        ):
            params = normalize_state(operation, {'project_uuid': state('array')['project_uuid'],
                                                  'node_uuid': state('array')['node_uuid']})
            count = 9999 if operation == 'populate_2d' else 30
            inputs.update(N=count, S=-7, P=PointValue('origin', (0, 0, 0)))
            waiting = evaluate(operation, params, inputs)
            plan = waiting['_sampling']
            request = self.call('geometry.population', plan)
            self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
            reply = self.call('geometry.job', request)
            self.assertEqual(reply['state'], 'complete', reply)
            result = evaluate(operation, {**params, 'sampling_details': {
                'signature': plan['signature'], 'values': reply['measurements']}}, inputs)['P']
            self.assertEqual(result.count, count + 1)
            self.assertIs(result.values()[0], inputs['P'])
            self.assertTrue(all(check(p.xyz) for p in result.values()))
            self.assertFalse(self.window.scene.objects)

    def test_population_graph_drives_placement_and_properties_hide_only_source(self):
        from Qt import QtCore
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow
        from noodles.backend.grid_reference_native import children

        gui = MainWindow()
        gui.serpentine.stop()
        gui.point_service.client = self.client
        gui.point_service.start()
        gui.show()
        try:
            region = gui.add_node('NoodleS.Geometry.RectangleNode')
            population = gui.add_node('NoodleS.Geometry.Populate2DNode')
            box = gui.add_node('NoodleS.Geometry.BoxNode')
            placed = gui.add_node('NoodleS.Geometry.ObjectsOnPointsNode')
            population.set_property('parameters', {'N': 6, 'S': 12})
            region.outputs()['C'].connect_to(population.inputs()['R'])
            population.outputs()['P'].connect_to(placed.inputs()['P'])
            box.outputs()['G'].connect_to(placed.inputs()['G'])

            def owner(node):
                return self.bridge.points.owner((gui.project_uuid, node.curve_state()['node_uuid'], 0))

            self.wait_for(lambda: owner(placed) is not None and owner(region) is not None and owner(box) is not None)
            result = owner(placed)
            self.assertEqual(len(tuple(children(result.shape))), 6)
            self.assertIsNone(owner(population))
            self.assertEqual(len(self.window.scene.objects), 3)
            checkbox = gui.properties.curve_properties.show_parent
            self.assertTrue(checkbox.isVisible() and checkbox.isChecked())
            QTest.mouseClick(checkbox, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, checkbox.height() // 2))
            self.wait_for(lambda: not owner(box).visible)
            self.assertTrue(owner(region).visible)
            population.set_property('parameters', {'N': 6, 'S': 22})
            self.wait_for(lambda: owner(placed)._shape is not result._shape)
            self.assertEqual(owner(placed).id, result.id)
        finally:
            gui.graph.undo_stack().setClean()
            gui.close()

    def test_map_surface_on_cylinder_and_across_trimmed_hole(self):
        from noodles.backend.map_surface_native import map_shape
        from noodles.backend.surface_native import planar_surface_shape

        g = self.geo
        outer = g.make_rectangle((0, 0, 0), (10, 10, 0))
        source = g.planar_face(outer)
        hole = g.make_circle((5, 5, 0), 1.)
        target_with_hole = planar_surface_shape([outer, hole])
        crossing = g.make_line((1, 5, 0), (9, 5, 0))
        for src, dst, label in ((source, target_with_hole, 'Target'), (target_with_hole, source, 'Source')):
            with self.assertRaisesRegex(ValueError, 'trimmed '+label):
                map_shape(crossing, src, dst)
        cylinder = SolidValue('target', 'cylinder', PlaneValue(), (3, 8), False)
        on_surface = map_shape(crossing, source, materialize(cylinder))
        for x, y, z in g.sample_curve(on_surface, 13):
            self.assertAlmostEqual(math.hypot(x, y), 3, delta=1e-6)
            self.assertAlmostEqual(z, 4, delta=1e-6)
        arc = g.make_arc_3pt((3*math.cos(-.3), 3*math.sin(-.3), 4), (3, 0, 4),
                             (3*math.cos(.3), 3*math.sin(.3), 4))
        native_source = materialize(cylinder)
        other = materialize(SolidValue('other', 'cylinder', PlaneValue(), (6, 10), False))
        seam = map_shape(arc, native_source, other)
        self.assertAlmostEqual(g.curve_length(seam), 3.6, delta=1e-6)

    def test_map_surface_one_compound_and_keeps_last_good_curve_on_trim_error(self):
        from noodles.backend.curves import circle

        op = 'map_surface'
        surface_state = state('planar_surface')
        outer = rectangle('outer', 10, 10, (0, 0, 0), PlaneValue())
        inner = circle('hole', (0, 0, 0), 1., PlaneValue())
        source = evaluate_operation('planar_surface', surface_state, {'C': outer})['G'].values()[0]
        target = evaluate_operation('planar_surface', surface_state, {'C': [outer, inner]})['G'].values()[0]
        curve = line('c', (-4, 0, 0), (4, 0, 0))
        good = self.publish(model(op, {'C': curve, 'S': source, 'T': source}))
        request = self.call('geometry.prepare', {'model': model(op, {'C': curve, 'S': source, 'T': target})})
        self.wait_for(lambda: self.bridge.points.jobs[request['job_id']]['state'] != 'preparing')
        result = self.call('geometry.job', request)
        self.assertEqual(result['state'], 'error')
        self.assertIn('trimmed Target', result['error'])
        self.assertIs(self.window.scene.get(good.id)._shape, good._shape)

    def test_commands_publish_independently_of_editor(self):
        from serpentine3d.commands import base, transform
        from noodles.serpentine_plugin.NoodleSBridge import _register_commands

        self.window._noodles_bridge = self.bridge
        original = base.resolve('array')
        _register_commands(self.ctx)
        self.assertIs(base.resolve('array'), original)
        g, scene = self.geo, self.window.scene
        wire = scene.add(g.make_rectangle((0, 0, 0), (10, 10, 0)))
        face = scene.add(g.planar_face(wire.shape))
        point = scene.add(g.make_point((20, 0, 0)))
        vertices = [scene.add(g.make_point(xyz)) for xyz in ((0, 0, 0), (4, 0, 0), (0, 4, 0))]
        curve = scene.add(g.make_line((1, 2, 0), (8, 9, 0)))
        for command, answers in (
            ('planesurface', ((0, 0, 0), 10., 8.)),
            ('populate2d', ([face], 12, 4)),
            ('populategeometry', ([face], 12, 4)),
            ('delaunaymesh', (vertices,)),
            ('constructmesh', (vertices, '0 1 2')),
            ('objectsonpoints', ([curve], [point], 1.)),
            ('mapsurface', ([curve], [face], [face])),
        ):
            with self.subTest(command=command):
                context = SimpleNamespace(echo=[].append,
                    cplane=SimpleNamespace(origin=(0, 0, 0), xdir=(1, 0, 0), normal=(0, 0, 1)))
                before = len(scene.objects)
                action = base.resolve(command).fn(context)
                next(action)
                for value in answers[:-1]:
                    action.send(value)
                with self.assertRaises(StopIteration):
                    action.send(answers[-1])
                self.wait_for(lambda: len(scene.objects) == before+1)
                if command in ('delaunaymesh', 'constructmesh'):
                    self.assertEqual(list(scene.objects.values())[-1].kind, 'mesh')

    def test_noodles_command_starts_editor_from_installed_location(self):
        import importlib.util
        from pathlib import Path
        from unittest.mock import patch

        from serpentine3d.commands import base
        from noodles.install_bridge import install

        target = install(Path(self.folder.name) / 'isolated plugins')
        spec = importlib.util.spec_from_file_location('noodles_command_test', target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.importlib, 'import_module'):
            module._register_commands(self.ctx)
        command = base.resolve('noodles')
        self.assertFalse(command.mutates)
        self.assertFalse(command.repeatable)
        messages = []
        context = SimpleNamespace(echo=messages.append)
        with (patch.object(self.ctx.window, '_noodles_bridge', self.bridge, create=True),
              patch.object(module.subprocess, 'Popen') as launch):
            list(command.fn(context))
        root = Path(__file__).resolve().parents[1]
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0], [str(root / '.venv' / 'Scripts' / 'pythonw.exe'),
                                                   '-E', str(root / 'NoodleS.pyw'),
                                                   '--bridge-session', self.bridge.session_id])
        self.assertEqual(launch.call_args.kwargs['cwd'], root)
        self.assertNotIn('QT_QPA_PLATFORM', launch.call_args.kwargs['env'])
        self.assertEqual(messages, ['Starting NoodleS…'])

        (target.parent / '_noodles_core' / 'editor-path.txt').unlink()
        messages.clear()
        with patch.object(self.ctx.window, '_noodles_bridge', self.bridge, create=True):
            list(command.fn(context))
        self.assertIn('Run the NoodleS bridge installer', messages[0])
