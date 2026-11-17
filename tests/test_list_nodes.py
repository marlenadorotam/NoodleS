"""Typed data, source ownership and actual Qt interaction for the first list nodes."""
from pathlib import Path
import tempfile
import unittest

from Qt import QtCore
from PySide6.QtTest import QTest

import test_curves as fixture
from noodles.backend.datatree import Branch, DataTree, tree_diagnostics
from noodles.backend.geometry import normalize_geometry_state
from noodles.backend.moves import TranslatedValue
from noodles.backend.point import PointValue
from noodles.core import Connection, GraphEngine, NodeSpec, compute
from noodles.document import read_document, write_document


class ListDataTests(unittest.TestCase):
    def test_tree_branch_and_replace_paths_use_real_paths_and_preserve_empty_branches(self):
        tree = DataTree((Branch((3, 1), ('panel A',), ('a',)), Branch((3, 2), ()),
                         Branch((5, 1), ('panel B',), ('b',))))
        paths = compute('tree_viewer', {}, {'D': tree})['P']
        self.assertEqual(compute('tree_branch', {}, {'T': tree, 'P': paths})['B'], tree)
        selected = compute('tree_branch', {}, {'T': tree, 'P': ['{5;1}', '{3;2}']})['B']
        self.assertEqual(selected.branches, (tree.branches[2], tree.branches[1]))
        self.assertEqual(compute('tree_branch', {}, {'T': tree, 'P': (5, 1)})['B'].branches, (tree.branches[2],))
        replaced = compute('replace_paths', {}, {'T': tree, 'S': ['{3;1}', '{5;1}'],
                                                   'P': ['{8;0}', '{8;0}']})['T']
        self.assertEqual(replaced.branches, (Branch((8, 0), ('panel A', 'panel B'), ('a', 'b')), tree.branches[1]))
        all_replaced = compute('replace_paths', {}, {'T': tree, 'P': ['{0}', '{1}', '{2}']})['T']
        self.assertEqual([b.path for b in all_replaced.branches], [(0,), (1,), (2,)])
        with self.assertRaisesRegex(ValueError, 'No branch at path'):
            compute('tree_branch', {}, {'T': tree, 'P': '{9}'})
        with self.assertRaisesRegex(ValueError, 'distinct source path'):
            compute('replace_paths', {}, {'T': tree, 'S': ['{3;1}', '{3;1}'], 'P': ['{8}', '{9}']})

    def test_average_and_maximum_reduce_each_branch_and_preserve_empty_paths(self):
        tree = DataTree((Branch((1,), (1e308, 1e308)), Branch((2,), ()), Branch((3,), (-9, -2, -4))))
        average = compute('average', {}, {'N': tree})['A']
        maximum = compute('maximum', {}, {'N': tree})['M']
        self.assertEqual(average.branches, (Branch((1,), (1e308,)), Branch((2,), ()), Branch((3,), (-5.,))))
        self.assertEqual(maximum.values(), (1e308, -2.))
        self.assertEqual(compute('maximum', {'tree_modes': {'N': 'flatten'}}, {'N': tree})['M'].values(), (1e308,))

    def test_read_csv_keeps_ids_quoted_fields_and_polish_text(self):
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / 'types.csv'
            path.write_text('Id;Type;Area\n001;"Ściana; północ";2,5\n002;"Panel ""A""";3\n', encoding='utf-8-sig')
            arguments = {'P': str(path), 'D': 1}
            result = compute('read_csv', {}, arguments)
            self.assertEqual(result['H'].values(), ('Id', 'Type', 'Area'))
            self.assertEqual(result['R'].branches[0], Branch((0, 0), ('001', 'Ściana; północ', '2,5')))
            self.assertEqual(result['R'].branches[1].items, ('002', 'Panel "A"', '3'))
            self.assertEqual(result['N'].values(), (2,))
            result = compute('read_csv', {}, {**arguments, 'N': True})
            self.assertEqual(result['R'].branches[0].items, (1., 'Ściana; północ', 2.5))
            paths = DataTree((Branch((4,), (str(path),)), Branch((5,), (str(path),))))
            grouped = compute('read_csv', {}, {**arguments, 'P': paths})
            self.assertEqual([b.path for b in grouped['R'].branches], [(4, 0), (4, 1), (5, 0), (5, 1)])
            path.write_text('Name;Note\nPanel;"unfinished', encoding='utf-16')
            with self.assertRaisesRegex(ValueError, 'Could not read CSV'):
                compute('read_csv', {}, arguments)

    def test_sort_list_preserves_equal_key_order_and_paired_tree_keys(self):
        keys = DataTree((Branch((2,), (3, 1, 1), ('k3', 'k1', 'k2')), Branch((5,), ())))
        values = DataTree((Branch((2,), ('panel C', 'panel A', 'panel B'), ('c', 'a', 'b')), Branch((5,), ())))
        result = compute('sort_list', {}, {'K': keys, 'A': values})
        self.assertEqual(result['K'].branches, (Branch((2,), (1, 1, 3), ('k1', 'k2', 'k3')), Branch((5,), ())))
        self.assertEqual(result['A'].branches, (Branch((2,), ('panel A', 'panel B', 'panel C'), ('a', 'b', 'c')), Branch((5,), ())))
        self.assertEqual(compute('sort_list', {}, {'K': ['west', 'east']})['K'].values(), ('east', 'west'))
        with self.assertRaisesRegex(ValueError, 'equally many keys and values'):
            compute('sort_list', {}, {'K': [2, 1], 'A': ['panel A']})
        with self.assertRaisesRegex(ValueError, 'all numbers or all text'):
            compute('sort_list', {}, {'K': [2, 'west']})

    def test_sort_points_keeps_ties_keys_branches_and_indices(self):
        a = PointValue('a', (2, 0, 1))
        b = PointValue('b', (1, 2, 0))
        c = PointValue('c', (2, 0, 1))
        d = PointValue('d', (2, 0, 0))
        tree = DataTree((Branch((2, 4), (a, b, c, d), ('a', 'b', 'c', 'd')),
                         Branch((3,), ()), Branch((4,), (a,))))
        result = compute('sort_points', {}, {'P': tree})
        self.assertEqual(result['P'].branches,
                         (Branch((2, 4), (b, d, a, c), ('b', 'd', 'a', 'c')), *tree.branches[1:]))
        self.assertEqual([branch.items for branch in result['I'].branches], [(1, 3, 0, 2), (), (0,)])
        result = compute('sort_points', {'parameters': {'axis_order': 'YXZ'}}, {'P': tree})
        self.assertEqual(result['I'].branches[0].items, (3, 0, 2, 1))
        flattened = compute('sort_points', {'tree_modes': {'P': 'flatten'}}, {'P': tree})
        self.assertEqual(flattened['I'].branches[0].path, (0,))
        self.assertEqual(flattened['I'].values(), (1, 3, 0, 2, 4))

    def test_cull_duplicate_points_preserves_first_items_indices_and_branches(self):
        a, b, c = [PointValue(str(i), (x, 0, 0)) for i, x in enumerate((-.005, .004, 1))]
        points = DataTree((Branch((2,), (a, b, c), ('a', 'b', 'c')), Branch((5,), (b,)), Branch((7,), ())))
        result = compute('cull_duplicate_points', {}, {'P': points, 'T': .01})
        self.assertEqual(result['P'].branches[0], Branch((2,), (a, c), ('a', 'c')))
        self.assertEqual([branch.items for branch in result['I'].branches], [(0, 2), (0,), ()])
        flattened = compute('cull_duplicate_points', {'tree_modes': {'P': 'flatten'}},
                            {'P': points, 'T': 0})
        self.assertEqual(flattened['I'].values(), (0, 1, 2))
        with self.assertRaisesRegex(ValueError, 'nonnegative tolerance'):
            compute('cull_duplicate_points', {}, {'P': points, 'T': -1})

    def test_closest_points_preserves_single_hit_paths_and_groups_multiple_hits(self):
        a, b, c = [PointValue(str(i), (x, 0, 0)) for i, x in enumerate((-1, 1, 3))]
        query = DataTree((Branch((2,), (PointValue('q', (0, 0, 0)), c)), Branch((5,), ())))
        result = compute('closest_points', {}, {'P': query, 'C': [a, b, c]})
        self.assertEqual([branch.path for branch in result['I'].branches], [(2,), (5,)])
        self.assertEqual(result['I'].values(), (0, 2))
        self.assertEqual(result['D'].values(), (1., 0.))
        result = compute('closest_points', {}, {'P': query, 'C': [a, b, c], 'N': 9})
        self.assertEqual([branch.path for branch in result['I'].branches], [(2, 0), (2, 1), (5, 0)])
        self.assertEqual([branch.items for branch in result['I'].branches], [(0, 1, 2), (2, 1, 0), ()])
        self.assertEqual(result['P'].values(), (a, b, c, c, b, a))
        self.assertEqual(compute('closest_points', {}, {'P': query, 'C': [], 'N': 2})['P'].count, 0)

    def test_cross_reference_pairing_modes_with_unequal_lists(self):
        rules = {
            'holistic': lambda i, j: True,
            'diagonal': lambda i, j: i != j,
            'coincident': lambda i, j: i != j,
            'upper': lambda i, j: i <= j,
            'upper_strict': lambda i, j: i < j,
            'lower': lambda i, j: i >= j,
            'lower_strict': lambda i, j: i > j,
        }
        for pairing, accepts in rules.items():
            for height, width in ((2, 4), (4, 2), (3, 3), (1, 1), (0, 2)):
                with self.subTest(pairing=pairing, height=height, width=width):
                    state = {'parameters': {'pairing': pairing}}
                    result = compute('cross_reference', state, {'A': list(range(height)), 'B': list(range(width))})
                    expected = tuple((i, j) for i in range(height) for j in range(width) if accepts(i, j))
                    self.assertEqual(tuple(zip(result['A'].values(), result['B'].values(), strict=True)), expected)

    def test_lower_strict_pairs_different_indices_and_keeps_unequal_lists(self):
        state = {'parameters': {'pairing': 'lower_strict'}}
        result = compute('cross_reference', state, {'A': [0, 1, 2, 3], 'B': [0, 1]})
        self.assertEqual(tuple(zip(result['A'].values(), result['B'].values())),
                         ((1, 0), (2, 0), (2, 1), (3, 0), (3, 1)))
        result = compute('cross_reference', state, {'A': [0], 'B': [0, 1]})
        self.assertEqual(result['A'].branches, (Branch((0,), ()),))
        with self.assertRaisesRegex(ValueError, '10,000'):
            compute('cross_reference', state, {'A': list(range(142)), 'B': list(range(142))})

    def test_cross_reference_pairs_items_within_matching_branches(self):
        a = DataTree((Branch((3,), ('a', 'b')), Branch((5,), ()), Branch((7,), ('c',))))
        b = DataTree((Branch((7,), (3,)), Branch((5,), (4,)), Branch((3,), (1, 2))))
        result = compute('cross_reference', {}, {'A': a, 'B': b})
        self.assertEqual(tuple(branch.path for branch in result['A'].branches), ((3,), (5,), (7,)))
        self.assertEqual(result['A'].branches[1], Branch((5,), ()))
        self.assertEqual(result['B'].branches[1], Branch((5,), ()))
        self.assertEqual(tuple(zip(result['A'].values(), result['B'].values())),
                         (('a', 1), ('a', 2), ('b', 1), ('b', 2), ('c', 3)))
        self.assertEqual(len(set(result['A'].branches[0].keys)), 4)
        self.assertEqual(len(set(result['B'].branches[0].keys)), 4)

        grafted = compute('cross_reference', {'tree_modes': {'A': 'graft'}},
                          {'A': ['a', 'b'], 'B': [1, 2]})
        self.assertEqual([(branch.path, branch.items) for branch in grafted['B'].branches],
                         [((0, 0), (1, 2)), ((0, 1), (1, 2))])
        flattened = compute('cross_reference', {'tree_modes': {'B': 'flatten'}}, {'A': a, 'B': b})
        self.assertEqual([branch.items for branch in flattened['B'].branches],
                         [(3, 4, 1, 2) * 2, (), (3, 4, 1, 2)])
        with self.assertRaisesRegex(ValueError, 'paths'):
            compute('cross_reference', {}, {'A': a, 'B': grafted['B']})
        with self.assertRaisesRegex(ValueError, '10,000'):
            compute('cross_reference', {}, {'A': list(range(100)), 'B': list(range(101))})

    def test_cross_reference_keeps_geometry_owners_separate_per_output(self):
        first = NodeSpec('a', 'line', normalize_geometry_state('line', {}))
        second = NodeSpec('b', 'line', normalize_geometry_state('line', {'parameters': {'B': [20, 0, 0]}}))
        cross = NodeSpec('cross', 'cross_reference', {}, {'A': Connection('a', 'C'), 'B': Connection('b', 'C')})
        result = GraphEngine().evaluate([first, second, cross]).results['cross']
        self.assertFalse(result.error)
        self.assertIsNone(result.parametric_object)
        self.assertEqual(tuple(binding.owner for binding in result.bindings['A'].values()), ('a',))
        self.assertEqual(tuple(binding.owner for binding in result.bindings['B'].values()), ('b',))

    def test_shift_list_preserves_paths_and_moves_keys_with_items(self):
        a = Branch((3, 1), ('a', 'b', 'c'), ('ka', 'kb', 'kc'))
        b = Branch((3, 2), ('d', 'e'), ('kd', 'ke'))
        empty = Branch((4,), ())
        source = DataTree((a, b, empty))
        self.assertEqual(compute('shift_list', {}, {'L': source})['L'].branches,
                         (Branch(a.path, ('b', 'c', 'a'), ('kb', 'kc', 'ka')),
                          Branch(b.path, ('e', 'd'), ('ke', 'kd')), empty))
        for offset, expected in ((-1, ('c', 'a', 'b')), (7, ('b', 'c', 'a')), (0, a.items)):
            with self.subTest(offset=offset):
                self.assertEqual(compute('shift_list', {}, {'L': list(a.items), 'S': offset})['L'].values(), expected)
        for offset, expected in ((1, ('b', 'c')), (-1, ('a', 'b')), (0, a.items), (5, ()), (-5, ())):
            with self.subTest(offset=offset, wrap=False):
                result = compute('shift_list', {}, {'L': DataTree((a,)), 'S': offset, 'W': False})['L']
                self.assertEqual((result.branches[0].path, result.values()), (a.path, expected))
        with self.assertRaisesRegex(ValueError, 'integer'):
            compute('shift_list', {}, {'L': source, 'S': 1.5})

    def test_duplicate_dispatch_and_weave_keep_branch_order(self):
        tree = DataTree((Branch((3,), ('a', 'b')), Branch((5,), ())))
        ordered = compute('duplicate_data', {}, {'D': tree, 'N': 3})['D']
        grouped = compute('duplicate_data', {}, {'D': tree, 'N': 3, 'O': False})['D']
        self.assertEqual(ordered.values(), ('a', 'b') * 3)
        self.assertEqual(grouped.values(), ('a', 'a', 'a', 'b', 'b', 'b'))
        self.assertEqual(len(set(ordered.branches[0].keys)), 6)
        split = compute('dispatch', {}, {'L': ordered, 'P': [True, False, True]})
        woven = compute('weave', {}, {'0': split['A'], '1': split['B'], 'P': [0, 1, 0]})['W']
        self.assertEqual([(b.path, b.items) for b in woven.branches],
                         [(b.path, b.items) for b in ordered.branches])
        self.assertEqual(compute('weave', {}, {'0': [1, 2, 3], '1': [4]})['W'].values(), (1, 4, 2, 3))
        with self.assertRaisesRegex(ValueError, '10,000'):
            compute('duplicate_data', {}, {'D': tree, 'N': 5001})

    def test_tree_viewer_limits_text_but_reports_all_paths_and_items(self):
        tree = DataTree(tuple(Branch((i,), tuple(range(8))) for i in range(25)) + (Branch((99,), ()),))
        result = compute('tree_viewer', {}, {'D': tree})
        self.assertEqual((result['B'], result['N']), (26, 200))
        self.assertEqual(result['P'].values()[-1], (99,))
        self.assertIn('{0}: 0, 1, 2, 3, 4, 5, … 2 more', result['V'])
        self.assertIn('… 2 more branch(es)', result['V'])
        self.assertNotIn('{99}', result['V'])
        self.assertEqual(compute('tree_viewer', {}, {})['N'], 0)
        self.assertIn('(empty)', compute('tree_viewer', {}, {'D': []})['V'])

    def test_tree_diagnostics_exposes_paths_and_counts_including_empty_branches(self):
        tree = DataTree((Branch((3, 7), (1, 2)), Branch((8,), ())))
        output = tree_diagnostics(tree)
        self.assertEqual(output['P'].branches, (Branch((3, 7), ((3, 7),)), Branch((8,), ((8,),))))
        self.assertEqual((output['B'], output['N']), (2, 2))
        self.assertEqual(tree_diagnostics(DataTree(())), {'P': DataTree(()), 'B': 0, 'N': 0})

    def test_merge_preserves_paths_and_port_order_without_broadcast(self):
        left = DataTree((Branch((5,), (1, 2)), Branch((8,), ())))
        right = DataTree((Branch((5,), (3,)), Branch((2,), (4,))))
        result = compute('merge', {}, {'B': right, 'A': left})['D']
        self.assertEqual([(b.path, b.items) for b in result.branches],
                         [((5,), (1, 2, 3)), ((8,), ()), ((2,), (4,))])
        self.assertEqual(len(set(result.branches[0].keys)), 3)
        self.assertEqual(compute('merge', {'tree_modes': {'A': 'flatten'}}, {'A': left, 'B': right})['D'].branches[0].path, (0,))

    def test_list_item_and_length_keep_empty_branches_and_typed_leaves(self):
        from noodles.backend.point import PointValue
        point = PointValue('p', (1, 2, 3))
        source = DataTree((Branch((5,), (point, 2)), Branch((8,), ())))
        result = compute('list_item', {}, {'L': source, 'I': [-2, -1]})['I']
        self.assertIs(result.branches[0].items[0], point)
        self.assertEqual(result.branches[0].items[1], 2)
        self.assertEqual(result.branches[1], Branch((8,), ()))
        lengths = compute('list_length', {}, {'L': source})
        self.assertEqual(lengths['L'].values(), (2, 0))
        self.assertEqual((lengths['T'], lengths['B']), (2, 2))
        for index in (2, -3, 0.25, True):
            with self.subTest(index=index), self.assertRaises(ValueError):
                compute('list_item', {}, {'L': source, 'I': index})

    def test_bool_matches_legacy_values_and_keeps_tree(self):
        self.assertIs(compute('bool', {}, {})['B'], True)
        self.assertIs(compute('bool', {}, {'V': 0})['B'], False)
        self.assertEqual(compute('bool', {}, {'V': ['OFF', 'yes', 5]})['B'].values(), (False, True, True))
        with self.assertRaises(ValueError):
            compute('bool', {}, {'V': 'perhaps'})

    def test_simplify_preserves_keys_order_and_empty_branches(self):
        tree = DataTree((Branch((3, 2, 5), ('first',), ('stable',)),
                         Branch((3, 2, 5, 0), ()),
                         Branch((3, 2, 7), ('last',), ('other',))))
        output = compute('simplify', {}, {'D': tree})
        self.assertEqual(output['T'].branches,
                         (Branch((5,), ('first',), ('stable',)), Branch((5, 0), ()),
                          Branch((7,), ('last',), ('other',))))
        self.assertEqual((output['B'], output['N']), (3, 2))
        single = compute('simplify', {}, {'D': DataTree((tree.branches[0],))})
        self.assertEqual(single['T'].branches, (Branch((0,), ('first',), ('stable',)),))
        self.assertEqual(compute('simplify', {}, {'D': DataTree(())})['T'], DataTree(()))

    def test_flip_matrix_preserves_parent_and_moves_item_keys_with_values(self):
        first = Branch((3, 2), ('a', 'b'), ('p', 'q'))
        second = Branch((3, 5), ('c', 'd'), ('r', 's'))
        output = compute('flip_matrix', {}, {'D': DataTree((first, second))})
        self.assertEqual(output['T'].branches, (Branch((3, 0), ('a', 'c'), ('p', 'r')),
                                               Branch((3, 1), ('b', 'd'), ('q', 's'))))
        self.assertEqual((output['B'], output['N']), (2, 4))
        self.assertEqual(compute('flip_matrix', {}, {'D': DataTree((first,))})['T'].branches,
                         (Branch((0,), ('a',), ('p',)), Branch((1,), ('b',), ('q',))))
        for tree in (DataTree(()), DataTree((Branch((0,), ()),)),
                     DataTree((first, Branch((3, 5), ('c',))))):
            with self.assertRaisesRegex(ValueError, 'branches of equal length'):
                compute('flip_matrix', {}, {'D': tree})

    def test_merge_and_list_item_keep_owners_when_source_keys_collide(self):
        a = NodeSpec('a', 'line', normalize_geometry_state('line', {'parameters': {'B': [10, 0, 0]}}))
        b = NodeSpec('b', 'line', normalize_geometry_state('line', {'parameters': {'B': [20, 0, 0]}}))
        merge = NodeSpec('merge', 'merge', normalize_geometry_state('merge', {}), {'A': Connection('a', 'C'), 'B': Connection('b', 'C')})
        selected = NodeSpec('selected', 'list_item', normalize_geometry_state('list_item', {'parameters': {'I': 1}}), {'L': Connection('merge', 'D')})
        simplify = NodeSpec('simplify', 'simplify', normalize_geometry_state('simplify', {}), {'D': Connection('selected', 'I')})
        flip = NodeSpec('flip', 'flip_matrix', normalize_geometry_state('flip_matrix', {}), {'D': Connection('simplify', 'T')})
        move = NodeSpec('move', 'move', normalize_geometry_state('move', {'parameters': {'Z': 5}}), {'G': Connection('flip', 'T')})
        result = GraphEngine().evaluate([a, b, merge, selected, simplify, flip, move]).results
        self.assertTrue(all(not v.error for v in result.values()))
        self.assertEqual(result['a'].outputs['C'].values()[0].key, result['b'].outputs['C'].values()[0].key)
        self.assertEqual({binding.owner for binding in result['merge'].bindings['D'].values()}, {'a','b'})
        self.assertIsNone(result['move'].parametric_object)
        self.assertNotIsInstance(result['a'].parametric_object.parts.values()[0], TranslatedValue)
        self.assertIsInstance(result['b'].parametric_object.parts.values()[0], TranslatedValue)

    def test_shift_list_forwards_only_retained_geometry_bindings(self):
        first = NodeSpec('a', 'line', normalize_geometry_state('line', {}))
        second = NodeSpec('b', 'line', normalize_geometry_state('line', {'parameters': {'B': [20, 0, 0]}}))
        merge = NodeSpec('merge', 'merge', {}, {'A': Connection('a', 'C'), 'B': Connection('b', 'C')})
        shift = NodeSpec('shift', 'shift_list', {'parameters': {'W': False}}, {'L': Connection('merge', 'D')})
        result = GraphEngine().evaluate([first, second, merge, shift]).results['shift']
        self.assertFalse(result.error)
        self.assertIsNone(result.parametric_object)
        self.assertEqual(tuple(binding.owner for binding in result.bindings['L'].values()), ('b',))

    def test_sort_list_forwards_sorted_geometry_bindings(self):
        short = NodeSpec('short', 'line', normalize_geometry_state('line', {}))
        long = NodeSpec('long', 'line', normalize_geometry_state('line', {'parameters': {'B': [20, 0, 0]}}))
        lengths = NodeSpec('lengths', 'merge', {}, {'A': Connection('long', 'L'), 'B': Connection('short', 'L')})
        lines = NodeSpec('lines', 'merge', {}, {'A': Connection('long', 'C'), 'B': Connection('short', 'C')})
        sort = NodeSpec('sort', 'sort_list', {}, {'K': Connection('lengths', 'D'), 'A': Connection('lines', 'D')})
        result = GraphEngine().evaluate([short, long, lengths, lines, sort]).results['sort']
        self.assertFalse(result.error)
        self.assertIsNone(result.parametric_object)
        self.assertEqual(result.outputs['K'].values(), (10., 20.))
        self.assertEqual(tuple(result.bindings['A'][value.key].owner for value in result.outputs['A'].values()),
                         ('short', 'long'))


