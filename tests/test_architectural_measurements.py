"""Section, Area, Sum and Volume through the real Qt graph and OCC bridge."""
import math
import unittest

import test_point_native as fixture
from noodles.backend.curves import PlaneValue, circle, line, polyline, rectangle
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.geometry import evaluate_geometry
from noodles.backend.point import PointValue
from noodles.backend.solids import SolidValue
from noodles.backend.splines import spline
from noodles.core import compute


class MeasurementDataTests(unittest.TestCase):
    def test_nonuniform_scale_uses_local_axes_and_preserves_tree_paths(self):
        frame = PlaneValue((5, 6, 7), (0, 1, 0))
        points = DataTree((Branch((2,), (PointValue('p', (6, 8, 10)),)), Branch((3,), ())))
        result = compute('scale_non_uniform', {}, {'G': points, 'P': frame, 'X': 2, 'Y': -3, 'Z': .5})['G']
        self.assertEqual(result.values()[0].xyz, (2., 10., 8.5))
        self.assertEqual(result.branches[1], Branch((3,), ()))
        with self.assertRaisesRegex(ValueError, 'Scale factors'):
            compute('scale_non_uniform', {}, {'G': points, 'X': 0})

    def test_plane_fit_and_deconstruct_preserve_branches_and_measure_noise(self):
        points = tuple(PointValue(str(i), (x, y, 4 + z)) for i, (x, y, z) in enumerate(
            ((-2, -3, -.1), (-2, 3, .1), (2, -3, .1), (2, 3, -.1))))
        plane = compute('plane_fit', {}, {'P': DataTree((Branch((2,), points), Branch((3,), ())))})
        self.assertAlmostEqual(plane['D'].values()[0], .1)
        self.assertAlmostEqual(plane['R'].values()[0], .1)
        components = compute('deconstruct_plane', {}, {'P': plane['P']})
        self.assertEqual(components['O'].values()[0].xyz, (0., 0., 4.))
        self.assertEqual(components['Z'].values()[0].xyz, (0., 0., 1.))
        self.assertEqual(components['Z'].branches[1], Branch((3,), ()))
        oblique = [PointValue(str(i), (x, y, 4 + 2*x + 3*y)) for i, (x, y) in enumerate(((0, 0), (3, 0), (0, 2), (3, 2)))]
        fitted = compute('plane_fit', {}, {'P': oblique})
        self.assertLess(fitted['D'].values()[0], 1e-12)
        self.assertAlmostEqual(abs(fitted['P'].values()[0].normal[2]), 1/math.sqrt(14))
        straight = [PointValue(str(i), (i, 2*i, 3*i)) for i in range(3)]
        with self.assertRaisesRegex(ValueError, 'noncollinear'):
            compute('plane_fit', {}, {'P': straight})

    def test_contour_offsets_follow_the_plane_normal(self):
        box = SolidValue('box', 'box', PlaneValue(), (10, 10, 10))
        base = PlaneValue((1, 2, 3), (0, 1, 0), (1, 0, 0))
        levels = evaluate_geometry('contour', {}, {'B': box, 'P': base, 'D': 2., 'N': 3})
        plan = levels['_sampling']['plan']
        self.assertEqual([row[1]['origin'] for row in plan['rows']], [[1, 2, 3], [3, 2, 3], [5, 2, 3]])
        self.assertEqual([b.path for b in levels['C'].branches], [(0, 0), (0, 1), (0, 2)])
        with self.assertRaisesRegex(ValueError, 'spacing must be positive'):
            evaluate_geometry('contour', {}, {'B': box, 'D': 0})

    def test_section_plan_keeps_level_paths_and_reuses_sources(self):
        box = SolidValue('box', 'box', PlaneValue(), (10, 10, 10))
        levels = DataTree((Branch((2,), (PlaneValue((0, 0, 2)), PlaneValue((0, 0, 4)))),
                           Branch((7,), ())))
        plan = evaluate_geometry('section', {}, {'B': box, 'P': levels})
        self.assertEqual([b.path for b in plan['R'].branches], [(2, 0), (2, 1), (7, 0)])
        self.assertEqual(len(plan['_sampling']['plan']['sources']), 1)
        self.assertEqual(len(plan['_sampling']['plan']['rows']), 2)

    def test_sum_keeps_empty_branches_and_flattens_only_on_request(self):
        data = DataTree((Branch((2,), (1e16, 1, -1e16)), Branch((3,), ()), Branch((8,), (7, 2))))
        result = compute('sum', {}, {'N': data})['S']
        self.assertEqual(tuple((b.path, b.items) for b in result.branches),
                         (((2,), (1.,)), ((3,), (0.,)), ((8,), (9.,))))
        self.assertEqual(compute('sum', {'tree_modes': {'N': 'flatten'}}, {'N': data})['S'].values(), (10.,))


