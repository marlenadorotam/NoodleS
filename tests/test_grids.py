"""Grid topology, exact recipes, matching and real Properties interactions."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_curves as ui_fixture
from test_curves import PROJECT,NODE
from noodles.backend.grids import (GRID_SPECS,GridValue,evaluate_grid,normalize_grid_state,
                                  grid_object_from_outputs,grid_from_wire,members)
from noodles.backend.curves import PlaneValue,curve_from_wire,evaluate_curve
from noodles.backend.point import object_from_wire
from noodles.backend.solids import evaluate_solid
from noodles.backend.datatree import Branch,DataTree
from noodles.document import read_document,write_document
from Qt import QtCore
from PySide6.QtTest import QTest


def state(operation,**changes):
    return normalize_grid_state(operation,{'project_uuid':PROJECT,'node_uuid':NODE,**changes})


class GridDataTests(unittest.TestCase):
    def test_legacy_counts_and_compact_single_deferred_recipe(self):
        expected={'grid_rectangle':(12,20,31),'grid_triangle':(24,44,43),
                  'grid_hexagon':(12,50,49),'grid_radial':(32,33,64)}
        for op in GRID_SPECS:
            with self.subTest(op=op):
                output=evaluate_grid(op,state(op),{})
                value=output['G'].values()[0]
                self.assertEqual(value.counts,expected[op])
                self.assertEqual(output['C'].count,value.counts[0])
                self.assertEqual(output['P'].count+output.get('V',DataTree(())).count,value.counts[1])
                self.assertEqual(output['E'].count,value.counts[2])
                model=grid_object_from_outputs(state(op),output)
                self.assertEqual(model.parts.count,1)
                self.assertEqual(object_from_wire(model.to_wire()).to_wire(),model.to_wire())
                self.assertLess(len(json.dumps(model.to_wire())),1000)

    def test_rectangle_rows_spacing_and_closed_cells(self):
        out=evaluate_grid('grid_rectangle',state('grid_rectangle'),{'Sx':2,'Sy':3,'Ex':2,'Ey':1})
        self.assertEqual([b.path for b in out['P'].branches],[(0,),(1,)])
        self.assertEqual([p.xyz for p in out['P'].values()],[(0,0,0),(2,0,0),(4,0,0),(0,3,0),(2,3,0),(4,3,0)])
        self.assertEqual([c.length for c in out['C'].values()],[10,10])
        self.assertEqual(out['C'].values()[0].points,((0,0,0),(2,0,0),(2,3,0),(0,3,0)))

    def test_point_grouping_preserves_keys_and_geometry_for_all_grids(self):
        cases = (
            ('grid_rectangle', {'Ex': 2, 'Ey': 3}, [3]*4, [4]*3),
            ('grid_triangle', {'Ex': 2, 'Ey': 3}, [4]*3, [3]*4),
            ('grid_hexagon', {'Ex': 2, 'Ey': 3}, [2]*3, [3]*2),
            ('grid_radial', {'Er': 3, 'Ep': 4}, [1, 4, 4, 4], [1, 3, 3, 3, 3]),
        )
        for operation, inputs, row_sizes, column_sizes in cases:
            with self.subTest(operation=operation):
                rows = evaluate_grid(operation, state(operation), inputs)
                self.assertEqual([len(b.items) for b in rows['P'].branches], row_sizes)
                for grouping, sizes in (('flat', [sum(row_sizes)]), ('columns', column_sizes)):
                    configured = state(operation, parameters={'point_grouping': grouping})
                    result = evaluate_grid(operation, configured, inputs)
                    self.assertEqual([b.path for b in result['P'].branches], [(i,) for i in range(len(sizes))])
                    self.assertEqual([len(b.items) for b in result['P'].branches], sizes)
                    self.assertCountEqual(result['P'].values(), rows['P'].values())
                    for port in result.keys() - {'P'}:
                        self.assertEqual(result[port], rows[port])
                    self.assertEqual(grid_object_from_outputs(configured, result),
                                     grid_object_from_outputs(state(operation), rows))
                original_rows = [b.items for b in rows['P'].branches]
                expected = list(zip(*original_rows))
                if operation == 'grid_radial':
                    expected = [original_rows[0], *zip(*original_rows[1:])]
                self.assertEqual([b.items for b in result['P'].branches], expected)

    def test_flat_keeps_grid_slots_separate_and_reference_uses_grouping(self):
        op = 'grid_rectangle'
        flat = state(op, parameters={'point_grouping': 'flat'})
        output = evaluate_grid(op, flat, {'Ex': [2, 3], 'Ey': 2})
        self.assertEqual([b.path for b in output['P'].branches], [(0, 0), (0, 1)])
        self.assertEqual([len(b.items) for b in output['P'].branches], [9, 12])
        recipe = output['G'].values()[1].to_wire()
        reference = state(op, mode='reference', parameters={'point_grouping': 'columns'},
                          references=[{'key': 'owner/slot', 'id': 'native', 'recipe': recipe, 'path': [3]}])
        result = evaluate_grid(op, reference, {})
        self.assertEqual([b.path for b in result['P'].branches], [(3, 0, i) for i in range(4)])
        self.assertEqual([len(b.items) for b in result['P'].branches], [3]*4)
        self.assertEqual([p.xyz for p in result['P'].branches[0].items],
                         [(0, 0, 0), (0, 10, 0), (0, 20, 0)])

    def test_rows_and_columns_feed_interpcurve_directly(self):
        op = 'grid_rectangle'
        for grouping, count, end in (('rows', 4, (20, 0, 0)), ('columns', 3, (0, 30, 0))):
            grid = evaluate_grid(op, state(op, parameters={'point_grouping': grouping}), {'Ex': 2, 'Ey': 3})
            curves = evaluate_curve('interpcurve', {}, {'P': grid['P']})['C']
            self.assertEqual(curves.count, count)
            self.assertEqual(curves.values()[0].points[-1], end)

    def test_triangles_equilateral_centres_and_shared_diagonals(self):
        out=evaluate_grid('grid_triangle',state('grid_triangle'),{'S':2,'Ex':1,'Ey':1})
        self.assertEqual(out['C'].count,2)
        for cell in out['C'].values():
            self.assertAlmostEqual(cell.length,6)
        self.assertAlmostEqual(out['P'].values()[0].xyz[1],math.sqrt(3)/3)
        a,b=out['C'].values()
        self.assertIs(a.segments[1],b.segments[2])
        self.assertNotEqual(a.reversed_edges[1],b.reversed_edges[2])

    def test_hexagons_share_unique_vertices_and_edges_with_nonnegative_paths(self):
        out=evaluate_grid('grid_hexagon',state('grid_hexagon'),{'S':2,'Ex':2,'Ey':1})
        self.assertEqual(out['V'].count,10)
        self.assertEqual(out['E'].count,11)
        for cell in out['C'].values():
            self.assertAlmostEqual(cell.length,12)
        self.assertIn((-2.,0.,0.),tuple(p.xyz for p in out['V'].values()))
        self.assertTrue(all(i>=0 for b in out['V'].branches for i in b.path))

    def test_radial_exact_arcs_and_angular_seam_without_duplicate_points(self):
        out=evaluate_grid('grid_radial',state('grid_radial'),{'S':2,'Er':2,'Ep':4})
        self.assertEqual(out['P'].count,9)
        self.assertEqual(out['R'].count,8)
        self.assertEqual(out['A'].count,8)
        for edge in out['A'].values():
            self.assertEqual(edge.kind,'arc')
            self.assertAlmostEqual(abs(edge.angle),math.pi/2)
        self.assertEqual([len(c.segments) for c in out['C'].values()],[3]*4+[4]*4)
        self.assertAlmostEqual(out['C'].values()[0].length,4+math.pi)
        for cell in out['C'].values():
            restored=curve_from_wire(cell.to_wire())
            self.assertEqual(restored.points,cell.points)
            self.assertAlmostEqual(restored.length,cell.length)

    def test_graft_flatten_slots_keys_and_multiple_grids_one_owner(self):
        op='grid_rectangle'
        inputs={'Sx':[2,4]}
        flat=evaluate_grid(op,state(op),inputs)
        graft=evaluate_grid(op,state(op,tree_modes={'Sx':'graft'}),inputs)
        self.assertEqual(flat['G'].count,2)
        self.assertEqual([b.path for b in graft['G'].branches],[(0,0),(0,1)])
        self.assertEqual(tuple(v.key for v in flat['G'].values()),tuple(v.key for v in graft['G'].values()))
        self.assertEqual(len({p.key for p in flat['P'].values()}),40)
        self.assertEqual(flat['P'].count,graft['P'].count)
        native=grid_object_from_outputs(state(op),flat)
        self.assertEqual(native.parts.count,2)
        self.assertEqual(native.kind,'grids')
        flattened=evaluate_grid(op,state(op,tree_modes={'Sx':'flatten'}),{'Sx':DataTree((Branch((2,),(2,)),Branch((3,),(4,))))})
        self.assertEqual(len(flattened['G'].branches),1)

    def test_grid_points_feed_boxes_without_scene_objects(self):
        op='grid_rectangle'
        out=evaluate_grid(op,state(op),{'Ex':19,'Ey':9})
        self.assertEqual(out['P'].count,200)
        boxes=evaluate_solid('box',{'project_uuid':PROJECT,'node_uuid':NODE}, {'O':out['P'],'Z':list(range(1,201))})
        self.assertEqual(boxes['G'].count,200)
        self.assertEqual([b.path for b in boxes['G'].branches],[b.path for b in out['P'].branches])
        self.assertEqual(boxes['Z'].values(),tuple(range(1,201)))

    def test_invalid_counts_sizes_coordinates_and_total_budget_fail_before_topology(self):
        with self.assertRaises(ValueError):
            state('grid_rectangle',tree_modes=[])
        for inputs in ({'Ex':0},{'Ey':-1},{'Ex':2.5},{'Sx':0},{'Sy':float('nan')},{'Ex':10000,'Ey':10000},{'Sx':1e9}):
            with self.subTest(inputs=inputs),patch('noodles.backend.grids.members') as build,self.assertRaises((ValueError,OverflowError)):
                evaluate_grid('grid_rectangle',state('grid_rectangle'),inputs)
            build.assert_not_called()
        with self.assertRaises(ValueError):
            evaluate_grid('grid_radial',state('grid_radial'),{'Ep':2})
        with self.assertRaisesRegex(ValueError,'Combined'):
            evaluate_grid('grid_rectangle',state('grid_rectangle'),{'Ex':[49]*3,'Ey':49})
        with self.assertRaisesRegex(ValueError,'equal lengths'):
            evaluate_grid('grid_rectangle',state('grid_rectangle'),{'Sx':[1,2],'Sy':[1,2,3]})

    def test_plane_and_origin_offset_vs_absolute_point(self):
        from noodles.backend.point import PointValue
        op='grid_rectangle'
        frame=PlaneValue((10,20,30),(0,1,0),(1,0,0))
        out=evaluate_grid(op,state(op,parameters={'O':[1,2,3]}),{'P':frame})
        self.assertEqual(out['P'].values()[0].xyz,(11,22,33))
        absolute=evaluate_grid(op,state(op),{'P':frame,'O':PointValue('o',(1,2,3))})
        self.assertEqual(absolute['P'].values()[0].xyz,(1,2,3))
        self.assertEqual(absolute['P'].values()[1].xyz,(1,12,3))

    def test_identity_stable_when_extents_grow_and_empty_reference_needs_capture(self):
        for op in GRID_SPECS:
            out=evaluate_grid(op,state(op),{})
            updated=evaluate_grid(op,state(op),{'Er':5} if op=='grid_radial' else {'Ex':5})
            self.assertEqual(out['G'].values()[0].key,updated['G'].values()[0].key)
            old={p.key:p.xyz for p in out['P'].values()}
            new={p.key:p.xyz for p in updated['P'].values()}
            self.assertTrue(old.items()<=new.items())
            with self.assertRaises(ValueError):
                evaluate_grid(op,state(op,mode='reference'),{})


class GridUiTests(unittest.TestCase):
    setUpClass=classmethod(ui_fixture.CurveWindowTests.setUpClass.__func__)
    setUp=ui_fixture.CurveWindowTests.setUp
    tearDown=ui_fixture.CurveWindowTests.tearDown
    settle=ui_fixture.CurveWindowTests.settle

    def test_point_grouping_properties_keyboard_undo_reference_and_save(self):
        node = self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        self.settle()
        panel = self.window.properties.curve_properties
        combo = panel.grid_grouping
        self.assertTrue(combo.isVisible())
        self.assertEqual(combo.currentText(), 'Rows')
        native = copy.deepcopy(self.window.point_service.models[node.id])
        combo.setFocus()
        QTest.keyClick(combo, QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(node.get_property('parameters')['point_grouping'], 'columns')
        points = self.window.evaluation.results[node.id].outputs['P']
        self.assertEqual([len(b.items) for b in points.branches], [4]*5)
        self.assertEqual(self.window.point_service.models[node.id], native)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(combo.currentText(), 'Rows')
        QTest.mouseClick(panel.sources['reference'], QtCore.Qt.LeftButton)
        self.settle()
        self.assertTrue(combo.isVisible())
        QTest.keyClick(combo, QtCore.Qt.Key_Up)
        self.settle()
        self.assertEqual(node.get_property('mode'), 'reference')
        self.assertEqual(node.get_property('parameters')['point_grouping'], 'flat')
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path = Path(folder)/'grouping.noodles'
            write_document(path, self.window.graph.serialize_session())
            saved = read_document(path, self.window.node_ports)
        self.assertEqual(saved['nodes'][node.id]['custom']['parameters']['point_grouping'], 'flat')

    def test_properties_count_editor_real_keys_tree_buttons_and_undo(self):
        node=self.window.add_node('NoodleS.Geometry.GridRadialNode')
        self.window.graph.select_all()
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertFalse(panel.source_modes.isHidden())
        field=panel.editors['Ep'][0]
        field.setFocus()
        QTest.keyClick(field,QtCore.Qt.Key_A,QtCore.Qt.ControlModifier)
        QTest.keyClicks(field,'12')
        QTest.keyClick(field,QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property('parameters')['Ep'],12)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(field.value(),8)
        QTest.mouseClick(panel.modifiers['Er'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'Er':'graft'})
        QTest.mouseClick(panel.modifiers['Er'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{})

    def test_all_grid_nodes_save_load_with_common_geometry_state(self):
        for spec in GRID_SPECS.values():
            self.window.add_node('NoodleS.Geometry.'+spec['class'])
        self.settle()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path=Path(folder)/'grids.noodles'
            write_document(path,self.window.graph.serialize_session())
            restored=read_document(path,self.window.node_ports)
            self.assertEqual(len(restored['nodes']),4)

    def test_new_document_discards_pending_grid_results_and_resets_worker(self):
        self.window.add_node('NoodleS.Geometry.GridRectangleNode')
        self.settle()
        old_worker=self.window._graph_worker
        self.assertIsNotNone(old_worker)
        self.window.graph.undo_stack().setClean()
        self.window.new_document()
        self.settle()
        self.assertTrue(old_worker.stopped)
        self.assertIsNone(self.window._graph_worker)
        self.assertFalse(self.window.evaluation.results)

    def test_undo_refreshes_editor_while_data_worker_is_busy(self):
        import threading
        import time
        from unittest.mock import patch
        node=self.window.add_node('NoodleS.Geometry.GridRadialNode')
        self.settle()
        panel=self.window.properties.curve_properties
        field=panel.editors['Ep'][0]
        entered,release=threading.Event(),threading.Event()
        evaluate=self.window.engine.evaluate
        def busy(snapshot):
            entered.set()
            release.wait(3)
            return evaluate(snapshot)
        with patch.object(self.window.engine,'evaluate',side_effect=busy):
            try:
                node.set_property('parameters',{**node.get_property('parameters'),'Ep':12})
                deadline=time.monotonic()+2
                while not entered.is_set() and time.monotonic()<deadline:
                    self.app.processEvents()
                    QTest.qWait(2)
                self.assertTrue(entered.is_set())
                self.window.graph.undo_stack().undo()
                self.settle()
                self.assertEqual(node.get_property('parameters')['Ep'],8)
                self.assertEqual(field.value(),8)
            finally:
                release.set()
