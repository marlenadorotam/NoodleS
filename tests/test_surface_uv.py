"""Native UV bounds, face selection, and Domain² graph integration."""
import math
import unittest

import test_surface_references as reference_fixture
from noodles.backend.curves import PlaneValue, circle, cross, polyline
from noodles.backend.datatree import Branch, DataTree
from noodles.backend.domain import DomainValue
from noodles.backend.operations import evaluate_operation
from noodles.backend.point import PointValue
from noodles.backend.scene_curves import materialize
from noodles.backend.surface_uv import Domain2Value, SurfaceUvView, evaluate_surface_uv


class SurfaceUvDataTests(unittest.TestCase):
    def test_divide_domain2_keeps_paths_and_pairs_intervals_in_order(self):
        domain = Domain2Value(DomainValue(-3, 3), DomainValue(0, 4))
        tree = DataTree((Branch((2,), (domain,)), Branch((9,), ())))
        out = evaluate_surface_uv('divide_domain2', {}, {'I': tree, 'U': 3, 'V': 2})
        segments = out['S']
        self.assertEqual(tuple(b.path for b in segments.branches), ((2,), (9,)))
        result = evaluate_surface_uv('deconstruct_domain2', {}, {'I': segments})
        self.assertEqual(result['U'].values(), (DomainValue(-3, -1), DomainValue(-1, 1), DomainValue(1, 3)) * 2)
        self.assertEqual(result['V'].values(), (DomainValue(0, 2),) * 3 + (DomainValue(2, 4),) * 3)
        self.assertEqual(result['U'].branches[0].keys, result['V'].branches[0].keys)
        with self.assertRaisesRegex(ValueError, '10,000-segment'):
            evaluate_surface_uv('divide_domain2', {}, {'I': tree, 'U': 101, 'V': 100})

    def test_deconstruct_domain2_preserves_paths_and_requires_no_bridge(self):
        a = Domain2Value(DomainValue(-3, 2), DomainValue(5, 7))
        b = Domain2Value(DomainValue(1, 9), DomainValue(-4, -1))
        tree = DataTree((Branch((2,), (a, b)), Branch((9,), ())))
        outputs = evaluate_surface_uv('deconstruct_domain2', {}, {'I': tree})
        self.assertEqual(set(outputs), {'U', 'V'})
        self.assertEqual([branch.path for branch in outputs['U'].branches], [(2,), (9,)])
        self.assertEqual(outputs['U'].values(), (a.u, b.u))
        self.assertEqual(outputs['V'].values(), (a.v, b.v))
        grafted = evaluate_surface_uv('deconstruct_domain2', {'tree_modes': {'I': 'graft'}}, {'I': tree})
        self.assertEqual([branch.path for branch in grafted['U'].branches], [(2, 0), (2, 1), (9, 0)])
        with self.assertRaisesRegex(ValueError, 'integer'):
            evaluate_surface_uv('deconstruct_domain2', {}, {'I': a, 'F': .5})

    def test_surface_samples_pair_flat_lists_and_broadcast_over_grafted_rows(self):
        shape = evaluate_operation('planar_surface', {}, {'C': circle('c', (0, 0, 0), 5, PlaneValue())})['G']
        inputs = {'S': shape, 'U': [0, .5, 1], 'V': [.2, .4, .8]}
        paired = evaluate_surface_uv('surface_evaluate', {}, inputs)
        rows = paired['_sampling']['plan']['rows']
        self.assertEqual([(r['u'], r['v']) for r in rows], [(0, .2), (.5, .4), (1, .8)])
        grafted = evaluate_surface_uv('surface_evaluate', {'tree_modes': {'V': 'graft'}}, inputs)
        self.assertEqual([b.path for b in grafted['P'].branches], [(0, 0), (0, 1), (0, 2)])
        self.assertEqual([len(b.items) for b in grafted['P'].branches], [3, 3, 3])
        self.assertEqual(len(grafted['_sampling']['plan']['sources']), 1)
        with self.assertRaisesRegex(ValueError, 'increasing'):
            evaluate_surface_uv('reparameterize_surface', {}, {'S': shape, 'U': DomainValue(2, 1)})


