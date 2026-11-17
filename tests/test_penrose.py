"""Check the P2 prototiles and the coverage of the subdivided sun."""
from collections import Counter, defaultdict
import math
import unittest

from noodles.backend.penrose import DART, KITE, MAX_GENERATIONS, pattern, sun


def edges(points):
    return zip(points, (*points[1:], points[0]))


class PenroseTests(unittest.TestCase):
    def test_complete_tiles_have_p2_interior_angles(self):
        for tile in sun(3):
            if not tile.complete:
                continue
            vertices = tuple(complex(*point) for point in tile.points)
            turns = [(vertices[i - 1] - point) / (vertices[(i + 1) % 4] - point)
                     for i, point in enumerate(vertices)]
            angles = [round(math.degrees(math.atan2(turn.imag, turn.real)) % 360) for turn in turns]
            expected = [72, 72, 72, 144] if tile.kind == KITE else [36, 36, 72, 216]
            self.assertEqual(sorted(angles), expected)

    def test_subdivision_covers_decagon_with_matching_internal_edges(self):
        normals = [complex(math.cos(angle), math.sin(angle)).conjugate()
                   for angle in ((i + .5) * math.tau / 10 for i in range(10))]
        for generation in range(MAX_GENERATIONS + 1):
            with self.subTest(generation=generation):
                tiles = sun(generation)
                area = sum(x * v - y * u for tile in tiles for (x, y), (u, v) in edges(tile.points)) / 2
                self.assertAlmostEqual(area, 5 * math.sin(math.tau / 10), places=10)
                incidence = Counter(tuple(sorted(edge)) for tile in tiles for edge in edges(tile.points))
                for (a, b), count in incidence.items():
                    self.assertIn(count, (1, 2))
                    if count == 1:
                        midpoint = (complex(*a) + complex(*b)) / 2
                        self.assertAlmostEqual(max((midpoint * n).real for n in normals), math.cos(math.pi / 10))
        full = Counter(tile.kind for tile in sun(MAX_GENERATIONS) if tile.complete)
        self.assertEqual(full, {KITE: 1155, DART: 700})

    def test_matching_arcs_share_endpoints_across_interior_edges(self):
        incidence = defaultdict(list)
        for tile, (_, _, _, arcs) in zip(sun(4), pattern(4)):
            vertices = tuple(complex(*p) for p in tile.points)
            endpoints = [p for arc in arcs for p in (arc[0], arc[-1])]
            for a, b in edges(vertices):
                ratios = ((p - a) / (b - a) for p in endpoints)
                on_edge = [round(t.real, 8) for t in ratios if abs(t.imag) < 1e-8 and 0 < t.real < 1]
                incidence[a, b] = on_edge
        for (a, b), positions in incidence.items():
            if (b, a) in incidence:
                self.assertEqual(len(positions), 1)
                self.assertEqual(len(incidence[b, a]), 1)
                self.assertAlmostEqual(positions[0] + incidence[b, a][0], 1., places=7)

    def test_crop_covers_boundary_and_keeps_real_corners(self):
        outline = (-.6-.4j, .5-.4j, .5+.3j, -.6+.3j)
        parts = tuple(pattern(5, outline))
        rings = [ring for _, _, rings, _ in parts for ring in rings]
        self.assertTrue(set(outline) <= {p for ring in rings for p in ring})
        area = sum((a.conjugate() * b).imag for ring in rings for a, b in edges(ring)) / 2
        self.assertAlmostEqual(area, .77, places=9)
        for _, _, _, arcs in parts:
            for arc in arcs:
                for p in arc:
                    self.assertTrue(-.6 <= p.real <= .5 and -.4 <= p.imag <= .3)
        with self.assertRaisesRegex(ValueError, 'convex'):
            tuple(pattern(4, (0j, .4+0j, .1+.1j, .4+.4j, .4j)))

    def test_grafted_generations_keep_paths_and_share_one_indexed_model(self):
        from noodles.backend.penrose_node import evaluate, normalize_state, object_from_outputs
        from noodles.backend.point import object_from_wire
        from noodles.backend.tessellation_native import measure

        params = normalize_state({'project_uuid': 'af96bbf5-d242-4876-bebb-15d8de7a8991',
                                  'node_uuid': 'e5c1ed25-f186-4668-842d-b554cc39c95f',
                                  'tree_modes': {'N': 'graft'}})
        inputs = {'N': [0, 1]}
        request = evaluate(params, inputs)['_sampling']
        values = measure(request['plan'], lambda: True)
        outputs = evaluate({**params, 'sampling_details': {
            'signature': request['signature'], 'values': values}}, inputs)
        self.assertEqual([(b.path, len(b.items)) for b in outputs['C'].branches],
                         [((0, 0), 5), ((0, 1), 15)])
        self.assertEqual(outputs['A'].count, 40)
        model = object_from_outputs(params, outputs)
        self.assertEqual(model.parts.count, 60)
        self.assertEqual(object_from_wire(model.to_wire()), model)