class NativeMeasurementTests(unittest.TestCase):
    setUpClass = classmethod(fixture.NativePointTests.setUpClass.__func__)
    setUp = fixture.NativePointTests.setUp
    tearDown = fixture.NativePointTests.tearDown
    call = fixture.NativePointTests.call
    wait_for = fixture.NativePointTests.wait_for

    def run_job(self, method, request):
        job = self.call(method, request)
        self.wait_for(lambda: self.bridge.geometry.jobs[job['job_id']]['state'] != 'preparing')
        return self.call('geometry.job', job)

    def measure(self, operation, inputs, method='geometry.mass_properties', **options):
        parameters = {**self.parameters, **options}
        pending = evaluate_geometry(operation, parameters, inputs)
        request = pending['_sampling']
        reply = self.run_job(method, request)
        self.assertEqual(reply['state'], 'complete', reply)
        details = {'signature': request['signature'], 'values': reply['measurements']}
        return evaluate_geometry(operation, {**parameters, 'sampling_details': details}, inputs)

    def test_nonuniform_scale_applies_per_item_factors_and_keeps_native_breps(self):
        from noodles.backend.scene_curves import materialize

        frame = PlaneValue((5, 6, 7), (0, 1, 0))
        boxes = [SolidValue(key, 'box', PlaneValue(frame.origin), (2, 3, 4)) for key in ('left', 'right')]
        original = materialize(boxes[0])
        result = compute('scale_non_uniform', {}, {'G': boxes, 'P': frame, 'X': [2, 3], 'Y': -3, 'Z': .5})['G']
        volumes = self.measure('volume', {'G': result})['V'].values()
        for value, expected in zip(volumes, (72., 108.), strict=True):
            self.assertAlmostEqual(value, expected)
        from noodles.backend.native_display import geometry_bounds
        actual = geometry_bounds([materialize(result.values()[0])])
        for corner, expected in zip(actual, ((-1, 6, 7), (5, 12, 9)), strict=True):
            self.assertLess(math.dist(corner, expected), 1e-6)
        self.assertAlmostEqual(self.geo.volume(original), 24.)
        source = circle('round', (0, 0, 0), 2, PlaneValue())
        scaled = compute('scale_non_uniform', {}, {'G': source, 'X': 3., 'Y': 2.})['G']
        lengths = self.measure('curve_length', {'C': scaled}, 'geometry.sample')['L'].values()
        self.assertGreater(lengths[0], 4*math.pi)

    def test_isocurves_respect_holes_uv_view_and_periodic_faces(self):
        plane = PlaneValue()
        outer = rectangle('outer', 12, 10, (0, 0, 0), plane)
        hole = rectangle('hole', 4, 3, (0, 0, 0), plane)
        source = compute('planar_surface', {}, {'C': [outer, hole]})['G'].values()[0]
        results = self.measure('surface_isocurves', {'S': source}, 'geometry.topology')
        self.assertEqual(results['Count'], 4)
        for port, expected in (('U', 4.), ('V', 3.5)):
            lengths = self.measure('curve_length', {'C': results[port]}, 'geometry.sample')['L'].values()
            self.assertEqual(len(lengths), 2)
            for length in lengths:
                self.assertAlmostEqual(length, expected)
        view = self.measure('reparameterize_surface', {'S': source, 'U': DomainValue(10, 20),
                                                        'V': DomainValue(-4, 8)}, 'geometry.surface_domain')['S'].values()[0]
        alternate = self.measure('surface_isocurves', {'S': view, 'u': 15., 'v': 2., 'N': False,
                                                       'D': 1}, 'geometry.topology')
        self.assertEqual(alternate['Count'], 2)
        self.assertEqual(alternate['V'].count, 0)
        self.assertEqual([piece.iso for piece in alternate['U'].values()], [piece.iso for piece in results['U'].values()])
        shell = SolidValue('shell', 'cylinder', plane, (2, 5), False)
        results = self.measure('surface_isocurves', {'S': shell}, 'geometry.topology')
        for port, expected in (('U', 4*math.pi), ('V', 5.)):
            length = self.measure('curve_length', {'C': results[port]}, 'geometry.sample')['L'].values()[0]
            self.assertAlmostEqual(length, expected)
        sphere = SolidValue('sphere', 'sphere', plane, (2,))
        pole = self.measure('surface_isocurves', {'S': sphere, 'v': 1.}, 'geometry.topology')
        self.assertEqual((pole['U'].count, pole['V'].count), (0, 1))
        box = SolidValue('box', 'box', plane, (2, 3, 4))
        pending = evaluate_geometry('surface_isocurves', self.parameters, {'S': box})
        self.assertIn('Face Index', self.run_job('geometry.topology', pending['_sampling'])['error'])
        selected = self.measure('surface_isocurves', {'S': box, 'F': 1}, 'geometry.topology')
        self.assertEqual(selected['Count'], 2)

    def test_surface_modules_publish_and_iso_outputs_feed_pipe(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            outline = editor.add_node('NoodleS.Geometry.RectangleNode')
            surface = editor.add_node('NoodleS.Geometry.PlanarSurfaceNode')
            iso = editor.add_node('NoodleS.Operations.SurfaceIsocurvesNode')
            pipe = editor.add_node('NoodleS.Geometry.PipeNode')
            radius = editor.add_node('NoodleS.Inputs.NumberNode')
            module = editor.add_node('NoodleS.Geometry.BoxNode')
            resized = editor.add_node('NoodleS.Operations.ScaleNonUniformNode')
            module.set_property('parameters', {'X': 2., 'Y': 3., 'Z': 4.})
            radius.set_property('value', .5)
            resized.set_property('parameters', {'X': 2., 'Y': .5})
            for source, out, target, port in (
                (outline, 'C', surface, 'C'), (surface, 'G', iso, 'S'), (iso, 'U', pipe, 'C'),
                (radius, 'Number', pipe, 'R'), (module, 'G', resized, 'G'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])

            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))

            self.wait_for(lambda: all(owner(node) is not None for node in (iso, pipe, module, resized)), timeout=10)
            self.assertEqual(len(self.geo.edges_of(owner(iso).shape)), 2)
            iso_result = editor.evaluation.results[iso.id]
            self.assertEqual(len(iso_result.bindings['V']), 1)
            self.assertEqual(self.geo.shape_kind(owner(pipe).shape), 'solid')
            original, before = owner(module), owner(resized)
            resized.set_property('parameters', {'X': 3., 'Y': .5})
            self.wait_for(lambda: owner(resized).shape is not before.shape, timeout=10)
            self.assertEqual(owner(resized).id, before.id)
            self.assertIs(owner(module).shape, original.shape)
            self.assertAlmostEqual(self.geo.volume(owner(resized).shape), 36.)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_divide_by_length_open_and_closed_and_shatter_wire(self):
        rail = polyline('rail', [(0, 0, 0), (4, 0, 0), (4, 6, 0)])
        samples = self.measure('divide_by_length', {'C': rail, 'L': 3, 'R': False}, 'geometry.sample')
        self.assertEqual([p.xyz for p in samples['P'].values()], [(0, 0, 0), (3, 0, 0), (4, 2, 0), (4, 5, 0)])
        with_remainder = self.measure('divide_by_length', {'C': rail, 'L': 3}, 'geometry.sample')
        self.assertEqual(with_remainder['P'].values()[-1].xyz, (4, 6, 0))
        loop = circle('loop', (0, 0, 0), 2, PlaneValue())
        closed = self.measure('divide_by_length', {'C': loop, 'L': math.pi}, 'geometry.sample')
        self.assertEqual(closed['Count'], 4)
        pieces = self.measure('shatter', {'C': rail, 't': [.8, .2, .2, 0., 1.]}, 'geometry.topology')
        self.assertEqual([(d.start, d.end) for d in pieces['D'].values()], [(0, 2), (2, 8), (8, 10)])
        lengths = self.measure('curve_length', {'C': pieces['C']}, 'geometry.sample')['L'].values()
        self.assertEqual(lengths, (2., 6., 2.))

    def test_flip_and_move_seam_preserve_exact_curve_geometry(self):
        rail = polyline('rail', [(0, 0, 0), (4, 0, 0), (4, 6, 0)])
        reverse = self.measure('flip_curve', {'C': rail}, 'geometry.topology')
        self.assertEqual(reverse['F'].values(), (True,))
        first = self.measure('evaluate_curve', {'C': reverse['C']}, 'geometry.sample')['P'].values()[0]
        self.assertEqual(first.xyz, (4, 6, 0))
        aligned = self.measure('flip_curve', {'C': reverse['C'], 'G': rail}, 'geometry.topology')
        first = self.measure('evaluate_curve', {'C': aligned['C']}, 'geometry.sample')['P'].values()[0]
        self.assertEqual(first.xyz, (0, 0, 0))
        loop = circle('loop', (0, 0, 0), 2, PlaneValue())
        square = rectangle('square', 4, 4, (0, 0, 0), PlaneValue())
        periodic = spline('periodic', 'interpcurve',
                          [(3, 0, 0), (0, 2, 0), (-2, 0, 0), (0, -3, 0)],
                          degree=3, closed=True, periodic=True)
        spline_length = self.measure('curve_length', {'C': periodic}, 'geometry.sample')['L'].values()[0]
        for curve, expected in ((loop, 4*math.pi), (square, 16), (periodic, spline_length)):
            with self.subTest(curve=curve.kind):
                shifted = self.measure('move_seam', {'C': curve, 't': .125}, 'geometry.topology')
                samples = self.measure('evaluate_curve', {'C': shifted['C'], 't': [0., 1.]}, 'geometry.sample')
                self.assertTrue(all(math.dist(p.xyz, shifted['P'].values()[0].xyz) < 1e-7 for p in samples['P'].values()))
                length = self.measure('curve_length', {'C': shifted['C']}, 'geometry.sample')['L'].values()[0]
                self.assertAlmostEqual(length, expected)
        pending = evaluate_geometry('move_seam', self.parameters, {'C': rail})
        self.assertIn('closed curve', self.run_job('geometry.topology', pending['_sampling'])['error'])

    def test_normalized_closed_profiles_feed_loft_in_qt(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            lower = editor.add_node('NoodleS.Geometry.CircleNode')
            upper = editor.add_node('NoodleS.Geometry.CircleNode')
            reversed_upper = editor.add_node('NoodleS.Operations.FlipCurveNode')
            aligned = editor.add_node('NoodleS.Operations.FlipCurveNode')
            lower_seam = editor.add_node('NoodleS.Operations.MoveSeamNode')
            upper_seam = editor.add_node('NoodleS.Operations.MoveSeamNode')
            profiles = editor.add_node('NoodleS.Data.MergeNode')
            loft = editor.add_node('NoodleS.Geometry.LoftNode')
            lower.set_property('parameters', {'R': 2.})
            upper.set_property('parameters', {'R': 2., 'C': [0., 0., 5.]})
            lower_seam.set_property('parameters', {'t': .25})
            upper_seam.set_property('parameters', {'t': .25})
            loft.set_property('parameters', {'A': False, 'T': 1})
            for source, out, target, port in (
                (upper, 'C', reversed_upper, 'C'), (reversed_upper, 'C', aligned, 'C'), (lower, 'C', aligned, 'G'),
                (lower, 'C', lower_seam, 'C'), (aligned, 'C', upper_seam, 'C'),
                (lower_seam, 'C', profiles, 'A'), (upper_seam, 'C', profiles, 'B'), (profiles, 'D', loft, 'C'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])
            identity = editor.project_uuid, loft.curve_state()['node_uuid'], 0
            self.wait_for(lambda: self.bridge.points.owner(identity) is not None, timeout=10)
            result = editor.evaluation.results
            self.assertEqual(result[aligned.id].outputs['F'].values(), (True,))
            a, b = (result[node.id].outputs['P'].values()[0].xyz for node in (lower_seam, upper_seam))
            self.assertLess(math.dist(a, (0, 2, 0)), 1e-7)
            self.assertLess(math.dist(b, (0, 2, 5)), 1e-7)
            self.assertAlmostEqual(self.geo.surface_area(self.bridge.points.owner(identity).shape), 20*math.pi, places=4)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_curve_curve_points_parameters_overlaps_and_empty_branches(self):
        a = line('a', (0, 0, 0), (10, 0, 0))
        cross = line('cross', (4, -3, 0), (4, 2, 0))
        overlap = line('overlap', (6, 0, 0), (12, 0, 0))
        missed = line('miss', (4, -3, 1), (4, 2, 1))
        tangent = circle('tangent', (4, 2, 0), 2, PlaneValue())
        curves = DataTree(tuple(Branch((i,), (curve,)) for i, curve in enumerate((cross, overlap, missed, tangent))))
        outputs = self.measure('curve_curve', {'A': a, 'B': curves}, 'geometry.topology')
        self.assertEqual([b.path for b in outputs['P'].branches], [(0,), (1,), (2,), (3,)])
        self.assertEqual([len(b.items) for b in outputs['P'].branches], [1, 2, 0, 1])
        self.assertEqual(outputs['P'].branches[0].items[0].xyz, (4., 0., 0.))
        self.assertAlmostEqual(outputs['tA'].branches[0].items[0], 4.)
        self.assertAlmostEqual(outputs['tB'].branches[0].items[0], 3.)
        self.assertLess(math.dist(outputs['P'].branches[3].items[0].xyz, (4., 0., 0.)), 1e-7)
        self.assertEqual([len(b.items) for b in outputs['C'].branches], [0, 1, 0, 0])
        length = self.measure('curve_length', {'C': outputs['C'].values()[0]}, 'geometry.sample')
        self.assertAlmostEqual(length['L'].values()[0], 4.)

    def test_contour_regions_support_atrium_and_zone_intersection(self):
        box = SolidValue('building', 'box', PlaneValue(), (12, 10, 10))
        levels = self.measure('contour', {'B': box, 'P': PlaneValue((0, 0, 2)), 'D': 3, 'N': 4},
                              'geometry.topology')
        self.assertEqual([len(b.items) for b in levels['R'].branches], [1, 1, 1, 0])
        first = levels['R'].values()[0]
        plane = PlaneValue((0, 0, 2))
        atrium = rectangle('atrium', 4, 3, (5, 3.5, 2), plane)
        left = rectangle('left', 6, 10, (3, 5, 2), plane)
        right = rectangle('right', 6, 10, (9, 5, 2), plane)
        difference = self.measure('region_boolean', {'A': first, 'B': atrium}, 'geometry.topology',
                                  parameters={'region_mode': 'Difference'})
        self.assertEqual(difference['C'].count, 2)
        region = difference['R'].values()[0]
        self.assertAlmostEqual(self.measure('area', {'G': region})['A'].values()[0], 108.)
        halves = DataTree((Branch((2,), (left,)), Branch((3,), (right,))))
        zones = self.measure('region_boolean', {'A': region, 'B': halves}, 'geometry.topology',
                             parameters={'region_mode': 'Intersection'})
        areas = self.measure('area', {'G': zones['R']})['A']
        self.assertEqual([b.path for b in areas.branches], [(2,), (3,)])
        for area, expected in zip(areas.values(), (51., 57.), strict=True):
            self.assertAlmostEqual(area, expected)
        joined = self.measure('region_boolean', {'A': [left, right]}, 'geometry.topology')
        self.assertEqual(joined['R'].count, 1)
        self.assertEqual(joined['C'].count, 1)
        self.assertAlmostEqual(self.measure('area', {'G': joined['R']})['A'].values()[0], 120.)
        empty = self.measure('region_boolean', {'A': left, 'B': right}, 'geometry.topology',
                             parameters={'region_mode': 'Intersection'})
        self.assertEqual([b.items for b in empty['R'].branches], [()])
        raised = rectangle('raised', 6, 10, (9, 5, 3), PlaneValue((0, 0, 3)))
        pending = evaluate_geometry('region_boolean', self.parameters, {'A': left, 'B': raised})
        self.assertIn('same plane', self.run_job('geometry.topology', pending['_sampling'])['error'])

    def test_contour_and_region_boolean_publish_one_owner_each(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            building = editor.add_node('NoodleS.Geometry.BoxNode')
            base_point = editor.add_node('NoodleS.Geometry.PointNode')
            base_plane = editor.add_node('NoodleS.Math.XYPlaneNode')
            contour = editor.add_node('NoodleS.Operations.ContourNode')
            atrium = editor.add_node('NoodleS.Geometry.RectangleNode')
            region = editor.add_node('NoodleS.Operations.RegionBooleanNode')
            area = editor.add_node('NoodleS.Operations.AreaNode')
            line_a = editor.add_node('NoodleS.Geometry.LineNode')
            line_b = editor.add_node('NoodleS.Geometry.LineNode')
            intersection = editor.add_node('NoodleS.Operations.CurveCurveNode')
            building.set_property('parameters', {'X': 12., 'Y': 10., 'Z': 10.})
            base_point.set_property('z', 2.)
            contour.set_property('parameters', {'D': 3., 'N': 1})
            atrium.set_property('parameters', {'X': 4., 'Y': 3., 'C': [5., 3.5, 2.]})
            region.set_property('parameters', {'region_mode': 'Difference'})
            line_b.set_property('parameters', {'A': [6., 0., 0.], 'B': [12., 0., 0.]})
            for source, out, target, port in (
                (base_point, 'P', base_plane, 'O'), (base_plane, 'P', contour, 'P'),
                (building, 'G', contour, 'B'), (contour, 'R', region, 'A'),
                (atrium, 'C', region, 'B'), (region, 'R', area, 'G'),
                (line_a, 'C', intersection, 'A'), (line_b, 'C', intersection, 'B'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])

            def owner(node):
                return self.bridge.points.owner((editor.project_uuid, node.curve_state()['node_uuid'], 0))

            # A single planar cutter applies only at its own elevation.
            self.wait_for(lambda: owner(contour) is not None and owner(region) is not None, timeout=10)
            self.wait_for(lambda: owner(intersection) is not None, timeout=10)
            self.assertEqual(len(self.geo.joined_pieces(owner(intersection).shape)), 3)

            def measured(expected):
                result = editor.evaluation.results.get(area.id)
                return result and not result.error and not result.outputs.get('_sampling') and (
                    result.outputs['A'].values() == (expected,))

            self.wait_for(lambda: measured(108.), timeout=10)
            before = owner(region)
            atrium.set_property('parameters', {'X': 2., 'Y': 3., 'C': [5., 3.5, 2.]})
            self.wait_for(lambda: measured(114.) and owner(region) and owner(region).shape is not before.shape, timeout=10)
            self.assertEqual(owner(region).id, before.id)
            contour.outputs()['R'].disconnect_from(region.inputs()['A'])
            before = owner(contour)
            contour.set_property('parameters', {'D': 3., 'N': 3})
            self.wait_for(lambda: owner(contour).shape is not before.shape, timeout=10)
            self.assertEqual(owner(contour).id, before.id)
            self.assertEqual(editor.evaluation.results[contour.id].outputs['R'].count, 3)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()

    def test_area_of_planar_curve_and_empty_section_of_open_shell(self):
        outline = circle('outline', (3, 4, 5), 2, PlaneValue())
        areas = self.measure('area', {'G': outline})
        self.assertAlmostEqual(areas['A'].values()[0], 4*math.pi)
        self.assertLess(math.dist(areas['C'].values()[0].xyz, (3, 4, 5)), 1e-8)
        open_curve = line('open', (0, 0, 0), (2, 0, 0))
        pending = evaluate_geometry('area', self.parameters, {'G': open_curve})
        self.assertIn('closed planar', self.run_job('geometry.mass_properties', pending['_sampling'])['error'])
        shell = SolidValue('shell', 'cylinder', PlaneValue(), (2, 4), False)
        with self.assertRaisesRegex(ValueError, 'closed solid'):
            evaluate_geometry('volume', self.parameters, {'G': shell})
        result = self.measure('section', {'B': shell, 'P': [PlaneValue((0, 0, 2)),
                                                           PlaneValue((0, 0, 8))]}, 'geometry.topology')
        self.assertEqual(tuple(len(b.items) for b in result['C'].branches), (1, 0))
        self.assertEqual(tuple(len(b.items) for b in result['R'].branches), (0, 0))

    def test_atrium_sections_area_and_volume_update_without_losing_levels(self):
        from noodles.window import MainWindow

        editor = MainWindow()
        editor.serpentine.stop()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            building = editor.add_node('NoodleS.Geometry.BoxNode')
            atrium = editor.add_node('NoodleS.Geometry.BoxNode')
            shell = editor.add_node('NoodleS.Geometry.BooleanDifferenceParametricNode')
            levels = editor.add_node('NoodleS.Math.SeriesNode')
            points = editor.add_node('NoodleS.Geometry.PointNode')
            planes = editor.add_node('NoodleS.Math.XYPlaneNode')
            sections = editor.add_node('NoodleS.Operations.SectionNode')
            area = editor.add_node('NoodleS.Operations.AreaNode')
            total = editor.add_node('NoodleS.Math.SumNode')
            volume = editor.add_node('NoodleS.Operations.VolumeNode')
            building.set_property('parameters', {'X': 12., 'Y': 10., 'Z': 10.})
            atrium.set_property('parameters', {'X': 4., 'Y': 3., 'Z': 14., 'O': (3., 2., -2.)})
            levels.set_property('start', 2.)
            levels.set_property('step', 3.)
            levels.set_property('count', 3)
            for source, out, target, port in (
                (building, 'G', shell, 'A'), (atrium, 'G', shell, 'B'), (shell, 'G', sections, 'B'),
                (levels, 'S', points, 'Z'), (points, 'P', planes, 'O'), (planes, 'P', sections, 'P'),
                (sections, 'R', area, 'G'), (area, 'A', total, 'N'), (shell, 'G', volume, 'G'),
            ):
                source.outputs()[out].connect_to(target.inputs()[port])

            def output(node, port):
                result = editor.evaluation.results.get(node.id)
                return result.outputs.get(port) if result and not result.error else None

            def sums_are(number):
                values = output(total, 'S')
                return values is not None and len(values.values()) == 3 and all(
                    math.isclose(v, number) for v in values.values())

            self.wait_for(lambda: sums_are(108), timeout=12)
            self.assertEqual(tuple(b.path for b in output(total, 'S').branches), ((0, 0), (0, 1), (0, 2)))
            self.assertEqual(tuple(len(b.items) for b in output(sections, 'C').branches), (2, 2, 2))
            self.assertEqual(tuple(len(b.items) for b in output(sections, 'R').branches), (1, 1, 1))
            for centroid, z in zip(output(area, 'C').values(), (2, 5, 8), strict=True):
                self.assertLess(math.dist(centroid.xyz, (660/108, 558/108, z)), 1e-7)
            self.wait_for(lambda: output(volume, 'V') and not editor.evaluation.results[volume.id].outputs.get('_sampling'))
            self.assertAlmostEqual(output(volume, 'V').values()[0], 1080.)
            self.assertLess(math.dist(output(volume, 'C').values()[0].xyz, (660/108, 558/108, 5)), 1e-7)
            identity = editor.project_uuid, sections.curve_state()['node_uuid'], 0
            owner = lambda: self.bridge.points.owner(identity)
            self.wait_for(lambda: owner() is not None)
            before = owner()

            levels.set_property('start', 3.)
            self.wait_for(lambda: output(area, 'C') and
                          all(hasattr(p, 'xyz') for p in output(area, 'C').values()) and
                          math.isclose(output(area, 'C').values()[0].xyz[2], 3))
            building.set_property('parameters', {'X': 14., 'Y': 10., 'Z': 10.})
            self.wait_for(lambda: sums_are(128), timeout=12)
            self.wait_for(lambda: output(volume, 'V') and not editor.evaluation.results[volume.id].outputs.get('_sampling')
                          and math.isclose(output(volume, 'V').values()[0], 1280))
            self.wait_for(lambda: owner() and owner().shape is not before.shape)
            self.assertEqual(owner().id, before.id)
            self.assertEqual(tuple(b.path for b in output(total, 'S').branches), ((0, 0), (0, 1), (0, 2)))
            self.assertNotIn(area.id, editor.point_service.models)
            self.assertNotIn(volume.id, editor.point_service.models)
        finally:
            editor.graph.undo_stack().setClean()
            editor.close()