class ListWindowTests(unittest.TestCase):
    setUpClass = classmethod(fixture.CurveWindowTests.setUpClass.__func__)
    setUp = fixture.CurveWindowTests.setUp
    tearDown = fixture.CurveWindowTests.tearDown
    settle = fixture.CurveWindowTests.settle

    def test_csv_relative_to_graph_updates_when_graph_moves(self):
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            root = Path(folder)
            original = root / 'original'
            relocated = root / 'copied folder'
            for directory, value in ((original, 'Original'), (relocated, 'Relocated')):
                (directory / 'data').mkdir(parents=True)
                (directory / 'data' / 'panels.csv').write_text(f'Name\n{value}\n', encoding='utf-8')
            reader = self.window.add_node('NoodleS.Data.ReadCsvNode')
            reader.set_property('parameters', {**reader.get_property('parameters'), 'P': 'data/panels.csv'})
            self.settle()
            self.assertIn('relative CSV path', self.window.evaluation.results[reader.id].error)
            for directory, value in ((original, 'Original'), (relocated, 'Relocated')):
                path = directory / 'Panels.noodles'
                self.assertTrue(self.window._save_to(path))
                self.settle()
                self.assertEqual(self.window.evaluation.results[reader.id].outputs['R'].values(), (value,))
                session = read_document(path, self.window.node_ports)
                self.assertEqual(session['nodes'][reader.id]['custom']['parameters']['P'], 'data/panels.csv')
            self.window.load_session(session, path)
            self.settle()
            reader, = self.window.graph.all_nodes()
            self.assertEqual(self.window.evaluation.results[reader.id].outputs['R'].values(), ('Relocated',))

    def test_sort_points_properties_change_axis_order_and_preserve_source_bindings(self):
        grid = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        sort = self.window.add_node('NoodleS.Data.SortPointsNode')
        grid.outputs()['P'].connect_to(sort.inputs()['P'])
        sort.set_property('tree_modes', {'P': 'flatten'})
        self.settle()
        panel = self.window.properties.curve_properties
        self.assertTrue(panel.point_sort_order.isVisible())
        self.assertEqual(panel.point_sort_order.currentText(), 'XYZ')
        result = self.window.evaluation.results[sort.id]
        original = result.outputs['P'].values()
        self.assertLess(original[0].xyz[1], original[1].xyz[1])
        self.assertIsNone(result.parametric_object)
        self.assertTrue(all(binding.owner == grid.id for binding in result.bindings['P'].values()))
        self.assertEqual(len(result.bindings['P']), len(original))
        QTest.keyClick(panel.point_sort_order, QtCore.Qt.Key_Down)
        QTest.keyClick(panel.point_sort_order, QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(panel.point_sort_order.currentText(), 'YXZ')
        reordered = self.window.evaluation.results[sort.id].outputs['P'].values()
        self.assertLess(reordered[0].xyz[0], reordered[1].xyz[0])
        self.window.graph.undo_stack().undo()
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(panel.point_sort_order.currentText(), 'XYZ')
        self.assertEqual(self.window.evaluation.results[sort.id].outputs['P'].values(), original)

    def test_value_list_options_selection_and_csv_reload_use_editor_actions(self):
        node = self.window.add_node('NoodleS.Inputs.ValueListNode')
        self.settle()
        panel = self.window.properties.curve_properties
        panel.choice_options.setPlainText('Small = 12\nLarge = 24')
        apply = next(button for button in panel.findChildren(type(panel.capture)) if button.text() == 'Apply Options')
        QTest.mouseClick(apply, QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(self.window.evaluation.results[node.id].outputs['V'], 12)
        panel.choice_picker.setFocus()
        QTest.keyClick(panel.choice_picker, QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(self.window.evaluation.results[node.id].outputs['V'], 24)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(panel.choice_picker.currentText(), 'Small')
        self.assertEqual(self.window.evaluation.results[node.id].outputs['V'], 12)

        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / 'table.csv'
            path.write_text('Panel,Area\nA,2\n', encoding='utf-8')
            reader = self.window.add_node('NoodleS.Data.ReadCsvNode')
            self.settle()
            field = panel.editors['P'][0]
            field.setFocus()
            QTest.keyClicks(field, path.as_posix())
            QTest.keyClick(field, QtCore.Qt.Key_Return)
            self.settle()
            self.assertEqual(self.window.evaluation.results[reader.id].outputs['R'].values(), ('A', '2'))
            path.write_text('Panel,Area\nB,3\n', encoding='utf-8')
            reload = next(button for button in panel.findChildren(type(panel.capture)) if button.text() == 'Reload CSV')
            QTest.mouseClick(reload, QtCore.Qt.LeftButton)
            self.settle()
            self.assertEqual(self.window.evaluation.results[reader.id].outputs['R'].values(), ('B', '3'))

    def test_bool_checkbox_and_numeric_override(self):
        node = self.window.add_node('NoodleS.Inputs.BoolNode')
        self.settle()
        panel = self.window.properties.curve_properties
        checkbox = panel.editors['V'][0]
        self.assertTrue(checkbox.isChecked())
        self.assertEqual(checkbox.text(), 'True')
        QTest.mouseClick(checkbox, QtCore.Qt.LeftButton, pos=QtCore.QPoint(8, checkbox.height()//2))
        self.settle()
        self.assertIs(self.window.evaluation.results[node.id].outputs['B'], False)
        self.assertEqual(checkbox.text(), 'False')
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(checkbox.isChecked())
        self.assertEqual(checkbox.text(), 'True')
        self.window.graph.undo_stack().redo()
        self.settle()
        self.assertEqual(checkbox.text(), 'False')
        number = self.window.graph.create_node('NoodleS.Inputs.NumberNode', selected=False)
        number.set_property('value', 1)
        number.outputs()['Number'].connect_to(node.inputs()['V'])
        self.window.graph.clear_selection()
        node.set_selected(True)
        self.settle()
        self.assertIs(self.window.evaluation.results[node.id].outputs['B'], True)
        self.assertIs(panel.stacks['V'].currentWidget(), panel.previews['V'])
        number.outputs()['Number'].disconnect_from(node.inputs()['V'])
        self.settle()
        self.assertIs(self.window.evaluation.results[node.id].outputs['B'], False)
        self.assertEqual(panel.editors['V'][0].text(), 'False')

    def test_three_data_nodes_work_in_graph_and_round_trip(self):
        nodes = {}
        for label, value in (('left', 10), ('right', 20)):
            nodes[label] = self.window.add_node('NoodleS.Inputs.NumberNode')
            nodes[label].set_property('value', value)
        merge = self.window.add_node('NoodleS.Data.MergeNode')
        nodes['left'].outputs()['Number'].connect_to(merge.inputs()['A'])
        nodes['right'].outputs()['Number'].connect_to(merge.inputs()['D'])
        length = self.window.add_node('NoodleS.Data.ListLengthNode')
        flip = self.window.add_node('NoodleS.Data.FlipMatrixNode')
        merge.outputs()['D'].connect_to(flip.inputs()['D'])
        flip.outputs()['T'].connect_to(length.inputs()['L'])
        simplify = self.window.add_node('NoodleS.Data.SimplifyNode')
        merge.outputs()['D'].connect_to(simplify.inputs()['D'])
        item = self.window.add_node('NoodleS.Data.ListItemNode')
        simplify.outputs()['T'].connect_to(item.inputs()['L'])
        self.settle()
        field = self.window.properties.curve_properties.editors['I'][0]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, '-1')
        QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(self.window.evaluation.results[item.id].outputs['I'].values(), (20,))
        self.assertEqual(self.window.evaluation.results[length.id].outputs['T'], 2)
        self.assertEqual(self.window.evaluation.results[length.id].outputs['B'], 2)
        viewer = self.window.add_node('NoodleS.Data.TreeViewerNode')
        flip.outputs()['T'].connect_to(viewer.inputs()['D'])
        self.settle()
        self.assertIn('2 item(s) · 2 branch(es)', self.window.properties.output.text())
        self.assertEqual(self.window.evaluation.results[viewer.id].outputs['P'].values(), ((0,), (1,)))
        self.assertFalse(self.window.point_service.models)
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder) / 'lists.noodles'
            session = self.window.graph.serialize_session()
            session['graph']['project_uuid'] = self.window.project_uuid
            write_document(path, session)
            self.window.load_session(read_document(path, self.window.node_ports), path)
            self.settle()
            restored = next(n for n in self.window.graph.all_nodes() if n.OPERATION == 'list_item')
            self.assertEqual(self.window.evaluation.results[restored.id].outputs['I'].values(), (20,))
            restored_flip = next(n for n in self.window.graph.all_nodes() if n.OPERATION == 'flip_matrix')
            self.assertEqual(self.window.evaluation.results[restored_flip.id].outputs['B'], 2)
            restored_viewer = next(n for n in self.window.graph.all_nodes() if n.OPERATION == 'tree_viewer')
            self.assertEqual(self.window.evaluation.results[restored_viewer.id].outputs['P'].values(), ((0,), (1,)))
