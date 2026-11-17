"""Curve sampling contract and isolated native OCC integration."""
import math
import unittest

import test_point_native as fixture
from noodles.backend.arithmetic import VectorValue
from noodles.backend.curve_sampling import evaluate_sampling
from noodles.backend.curves import circle, cross, dot, line, plane, polyline
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.range import evaluate_range
from noodles.backend.splines import PendingGeometry


class SamplingDataTests(unittest.TestCase):
    def test_cylindrical_point_and_orient_use_full_plane_axes(self):
        from noodles.backend.curves import PlaneValue
        from noodles.core import compute

        source = PlaneValue((1, 2, 3), (1, 0, 0), (0, -1, 0))
        point = compute('point_cylindrical', {}, {'P': source, 'A': math.pi / 2, 'R': 2, 'E': 4})['P'].values()[0]
        self.assertLess(math.dist(point.xyz, (1, -2, 5)), 1e-12)
        target = PlaneValue((7, 8, 9), (0, 1, 0), (0, 0, 1))
        mapped = compute('orient', {}, {'A': source, 'B': target, 'G': point})['G'].values()[0]
        self.assertLess(math.dist(mapped.xyz, (5, 8, 13)), 1e-12)

    def test_paths_matching_and_empty_branches(self):
        a = line('a', (0, 0, 0), (10, 0, 0))
        b = line('b', (0, 0, 0), (0, 20, 0))
        tree = DataTree((Branch((2,), (a, b)), Branch((5,), ()), Branch((2, 0), (a,))))
        pending = evaluate_sampling('divide_curve', {}, {'C': tree})
        self.assertEqual([b.path for b in pending['P'].branches], [(2, 0), (2, 1), (5, 0), (2, 0, 0)])
        self.assertIsInstance(pending['Count'], PendingGeometry)
        graft = evaluate_sampling('divide_curve', {'tree_modes': {'C': 'graft'}}, {'C': [a, b], 'N': [2, 5]})
        self.assertEqual([r['count'] for r in graft['_sampling']['plan']['rows']], [2, 5])
        domain = evaluate_sampling('curve_domain', {}, {'C': tree})
        self.assertEqual([b.path for b in domain['D'].branches], [(2,), (5,), (2, 0)])
        self.assertEqual(domain['D'].count, 3)
        self.assertEqual(evaluate_sampling('divide_curve', {}, {})['Count'], 0)
        with self.assertRaisesRegex(ValueError, 'integer'):
            evaluate_sampling('divide_curve', {}, {'C': a, 'N': 2.5})
        with self.assertRaisesRegex(ValueError, '5,000'):
            evaluate_sampling('divide_curve', {}, {'C': [a]*11, 'N': 500})

    def test_frame_parameter_tree_uses_child_then_parent_and_shared_values(self):
        a = line('a', (0, 0, 0), (10, 0, 0))
        b = line('b', (0, 0, 0), (0, 20, 0))
        c = line('c', (0, 0, 0), (0, 0, 30))
        curves = DataTree((Branch((2,), (a, b)), Branch((5,), (c,))))
        t = DataTree((Branch((2,), (.1, .2)), Branch((2, 1), (.3,)), Branch((5,), (.4,))))
        result = evaluate_sampling('frame', {}, {'C': curves, 't': t})
        self.assertEqual([b.path for b in result['F'].branches], [(2, 0), (2, 1), (5, 0)])
        self.assertEqual([row['parameters'] for row in result['_sampling']['plan']['rows']], [(.1, .2), (.3,), (.4,)])
        shared = evaluate_sampling('frame', {'tree_modes': {'t': 'flatten'}}, {'C': curves, 't': t})
        self.assertEqual([row['parameters'] for row in shared['_sampling']['plan']['rows']], [(.1, .2, .3, .4)]*3)
        with self.assertRaisesRegex(ValueError, 'matching nonempty'):
            evaluate_sampling('frame', {}, {'C': [a, b], 't': t})
        with self.assertRaisesRegex(ValueError, '512'):
            evaluate_sampling('frame', {}, {'C': a, 't': [0]*513})


class SamplingNativeTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def sample(self, operation, inputs):
        pending = evaluate_sampling(operation, self.parameters, inputs)
        request = pending['_sampling']
        job = self.call('geometry.sample', request)
        self.wait_for(lambda: self.bridge.geometry.jobs[job['job_id']]['state'] != 'preparing')
        data = self.call('geometry.job', job)
        self.assertEqual(data['state'], 'complete', data)
        details = {'signature': request['signature'], 'values': data['measurements']}
        return evaluate_sampling(operation, {**self.parameters, 'sampling_details': details}, inputs)

    def test_project_mixed_points_and_curves_and_measure_projected_length(self):
        from noodles.backend.curves import PlaneValue
        from noodles.backend.geometry import geometry_object_from_outputs, normalize_geometry_state
        from noodles.backend.grid_reference_native import children
        from noodles.backend.point import PointValue
        from noodles.core import compute

        target = PlaneValue((0, 0, 2))
        source = PlaneValue((0, 0, 4), (1, 0, 0), (0, 3, 4))
        ring = circle('ring', source.origin, 3, source)
        wire = polyline('wire', ((0, 0, 0), (3, 0, 0), (3, 0, 4), (3, 4, 4)))
        point = PointValue('point', (5, 6, 4))
        data = DataTree((Branch((2,), (point, ring)), Branch((5,), (wire,)), Branch((9,), ())))
        outputs = compute('project', self.parameters, {'G': data, 'P': target})
        projected_point, projected_ring, projected_wire = outputs['G'].values()
        self.assertEqual(projected_point.xyz, (5, 6, 2))
        self.assertEqual([b.path for b in outputs['G'].branches], [(2,), (5,), (9,)])
        state = normalize_geometry_state('project', self.parameters)
        model = geometry_object_from_outputs(state, outputs).to_wire()
        job = self.call('points.prepare', {'model': model, 'name': 'Project'})
        self.wait_for(lambda: self.bridge.points.jobs[job['job_id']]['state'] != 'preparing')
        result = self.call('points.job', job)
        self.assertEqual(result['state'], 'complete', result)
        owner = self.window.scene.get(result['object_id'])
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertEqual(len(tuple(children(owner.shape))), 3)

        lengths = self.sample('curve_length', {'C': DataTree((
            Branch((2,), (projected_ring, projected_wire)), Branch((5,), ())))})['L']
        from noodles.backend.curves import ellipse_perimeter
        self.assertAlmostEqual(lengths.values()[0], ellipse_perimeter(3., 2.4), places=7)
        self.assertAlmostEqual(lengths.values()[1], 7.)
        self.assertEqual([b.path for b in lengths.branches], [(2,), (5,)])
        oblique = compute('project', {}, {'G': point, 'P': target, 'D': VectorValue((1, 0, 1))})['G']
        self.assertEqual(oblique.values()[0].xyz, (3, 6, 2))
        with self.assertRaisesRegex(ValueError, 'parallel'):
            compute('project', {}, {'G': point, 'P': target, 'D': VectorValue((1, 0, 0))})

    def test_projectplane_command_without_editor(self):
        from types import SimpleNamespace
        from serpentine3d.commands import base
        from noodles.backend.grid_reference_native import children
        from noodles.backend.operation_native import register_commands

        self.window._noodles_bridge = self.bridge
        register_commands(self.ctx)
        scene = self.window.scene
        source = scene.add(self.geo.make_point((5, 6, 4)))
        cplane = SimpleNamespace(origin=(0, 0, 2), xdir=(1, 0, 0), normal=(0, 0, 1))
        messages = []
        command = base.resolve('projectplane').fn(SimpleNamespace(cplane=cplane, echo=messages.append))
        next(command)
        command.send([source])
        command.send('Along Vector')
        command.send((0, 0, 0))
        with self.assertRaises(StopIteration):
            command.send((1, 0, 1))
        self.wait_for(lambda: any(message.startswith('Created ') for message in messages))
        projected, = (item for item in scene.objects.values() if item.id != source.id)
        point, = children(projected.shape)
        self.assertEqual(tuple(self.geo.point_coords(point)), (3, 6, 2))

    def test_closest_point_and_evaluate_agree_on_trimmed_wire_and_circle(self):
        from noodles.backend.point import PointValue

        curves = DataTree((Branch((2,), (polyline('wire', ((8, 0, 0), (2, 0, 0), (2, 7, 0))),)),
                           Branch((5,), (circle('circle', (0, 0, 0), 4, plane('XY')),))))
        points = DataTree((Branch((2,), (PointValue('wire-point', (1, 3, 0)), PointValue('before', (10, 0, 0)))),
                           Branch((5,), (PointValue('circle-point', (0, 6, 0)),))))
        for normalized in (False, True):
            closest = self.sample('curve_closest_point', {'C': curves, 'P': points, 'N': normalized})
            sampled = self.sample('evaluate_curve', {'C': curves, 't': closest['t'], 'N': normalized})
            self.assertEqual(tuple(b.path for b in sampled['P'].branches), ((2,), (5,)))
            self.assertEqual(closest['D'].values(), (1, 2, 2))
            expected = ((2, 3, 0), (8, 0, 0), (0, 4, 0))
            for p, q, goal in zip(closest['P'].values(), sampled['P'].values(), expected, strict=True):
                self.assertLess(math.dist(p.xyz, goal), 1e-10)
                self.assertLess(math.dist(p.xyz, q.xyz), 1e-10)

    def test_sort_along_curve_preserves_original_points_and_order_for_equal_parameters(self):
        from noodles.backend.point import PointValue

        a, b, c, d = [PointValue(str(i), point) for i, point in
                      enumerate(((1, 2, 0), (8, 5, 0), (8, -5, 0), (4, 1, 0)))]
        guide = line('reversed', (10, 0, 0), (0, 0, 0))
        points = DataTree((Branch((2,), (a, b, c, d), ('a', 'b', 'c', 'd')), Branch((5,), ())))
        result = self.sample('sort_along_curve', {'P': points, 'C': guide})
        self.assertEqual([branch.path for branch in result['P'].branches], [(2,), (5,)])
        self.assertEqual(result['P'].branches[0], Branch((2,), (b, c, d, a), ('b', 'c', 'd', 'a')))
        self.assertEqual(result['I'].values(), (1, 2, 3, 0))
        self.assertEqual(result['t'].values(), (2., 2., 6., 9.))
        self.assertFalse(self.window.scene.objects)

    def test_book_seashell_publishes_one_loft_from_ordered_spiral_sections(self):
        from OCP.BRepCheck import BRepCheck_Analyzer
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        shape = self.geo.make_ellipse_axis((26, 0, 0), (1, 0, 0), 26, 47, (0, 0, 1))
        source = self.window.scene.add(shape, name='Shell opening')
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(category, name):
                return editor.add_node(f'NoodleS.{category}.{name}Node')

            def number(value):
                node = add('Inputs', 'Number')
                node.set_property('value', value)
                return node

            def link(source_node, output, target, port):
                source_node.outputs()[output].connect_to(target.inputs()[port])

            profile = add('Geometry', 'Curves')
            profile.set_property('mode', 'reference')
            capture = editor.properties.curve_properties.capture
            self.wait_for(capture.isVisible)
            QTest.mouseClick(capture, Qt.LeftButton)
            self.wait_for(lambda: len(profile.get_property('references')) == 1)
            turns = add('Inputs', 'Slider')
            turns.set_property('mode', 'integer')
            turns.set_property('value', 4)
            domain, values = add('Math', 'Domain'), add('Math', 'Range')
            steps, angle, radius = [add('Math', 'Multiplication') for _ in range(3)]
            power = add('Math', 'Power')
            power.set_property('base', .5)
            tau = add('Math', 'Expression')
            tau.set_property('formula', '2*pi')
            sites = add('Geometry', 'PointCylindrical')
            spiral = add('Geometry', 'InterpCurve')
            closest = add('Operations', 'CurveClosestPoint')
            curvature = add('Operations', 'CurveCurvature')
            evaluate = add('Operations', 'EvaluateCurve')
            binormal = add('Math', 'CrossProduct')
            frames = add('Math', 'ConstructPlane')
            scale = add('Geometry', 'Scale')
            scale.set_property('parameters', {'Cp': True})
            orient = add('Geometry', 'Orient')
            loft = add('Geometry', 'Loft')
            loft.set_property('parameters', {'A': False})
            for wire in (
                (turns, 'Number', domain, 'B'), (turns, 'Number', steps, 'A'), (number(10), 'Number', steps, 'B'),
                (domain, 'D', values, 'D'), (steps, 'R', values, 'N'), (values, 'R', angle, 'A'),
                (tau, 'R', angle, 'B'), (values, 'R', power, 'B'), (power, 'R', radius, 'A'),
                (number(100), 'Number', radius, 'B'), (angle, 'R', sites, 'A'), (radius, 'R', sites, 'R'),
                (radius, 'R', sites, 'E'), (sites, 'P', spiral, 'P'), (sites, 'P', closest, 'P'),
                (spiral, 'C', closest, 'C'), (spiral, 'C', curvature, 'C'), (spiral, 'C', evaluate, 'C'),
                (closest, 't', curvature, 't'), (closest, 't', evaluate, 't'), (curvature, 'K', binormal, 'A'),
                (evaluate, 'T', binormal, 'B'), (curvature, 'P', frames, 'O'), (curvature, 'K', frames, 'X'),
                (binormal, 'V', frames, 'Y'), (profile, 'C', scale, 'G'), (power, 'R', scale, 'F'),
                (scale, 'G', orient, 'G'), (frames, 'P', orient, 'B'), (orient, 'G', loft, 'C'),
            ):
                link(*wire)
            identity = editor.project_uuid, loft.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None, timeout=30)
            initial = owner()
            self.assertTrue(BRepCheck_Analyzer(initial.shape).IsValid())
            self.assertEqual(editor.evaluation.results[orient.id].outputs['Count'], 41)
            self.assertEqual(editor.evaluation.results[loft.id].outputs['SC'].values(), (41,))
            self.assertEqual(len(editor.point_service.models[sites.id]['model']['branches'][0]['points']), 41)
            self.assertTrue(all(d < 1e-6 for d in editor.evaluation.results[closest.id].outputs['D'].values()))
            self.assertIs(self.window.scene.get(source.id).shape, shape)
            QTest.keyClick(turns.get_widget('value').slider, Qt.Key_Left)
            self.wait_for(lambda: owner().shape is not initial.shape and
                          editor.evaluation.results[orient.id].outputs.get('Count') == 31, timeout=30)
            self.assertEqual(owner().id, initial.id)
            self.assertTrue(BRepCheck_Analyzer(owner().shape).IsValid())
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_circle_and_wire_kinks_with_no_scene_objects(self):
        c = circle('circle', (0, 0, 0), 3, plane('XY'))
        wire = polyline('wire', ((0, 0, 0), (2, 0, 0), (2, 7, 0)))
        result = self.sample('divide_curve', {'C': [c, wire], 'N': [4, 3], 'K': [False, True]})
        self.assertEqual(result['Count'], 9)
        circle_params, wire_params = (branch.items for branch in result['t'].branches)
        for i, t in enumerate(circle_params):
            self.assertAlmostEqual(t, i*math.pi/2)
        for a, b in zip(wire_params, (0, 2, 3, 6, 9), strict=True):
            self.assertAlmostEqual(a, b)
        self.assertEqual(result['P'].branches[1].items[1].xyz, (2, 0, 0))
        for tangent in result['T'].values():
            self.assertAlmostEqual(math.hypot(*tangent.xyz), 1)
        domains = self.sample('curve_domain', {'C': [c, wire]})
        self.assertEqual(domains['D'].values(), (DomainValue(0, math.tau), DomainValue(0, 9)))
        self.assertFalse(self.window.scene.objects)

    def test_curvature_magnitude_and_point_in_tilted_closed_curve(self):
        from noodles.backend.point import PointValue
        rail = circle('tilted', (3, 2, 1), 4, plane('YZ'))
        result = self.sample('curve_curvature', {'C': rail, 't': [0, .25]})
        self.assertEqual(result['P'].values()[0].xyz, (3, 6, 1))
        for vector, expected in zip(result['K'].values(), ((0, -.25, 0), (0, 0, -.25))):
            self.assertLess(math.dist(vector.xyz, expected), 1e-12)
        straight = self.sample('curve_curvature', {'C': line('line', (0, 0, 0), (5, 0, 0))})
        self.assertEqual(straight['K'].values(), (VectorValue((0, 0, 0)),))
        points = [PointValue(str(i), point) for i, point in enumerate(((3, 2, 1), (3, 6, 1), (3, 7, 1), (4, 2, 1)))]
        classified = self.sample('point_in_curve', {'C': rail, 'P': points})
        self.assertEqual(classified['R'].values(), (2, 1, 0, 0))
        self.assertEqual(classified['I'].values(), (True, False, False, False))
        self.assertFalse(self.window.scene.objects)

    def test_book_conditional_curve_offset_publishes_one_interpcurve(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        points = [(0, 0, 0), (10, -2, 0), (20, 0, 0), (18, 8, 0), (11, 5, 0), (6, 13, 0), (-2, 10, 0)]
        source = self.window.scene.add(self.geo.make_interp_curve(points, closed=True))
        self.window.selection.set([source.id])
        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            def add(category, node):
                return editor.add_node(f'NoodleS.{category}.{node}Node')

            curves = add('Geometry', 'Curves')
            panel = editor.properties.curve_properties
            self.wait_for(lambda: editor.properties.node_id == curves.id)
            QTest.mouseClick(panel.sources['reference'], Qt.LeftButton)
            self.wait_for(panel.capture.isVisible)
            QTest.mouseClick(panel.capture, Qt.LeftButton)
            self.wait_for(lambda: len(curves.get_property('references')) == 1)
            divide = add('Operations', 'DivideCurve')
            divide.set_property('parameters', {'N': 100})
            curvature = add('Operations', 'CurveCurvature')
            curvature.set_property('parameters', {'N': False})
            unit = add('Math', 'UnitVector')
            probe = add('Math', 'Addition')
            inside = add('Operations', 'PointInCurve')
            equal = add('Math', 'Equality')
            equal.set_property('b', 2)
            dispatch = add('Data', 'Dispatch')
            reverse = add('Math', 'ReverseVector')
            weave = add('Data', 'Weave')
            final_points = add('Math', 'Addition')
            check = add('Operations', 'PointInCurve')
            interp = add('Geometry', 'InterpCurve')
            interp.set_property('parameters', {'C': True})
            for src, out, dst, port in (
                (curves, 'C', divide, 'C'), (curves, 'C', curvature, 'C'), (divide, 't', curvature, 't'),
                (curvature, 'K', unit, 'V'), (curvature, 'P', probe, 'A'), (unit, 'U', probe, 'B'),
                (probe, 'R', inside, 'P'), (curves, 'C', inside, 'C'),
                (inside, 'R', equal, 'A'), (equal, '=', dispatch, 'P'), (unit, 'U', dispatch, 'L'),
                (dispatch, 'A', reverse, 'V'), (dispatch, 'B', weave, '0'),
                (reverse, 'V', weave, '1'), (equal, '=', weave, 'P'),
                (curvature, 'P', final_points, 'A'), (weave, 'W', final_points, 'B'),
                (final_points, 'R', interp, 'P'), (final_points, 'R', check, 'P'), (curves, 'C', check, 'C'),
            ):
                src.outputs()[out].connect_to(dst.inputs()[port])

            def values(node, port):
                result = editor.evaluation.results.get(node.id) if editor.evaluation else None
                return result.outputs[port].values() if result and not result.error else ()

            identity = editor.project_uuid, interp.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None and len(values(check, 'R')) == 100
                          and type(values(check, 'R')[0]) is int, timeout=15)
            self.assertEqual(set(values(inside, 'I')), {True, False})
            self.assertEqual(values(equal, '='), values(inside, 'I'))
            self.assertEqual(values(check, 'R'), (0,) * 100)
            for a, b in zip(values(curvature, 'P'), values(final_points, 'R'), strict=True):
                self.assertAlmostEqual(math.dist(a.xyz, b.xyz), 1)
            self.assertEqual(set(self.window.scene.objects), {source.id, owner().id})
            self.assertTrue(self.geo.is_closed_curve(self.geo.unwrap_compound(owner().shape)))
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_perp_frames_match_divide_and_guide_or_curvature_orientation(self):
        c = circle('circle', (0, 0, 0), 3, plane('XY'))
        wire = polyline('wire', ((0, 0, 0), (2, 0, 0), (2, 7, 0)))
        vertical = line('line', (0, 0, 0), (0, 0, 10))
        inputs = {'C': [c, wire, vertical], 'N': [4, 9, 2]}
        divided = self.sample('divide_curve', inputs)
        frames = self.sample('perp_frames', inputs)
        self.assertEqual(frames['Count'], 17)
        for port in ('P', 'T', 't'):
            self.assertEqual(frames[port], divided[port])
        for frame, point, tangent in zip(frames['F'].values(), frames['P'].values(), frames['T'].values()):
            self.assertEqual(frame.origin, point.xyz)
            self.assertEqual(frame.normal, tangent.xyz)
            self.assertAlmostEqual(dot(frame.axis_x, frame.normal), 0)
            self.assertAlmostEqual(math.hypot(*frame.axis_y), 1)
            self.assertLess(math.dist(cross(frame.axis_x, frame.axis_y), frame.normal), 1e-12)
        self.assertEqual(frames['F'].branches[0].items[0].axis_x, (0., 0., 1.))
        self.assertEqual(frames['F'].branches[2].items[0].axis_x, (1., 0., 0.))
        curved = self.sample('perp_frames', {**inputs, 'A': False})
        self.assertLess(math.dist(curved['F'].branches[0].items[0].axis_x, (-1., 0., 0.)), 1e-12)
        self.assertEqual(curved['F'].branches[2].items[0].axis_x, (1., 0., 0.))
        guided = self.sample('frame', {'C': vertical, 't': .5, 'G': VectorValue((0, 1, 0))})
        self.assertEqual(guided['F'].values()[0].axis_x, (0., 1., 0.))
        self.assertFalse(self.window.scene.objects)

    def test_trimmed_reference_domain_and_equal_length_on_rational_spline(self):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.GCPnts import GCPnts_AbscissaPoint
        from noodles.backend.curves import curve_from_wire
        from noodles.backend.spline_native import describe_spline, materialize_spline

        recipe = curve_from_wire({'key': 'rational', 'kind': 'curve', 'points': [[3, 0, 0], [3, 1, 0], [0, 1, 0]],
                                  'degree': 2, 'closed': False, 'periodic': False, 'knots': [0, 1],
                                  'multiplicities': [3, 3], 'weights': [1, .7, 1], 'domain': [0, 1]})
        spline = BRepAdaptor_Curve(materialize_spline(recipe)).BSpline()
        trimmed = BRepBuilderAPI_MakeEdge(spline, .2, .8).Edge()
        original = self.window.scene.add(trimmed, name='Trimmed spline')
        source = describe_spline(trimmed, 'reference', 'curve')
        result = self.sample('curve_domain', {'C': source})
        self.assertEqual(result['D'].values(), (DomainValue(.2, .8),))
        self.assertAlmostEqual(result['L'].values()[0], .6)
        parameters = evaluate_range({'steps': 4}, {'D': result['D']})['R']
        native = self.sample('frame', {'C': source, 't': parameters, 'N': False})
        normalized = self.sample('frame', {'C': source, 't': [0., .25, .5, .75, 1.]})
        self.assertEqual(native['t'], normalized['t'])
        self.assertEqual(native['F'], normalized['F'])
        for frame, t in zip(native['F'].values(), native['t'].values()):
            self.assertLess(math.dist(frame.origin, self.geo.pnt_tuple(spline.Value(t))), 1e-10)
        divided = self.sample('divide_curve', {'C': source, 'N': 4})
        t = divided['t'].values()
        self.assertEqual((t[0], t[-1]), (.2, .8))
        self.assertNotAlmostEqual(t[2], .5, places=3)
        adaptor = BRepAdaptor_Curve(trimmed)
        lengths = [GCPnts_AbscissaPoint.Length_s(adaptor, a, b) for a, b in zip(t, t[1:])]
        for length in lengths[1:]:
            self.assertAlmostEqual(length, lengths[0], places=6)
        self.assertEqual(set(self.window.scene.objects), {original.id})
        self.assertIs(self.window.scene.get(original.id)._shape, trimmed)

    def test_frame_updates_after_reference_edit_and_feeds_plane_preview(self):
        from noodles.window import MainWindow
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        scene = self.window.scene
        native = scene.add(self.geo.make_line((0, 0, 0), (0, 0, 8)), name='Live line')
        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            source = editor.add_node('NoodleS.Geometry.LineNode')
            source.set_property('mode', 'reference')
            self.wait_for(lambda: editor.properties.node_id == source.id)
            self.window.selection.set([native.id])
            editor._capture_points()
            self.wait_for(lambda: len(source.get_property('references')) == 1)
            domain = editor.add_node('NoodleS.Operations.CurveDomainNode')
            steps = editor.add_node('NoodleS.Math.RangeNode')
            frame = editor.add_node('NoodleS.Operations.FrameNode')
            preview = editor.add_node('NoodleS.Geometry.PlanePreviewNode')
            source.outputs()['C'].connect_to(domain.inputs()['C'])
            source.outputs()['C'].connect_to(frame.inputs()['C'])
            domain.outputs()['D'].connect_to(steps.inputs()['D'])
            steps.outputs()['R'].connect_to(frame.inputs()['t'])
            frame.outputs()['F'].connect_to(preview.inputs()['P'])
            editor.graph.clear_selection()
            frame.set_selected(True)
            self.wait_for(lambda: editor.properties.node_id == frame.id)
            checkbox = editor.properties.curve_properties.editors['N'][0]
            QTest.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(7, checkbox.height()//2))
            self.assertFalse(frame.get_property('parameters')['N'])

            def starts_at(position):
                result = editor.evaluation.results.get(frame.id)
                if not result or result.error or result.outputs['Count'] != 11:
                    return False
                planes = result.outputs['F'].values()
                return planes[0].origin == position and preview.id in editor.preview_service.nodes

            self.wait_for(lambda: starts_at((0, 0, 0)))
            shifted = self.geo.make_line((3, 4, 0), (3, 4, 8))
            scene.replace_shape(native.id, shifted)
            self.wait_for(lambda: starts_at((3, 4, 0)))
            overlay = editor.preview_service._frame(editor.preview_service.revision, editor.preview_service.nodes)
            self.assertEqual(self.call('previews.sync', overlay), {'state': 'complete', 'count': 11})
            self.assertEqual(self.bridge.previews.visible(scene)[0]['plane'].frame.origin, (3, 4, 0))
            self.assertEqual(set(scene.objects), {native.id})
            self.assertIs(scene.get(native.id)._shape, shifted)
        finally:
            editor.point_service.stop()
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_grid_to_interpcurve_to_divide_curve_in_editor(self):
        from noodles.window import MainWindow
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            grid = editor.add_node('NoodleS.Geometry.GridRectangleNode')
            curve = editor.add_node('NoodleS.Geometry.InterpCurveNode')
            divide = editor.add_node('NoodleS.Operations.DivideCurveNode')
            domain = editor.add_node('NoodleS.Operations.CurveDomainNode')
            grid.outputs()['P'].connect_to(curve.inputs()['P'])
            curve.outputs()['C'].connect_to(divide.inputs()['C'])
            curve.outputs()['C'].connect_to(domain.inputs()['C'])
            def output(node, port):
                result = editor.evaluation.results.get(node.id)
                return result.outputs.get(port) if result and not result.error else None

            self.wait_for(lambda: output(divide, 'Count') == 44)
            self.assertEqual([b.path for b in output(divide, 'P').branches], [(0,), (1,), (2,), (3,)])
            self.wait_for(lambda: isinstance(output(domain, 'D').values()[0], DomainValue) if output(domain, 'D') else False)
            self.assertEqual(output(domain, 'D').count, 4)
            editor.graph.clear_selection()
            divide.set_selected(True)
            self.wait_for(lambda: editor.properties.node_id == divide.id)
            field = editor.properties.curve_properties.editors['N'][0]
            field.setFocus()
            QTest.keyClick(field, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(field, '3')
            QTest.keyClick(field, Qt.Key_Return)
            self.wait_for(lambda: output(divide, 'Count') == 16)
            self.assertEqual([len(b.items) for b in output(divide, 'P').branches], [4]*4)
            self.assertNotIn(divide.id, editor.point_service.models)
            self.assertNotIn(domain.id, editor.point_service.models)
        finally:
            editor.point_service.stop()
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_book_shift_list_publishes_decagon_and_star_in_one_owner(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            circle_node = editor.add_node('NoodleS.Geometry.CircleNode')
            divide = editor.add_node('NoodleS.Operations.DivideCurveNode')
            shift = editor.add_node('NoodleS.Data.ShiftListNode')
            line_node = editor.add_node('NoodleS.Geometry.LineNode')
            slider = editor.add_node('NoodleS.Inputs.SliderNode')
            slider.set_property('mode', 'integer')
            slider.set_property('value', 1)
            circle_node.outputs()['C'].connect_to(divide.inputs()['C'])
            divide.outputs()['P'].connect_to(shift.inputs()['L'])
            slider.outputs()['Number'].connect_to(shift.inputs()['S'])
            shift.outputs()['L'].connect_to(line_node.inputs()['A'])
            divide.outputs()['P'].connect_to(line_node.inputs()['B'])

            identity = editor.project_uuid, line_node.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None
                          and editor.evaluation.results[line_node.id].outputs.get('Count') == 10)
            object_id = owner().id
            old_shape = owner().shape
            points = tuple(p.xyz for p in editor.evaluation.results[divide.id].outputs['P'].values())
            self.assertEqual(len(set(points)), 10)

            def check_edges(step):
                curves = editor.evaluation.results[line_node.id].outputs['C'].values()
                pairs = [(points[(i + step) % 10], p) for i, p in enumerate(points)]
                self.assertEqual([curve.points for curve in curves], pairs)
                edges = self.geo.edges_of(owner().shape)
                self.assertEqual(len(edges), 10)
                expected_length = math.dist(*pairs[0])
                for edge in edges:
                    self.assertAlmostEqual(self.geo.curve_length(edge), expected_length)

            check_edges(1)
            slider_control = slider.get_widget('value').slider
            QTest.keyClick(slider_control, Qt.Key_Right)
            QTest.keyClick(slider_control, Qt.Key_Right)
            self.assertEqual(slider.get_property('value'), 3)
            self.wait_for(lambda: not owner().shape.IsSame(old_shape))
            check_edges(3)
            self.assertEqual(owner().id, object_id)
            self.assertNotIn(shift.id, editor.point_service.models)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