class NativeSurfaceUvTests(unittest.TestCase):
    fixture = reference_fixture.NativeSurfaceReferenceTests
    setUpClass = classmethod(fixture.setUpClass.__func__)
    setUp = fixture.setUp
    tearDown = fixture.tearDown
    call = fixture.call
    wait_for = fixture.wait_for
    complete = fixture.complete
    capture = fixture.capture

    def measure(self, operation, inputs):
        pending = evaluate_surface_uv(operation, self.parameters, inputs)
        request = pending['_sampling']
        method = 'geometry.surface_closest' if operation == 'surface_closest_point' else 'geometry.surface_domain'
        reply = self.complete(method, request)
        self.assertEqual(reply['state'], 'complete', reply)
        state = {**self.parameters, 'sampling_details': {'signature': request['signature'],
                                                         'values': reply['measurements']}}
        return evaluate_surface_uv(operation, state, inputs)

    def test_closest_on_trimmed_face_returns_uv_for_interior_edge_and_vertex(self):
        outer = polyline('outer', ((-5,-5,0), (5,-5,0), (5,5,0), (-5,5,0)), True)
        hole = polyline('hole', ((-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)), True)
        surface = evaluate_operation('planar_surface', self.parameters, {'C': [outer, hole]})['G']
        points = DataTree((Branch((2,), (PointValue('interior', (3,2,2)), PointValue('hole', (.7,0,2)))),
                           Branch((5,), (PointValue('corner', (6,7,2)),)), Branch((8,), ())))
        view = self.measure('reparameterize_surface', {'S': surface, 'U': DomainValue(10, 20),
                                                      'V': DomainValue(-4, 6)})['S']
        for source, normalized in ((surface, False), (surface, True), (view, False)):
            inputs = {'S': source, 'N': normalized}
            closest = self.measure('surface_closest_point', {**inputs, 'P': points})
            evaluated = self.measure('surface_evaluate', {**inputs, 'U': closest['U'], 'V': closest['V']})
            expected = ((3,2,0), (1,0,0), (5,5,0))
            self.assertEqual([branch.path for branch in closest['P'].branches], [(2,), (5,), (8,)])
            self.assertEqual(evaluated['Count'], 3)
            for result, repeated, target in zip(closest['P'].values(), evaluated['P'].values(), expected, strict=True):
                self.assertLess(math.dist(result.xyz, target), 1e-8)
                self.assertLess(math.dist(result.xyz, repeated.xyz), 1e-8)
            for actual, expected in zip(closest['D'].values(), (2., math.hypot(.3, 2), 3.), strict=True):
                self.assertAlmostEqual(actual, expected)
        self.assertFalse(self.window.scene.objects)

    def test_closest_on_torus_feeds_surface_evaluate_at_both_seams(self):
        from noodles.backend.solids import evaluate_solid

        surface = evaluate_solid('torus', self.parameters, {'R': 10, 'r': 2})['G']
        points = [PointValue('outer-seam', (13,0,0)), PointValue('inner', (0,7,0)),
                  PointValue('top', (0,10,3)), PointValue('bottom-seam', (10,0,-3))]
        result = self.measure('surface_closest_point', {'S': surface, 'P': points})
        evaluated = self.measure('surface_evaluate', {'S': surface, 'U': result['U'], 'V': result['V']})
        self.assertEqual(evaluated['Count'], 4)
        for distance, closest, sampled, expected in zip(result['D'].values(), result['P'].values(),
                evaluated['P'].values(), ((12,0,0), (0,8,0), (0,10,2), (10,0,-2)), strict=True):
            self.assertAlmostEqual(distance, 1.)
            self.assertLess(math.dist(closest.xyz, expected), 1e-7)
            self.assertLess(math.dist(sampled.xyz, expected), 1e-7)

    def test_trimmed_planar_generated_reference_and_direct_deconstruct_agree(self):
        from OCP.BRepTools import BRepTools

        circles = [circle(str(radius), (4, 8, 0), radius, PlaneValue()) for radius in (8, 3)]
        generated = evaluate_operation('planar_surface', self.parameters, {'C': circles})['G']
        shape = materialize(generated.values()[0])
        obj = self.window.scene.add(shape, name='Planar surface with hole')
        state = self.capture('planar_surface', [obj])
        referenced = evaluate_operation('planar_surface', state, {})['G']
        generate = self.measure('surface_domain', {'S': generated})
        reference = self.measure('surface_domain', {'S': referenced})
        self.assertEqual(generate['D'].values(), reference['D'].values())
        direct = self.measure('deconstruct_domain2', {'I': referenced})
        split = evaluate_surface_uv('deconstruct_domain2', {}, {'I': reference['D']})
        for port in ('U', 'V'):
            self.assertEqual(direct[port].values(), split[port].values())
            self.assertEqual(split[port].values(), reference[port].values())
        u0, u1, v0, v1 = BRepTools.UVBounds_s(self.geo.faces_of(shape)[0])
        self.assertEqual(reference['D'].values(), (Domain2Value(DomainValue(u0, u1), DomainValue(v0, v1)),))
        self.assertAlmostEqual(u1 - u0, 16, places=5)
        self.assertAlmostEqual(v1 - v0, 16, places=5)
        self.assertIs(self.window.scene.get(obj.id)._shape, shape)

    def test_loft_face_selection_and_range_in_editor(self):
        from OCP.BRepTools import BRepTools
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from noodles.window import MainWindow

        sections = [polyline(str(z), ((0, 0, z), (9, 0, z), (2, 4, z)), True) for z in (0, 7)]
        loft = evaluate_operation('loft', self.parameters, {'C': sections})['G']
        shape = materialize(loft.values()[0])
        faces = self.geo.faces_of(shape)
        self.assertGreater(len(faces), 1)
        pending = evaluate_surface_uv('surface_domain', self.parameters, {'S': loft})
        reply = self.complete('geometry.surface_domain', pending['_sampling'])
        self.assertIn('Set Face Index', reply['error'])
        two_faces = self.measure('surface_domain', {'S': loft, 'F': [1, 2]})
        expected = [BRepTools.UVBounds_s(face) for face in faces[:2]]
        self.assertEqual(two_faces['D'].values(),
                         tuple(Domain2Value(DomainValue(a, b), DomainValue(c, d)) for a, b, c, d in expected))

        obj = self.window.scene.add(shape, name='Multiface loft')
        editor = MainWindow()
        editor.point_service.client = self.client
        editor.point_service.start()
        editor.show()
        try:
            source = editor.add_node('NoodleS.Geometry.LoftNode')
            source.set_property('mode', 'reference')
            self.window.selection.set([obj.id])
            self.wait_for(lambda: editor.properties.node_id == source.id)
            editor._capture_points()
            self.wait_for(lambda: not source.reference_error)
            domain = editor.add_node('NoodleS.Operations.SurfaceDomainNode')
            split = editor.add_node('NoodleS.Operations.DeconstructDomain2Node')
            span = editor.add_node('NoodleS.Math.RangeNode')
            source.outputs()['G'].connect_to(domain.inputs()['S'])
            domain.outputs()['D'].connect_to(split.inputs()['I'])
            split.outputs()['U'].connect_to(span.inputs()['D'])

            def result(node):
                return editor.evaluation.results.get(node.id)

            self.wait_for(lambda: result(domain) and result(domain).error and 'Set Face Index' in result(domain).error)
            editor.graph.clear_selection()
            domain.set_selected(True)
            self.wait_for(lambda: editor.properties.node_id == domain.id)
            field = editor.properties.curve_properties.editors['F'][0]
            field.setFocus()
            QTest.keyClick(field, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(field, '2')
            QTest.keyClick(field, Qt.Key_Return)
            self.wait_for(lambda: result(span) and not result(span).error and 'R' in result(span).outputs)
            values = result(span).outputs['R'].values()
            self.assertEqual((values[0], values[-1]), expected[1][:2])
            reparam = editor.add_node('NoodleS.Operations.ReparameterizeSurfaceNode')
            sample = editor.add_node('NoodleS.Operations.SurfaceEvaluateNode')
            reparam.set_property('parameters', {'F': 2})
            source.outputs()['G'].connect_to(reparam.inputs()['S'])
            reparam.outputs()['S'].connect_to(domain.inputs()['S'])
            reparam.outputs()['S'].connect_to(sample.inputs()['S'])
            span.outputs()['R'].connect_to(sample.inputs()['U'])
            self.wait_for(lambda: result(sample) and result(sample).outputs.get('Count') == 11)
            sampled = result(sample).outputs
            self.assertEqual(sampled['u'].values()[::10], (0., 1.))
            self.assertEqual(sampled['v'].values(), (.5,) * 11)
            self.assertNotIn(domain.id, editor.point_service.models)
            self.assertNotIn(split.id, editor.point_service.models)
            self.assertEqual(set(self.window.scene.objects), {obj.id})
        finally:
            editor.point_service.stop()
            editor.graph.undo_stack().setClean()
            editor.close()
            editor.deleteLater()
            self.app.processEvents()

    def test_reparameterized_domains_and_derivatives_with_trimmed_hole(self):
        curves = [circle(str(radius), (0, 0, 0), radius, PlaneValue()) for radius in (6, 2)]
        surface = evaluate_operation('planar_surface', self.parameters, {'C': curves})['G']
        domains = self.measure('surface_domain', {'S': surface})['D'].values()[0]
        view = self.measure('reparameterize_surface', {'S': surface})['S']
        mapped = view.values()[0]
        self.assertIsInstance(mapped, SurfaceUvView)
        self.assertEqual(mapped.source, surface.values()[0])
        self.assertEqual(evaluate_surface_uv('surface_domain', {}, {'S': view})['D'].values(),
                         (Domain2Value(DomainValue(0, 1), DomainValue(0, 1)),))
        partial = self.measure('reparameterize_surface', {'S': surface, 'U': DomainValue(10, 20)})['S'].values()[0]
        self.assertEqual(partial.domain.v, domains.v)
        chained = evaluate_surface_uv('reparameterize_surface', {}, {'S': partial, 'V': DomainValue(-3, 3)})['S'].values()[0]
        self.assertEqual(chained.source, mapped.source)
        self.assertEqual(chained.domain, Domain2Value(DomainValue(10, 20), DomainValue(-3, 3)))

        normalized = self.measure('surface_evaluate', {'S': surface, 'U': [.5, 2/3, 5/6, 1],
                                                       'V': [.5, .5, .5, 1], 'N': True})
        native = self.measure('surface_evaluate', {'S': surface,
            'U': [domains.u.start + domains.u.length * t for t in (2/3, 5/6)],
            'V': domains.v.start + domains.v.length / 2})
        mapped_samples = self.measure('surface_evaluate', {'S': view, 'U': [.5, 2/3, 5/6, 1],
                                                           'V': [.5, .5, .5, 1]})
        self.assertEqual(normalized['Count'], 2)
        self.assertEqual(normalized['Skipped'], 2)
        self.assertEqual(normalized['u'].values(), (2/3, 5/6))
        self.assertEqual([p.xyz for p in mapped_samples['P'].values()], [p.xyz for p in normalized['P'].values()])
        self.assertEqual([p.xyz for p in native['P'].values()], [p.xyz for p in normalized['P'].values()])
        self.assertAlmostEqual(math.hypot(*mapped_samples['U'].values()[0].xyz),
                               domains.u.length * math.hypot(*normalized['U'].values()[0].xyz))
        self.assertFalse(self.window.scene.objects)

    def test_periodic_seam_reversed_face_and_singular_samples(self):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
        from OCP.GeomAbs import GeomAbs_Cylinder

        scene = self.window.scene
        side = next(f for f in self.geo.faces_of(BRepPrimAPI_MakeCylinder(3, 5).Shape())
                    if BRepAdaptor_Surface(f).GetType() == GeomAbs_Cylinder)
        inward = self.geo.faces_of(side.Reversed())[0]
        obj = scene.add(inward, name='Reversed cylinder')
        reference = self.capture('edge_surface', [obj])
        surface = evaluate_operation('edge_surface', reference, {})['G']
        samples = self.measure('surface_evaluate', {'S': surface, 'U': [0., 1.], 'N': True})
        self.assertEqual(samples['Count'], 2)
        self.assertLess(math.dist(*(p.xyz for p in samples['P'].values())), 1e-10)
        for p, n, frame in zip(samples['P'].values(), samples['N'].values(), samples['F'].values()):
            self.assertLess(math.dist(n.xyz, (-p.xyz[0]/3, -p.xyz[1]/3, 0)), 1e-10)
            self.assertLess(math.dist(cross(frame.axis_x, frame.axis_y), frame.normal), 1e-12)
        sphere = scene.add(self.geo.faces_of(BRepPrimAPI_MakeSphere(2).Shape())[0], name='Sphere surface')
        source = evaluate_operation('edge_surface', self.capture('edge_surface', [sphere]), {})['G']
        poles = self.measure('surface_evaluate', {'S': source, 'V': [0., .5, 1.], 'N': True})
        self.assertEqual(poles['Count'], 1)
        self.assertEqual(poles['Skipped'], 2)
        self.assertEqual(poles['v'].values(), (.5,))
        request = evaluate_surface_uv('surface_evaluate', self.parameters,
                                      {'S': source, 'V': 1.1, 'N': True})['_sampling']
        invalid = self.complete('geometry.surface_domain', request)
        self.assertIn('outside the selected UV domain', invalid['error'])
        self.assertEqual(set(scene.objects), {obj.id, sphere.id})
