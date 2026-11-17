"""Pure operation recipes, branch semantics and Properties interactions."""
import copy
import math
import tempfile
from pathlib import Path
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_curves as ui_fixture
from test_curves import PROJECT,NODE
from noodles.backend.operations import (OPERATION_SPECS,OperationValue,evaluate_operation,
    normalize_operation_state,operation_object_from_outputs,operation_from_wire)
from noodles.backend.curves import circle,line,PlaneValue,polyline
from noodles.backend.solids import SolidValue
from noodles.backend.booleans import PARAMETRIC_BOOLEANS
from noodles.backend.topology_operations import TOPOLOGY_OPERATIONS
from noodles.backend.arithmetic import VectorValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.point import object_from_wire
from noodles.backend.splines import PendingGeometry,signature
from noodles.document import read_document,write_document


def state(op,**changes):
    return normalize_operation_state(op,{'project_uuid':PROJECT,'node_uuid':NODE,**changes})


def sections():
    return [circle('c'+str(i),(0,0,10*i),5+i,PlaneValue()) for i in range(3)]


def inputs(op):
    if op == 'box_morph':
        source = SolidValue('module', 'box', PlaneValue(), (8, 5, 1))
        box = OperationValue('bounds', 'bounding_box', (source,))
        target = OperationValue('cage', 'surface_box', (), box_corners=(
            (0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
            (0, 0, 1), (2, 0, 1), (2, 2, 1), (0, 2, 1)))
        return {'G': source, 'R': box, 'T': target}
    if op == 'isotrim':
        from noodles.backend.domain import DomainValue
        from noodles.backend.surface_uv import Domain2Value

        source = SolidValue('target', 'cylinder', PlaneValue(), (10, 20), False)
        return {'S': source, 'D': Domain2Value(DomainValue(0, 1), DomainValue(1, 4))}
    if op in ('bounding_box', 'surface_morph'):
        from noodles.backend.domain import DomainValue

        source = SolidValue('logo', 'box', PlaneValue(), (8, 5, 1))
        if op == 'bounding_box':
            return {'C': source}
        box = OperationValue('bounds', 'bounding_box', (source,))
        target = SolidValue('target', 'cylinder', PlaneValue(), (10, 20), False)
        return {'G': source, 'R': box, 'S': target, 'U': DomainValue(0, 1.26)}
    if op in ('array', 'array_polar', 'objects_on_points'):
        from noodles.backend.point import PointValue
        if op == 'objects_on_points':
            return {'G': PointValue('source', (0, 0, 0)), 'P': PointValue('at', (4, 5, 0))}
        return {'G': PointValue('source', (1, 0, 0)), **({'N': 2} if op == 'array_polar' else {})}
    if op == 'map_surface':
        def surface(key, z):
            return OperationValue(key, 'planar_surface', (circle(key, (0, 0, z), 5, PlaneValue()),))
        return {'C': line('curve', (0, 0, 0), (1, 0, 0)), 'S': surface('source', 0), 'T': surface('target', 10)}
    if op == 'fillet_parametric':
        from noodles.backend.point import PointValue
        return {'A': line('a', (-10, 0, 0), (0, 0, 0)), 'B': line('b', (0, 0, 0), (0, 10, 0)),
                'N': PointValue('near', (0, 0, 0))}
    if op == 'fillet_edge':
        return {'G': SolidValue('box', 'box', PlaneValue(), (10, 10, 10))}
    if op == 'offset':
        return {'G': line('line', (0, 0, 0), (10, 0, 0))}
    if op == 'project':
        return {'G': line('line', (0, 0, 0), (10, 0, 1))}
    if op == 'scale_non_uniform':
        return {'G': SolidValue('module', 'box', PlaneValue(), (2, 3, 4)),
                'P': PlaneValue((1, 2, 3), (0, 1, 0)), 'X': 2., 'Y': .5, 'Z': -1.}
    if op == 'cap_holes':
        return {'B': SolidValue('shell', 'cylinder', PlaneValue(), (4, 5), False)}
    if op in PARAMETRIC_BOOLEANS:
        a = SolidValue('a', 'box', PlaneValue(), (10, 10, 10))
        b = SolidValue('b', 'box', PlaneValue(origin=(5, 0, 0)), (10, 10, 10))
        return {'A': a, 'B': b} if op == 'boolean_difference_parametric' else {'O': [a, b]}
    if op == 'pipe':
        return {'C': line('rail', (0, 0, 0), (0, 0, 20)), 'R': 2}
    if op=='patch':
        return {'C':polyline('outline',((0,0,0),(5,0,0),(5,5,1),(0,5,0)),True)}
    if op=='sweep1':
        return {'R':line('r',(0,0,0),(0,0,10)),'P':line('p',(0,0,0),(5,0,0))}
    if op in ('sweep2','birail_sweep'):
        return {'R1':line('r1',(0,0,0),(0,0,10)),'R2':line('r2',(5,0,0),(5,0,10)),
            'P':line('p',(0,0,0),(5,0,0))}
    if op=='planar_surface':
        return {'C':sections()[0]}
    if op=='edge_surface':
        return {'C':[line('a',(0,0,0),(5,0,0)),line('b',(0,5,0),(5,5,0))]}
    if op=='surface_from_points':
        from noodles.backend.point import PointValue
        return {'P':[PointValue(str(i),(i%2,i//2,0)) for i in range(4)], 'U': 2}
    if op=='extrude':
        return {'G':sections()[0]}
    if op=='revolve':
        return {'C':line('l',(5,0,0),(5,0,10))}
    return {'C':sections()}


class OperationDataTests(unittest.TestCase):
    def test_fillet_edge_matches_radii_and_point_branches(self):
        from noodles.backend.point import PointValue

        op = 'fillet_edge'
        box = inputs(op)['G']
        p = PointValue('p', (5, 0, 0))
        q = PointValue('q', (5, 10, 0))
        parameters = state(op, parameters={'fillet_mode': 'selected'}, tree_modes={'E': 'graft'})
        result = evaluate_operation(op, parameters, {'G': box, 'E': [p, q]})
        self.assertEqual([b.path for b in result['G'].branches], [(0, 0), (0, 1)])
        self.assertEqual([part.fillet_points for part in result['G'].values()], [(p.xyz,), (q.xyz,)])
        parts = evaluate_operation(op, state(op), {'G': box, 'R': [0, 2], 'E': 'ignored'})['G'].values()
        self.assertEqual(tuple(part.radius for part in parts), (0, 2))
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            evaluate_operation(op, state(op), {'G': box, 'R': -1})

    def test_offset_modes_are_properties_and_distance_matches_the_tree(self):
        a = line('a', (0, 0, 0), (5, 0, 0))
        b = line('b', (0, 3, 0), (5, 3, 0))
        data = {'G': DataTree((Branch((3,), (a,)), Branch((7,), (b,)))),
                'D': DataTree((Branch((7,), (-2,)), Branch((3,), (4,)))), 'P': 'XY'}
        parameters = state('offset', parameters={'fill': True})
        outputs = evaluate_operation('offset', parameters, data)
        self.assertEqual([branch.path for branch in outputs['G'].branches], [(3,), (7,)])
        self.assertEqual(outputs['D'].values(), (4., -2.))
        self.assertTrue(all(part.fill and not part.solid for part in outputs['G'].values()))
        self.assertEqual(tuple(d.port for d in OPERATION_SPECS['offset']['inputs']), ('G', 'D', 'P'))
        with self.assertRaisesRegex(ValueError, 'one result mode'):
            state('offset', parameters={'fill': True, 'solid': True})
        with self.assertRaisesRegex(ValueError, 'nonzero'):
            evaluate_operation('offset', parameters, {**data, 'D': 0})
    def test_boolean_difference_matches_lists_of_cutters_and_preserves_paths(self):
        op = 'boolean_difference_parametric'
        a, b = inputs('boolean_union_parametric')['O']
        bases = DataTree((Branch((2,), (a,)), Branch((5,), (a,))))
        result = evaluate_operation(op, state(op), {'A': bases, 'B': b})
        self.assertEqual([branch.path for branch in result['G'].branches], [(2,), (5,)])
        self.assertEqual([value.sources for value in result['G'].values()], [(a, b), (a, b)])
        self.assertEqual(result['Flat'].branches[0].path, (0,))
        self.assertEqual(result['Flat'].values(), result['G'].values())
        wrong_paths = DataTree((Branch((2,), (b,)), Branch((3,), (b,))))
        with self.assertRaisesRegex(ValueError, 'match the From paths'):
            evaluate_operation(op, state(op), {'A': bases, 'B': wrong_paths})

    def test_boolean_union_rejects_same_owner_forwarded_twice_by_merge(self):
        from uuid import uuid4
        from noodles.backend.solids import normalize_solid_state
        from noodles.core import Connection, GraphEngine, NodeSpec

        def box(node_id):
            return NodeSpec(node_id, 'box', normalize_solid_state('box', {
                'project_uuid': PROJECT, 'node_uuid': str(uuid4()),
            }))

        op = 'boolean_union_parametric'
        merge = NodeSpec('merge', 'merge', inputs={'A': Connection('a', 'G'), 'B': Connection('a', 'G')})
        union = NodeSpec('union', op, state(op), {'O': Connection('merge', 'D')})
        engine = GraphEngine()
        source_a, source_b = box('a'), box('b')
        self.assertIn('Duplicate', engine.evaluate([source_a, merge, union]).results['union'].error)
        merge = NodeSpec('merge', 'merge', inputs={'A': Connection('a', 'G'), 'B': Connection('b', 'G')})
        evaluation = engine.evaluate([source_a, source_b, merge, union])
        self.assertIsNone(evaluation.results['union'].error)
        result = evaluation.results['union']
        self.assertEqual(result.outputs['Count'], 1)
        self.assertEqual(result.bindings['Flat'], result.bindings['G'])

    def test_recipes_roundtrip_are_deferred_and_native_kind_is_pending(self):
        for op in OPERATION_SPECS:
            if op in ('deconstruct_brep', 'surface_box') or op in TOPOLOGY_OPERATIONS:
                continue  # Piece topology must be read before these nodes can publish.
            with self.subTest(op=op):
                out=evaluate_operation(op,state(op),inputs(op))
                model=operation_object_from_outputs(state(op),out)
                self.assertEqual(model.kind,'operations')
                self.assertEqual(model.parts.count, 2 if op == 'array_polar' else 1)
                self.assertEqual(object_from_wire(model.to_wire()).to_wire(),model.to_wire())
                if op in ('bounding_box', 'surface_morph', 'box_morph', 'isotrim', 'project', 'scale_non_uniform'):
                    continue
                if op == 'fillet_parametric':
                    self.assertEqual(out['R'].values(), (1.,))
                    continue
                if op in ('array', 'array_polar', 'objects_on_points', 'map_surface'):
                    self.assertEqual(out['Count'], model.parts.count)
                    continue
                self.assertIsInstance(out['K'].values()[0],PendingGeometry)
                value=out[OPERATION_SPECS[op]['primary']].values()[0]
                result=evaluate_operation(op,{**state(op),'curve_details':{value.key:{'signature':signature(value),'kind':'surface'}}},inputs(op))
                self.assertEqual(result['K'].values(),('surface',))
                changed=evaluate_operation(op,{**state(op),'curve_details':{value.key:{'signature':'stale','kind':'solid'}}},inputs(op))
                self.assertIsInstance(changed['K'].values()[0],PendingGeometry)

    def test_extrude_vectors_branch_matching_graft_and_stable_keys(self):
        op='extrude'
        data={'G':sections(),'V':VectorValue((1,2,-3))}
        flat=evaluate_operation(op,state(op),data)
        graft=evaluate_operation(op,state(op,tree_modes={'G':'graft'}),data)
        self.assertEqual(flat['Count'],3)
        self.assertEqual(tuple(v.key for v in flat['G'].values()),tuple(v.key for v in graft['G'].values()))
        self.assertEqual([b.path for b in graft['G'].branches],[(0,0),(0,1),(0,2)])
        self.assertEqual(graft['G'].values()[0].vector,(1,2,-3))
        for bad in ([1,2,3],VectorValue((0,0,0))):
            with self.assertRaises(ValueError):
                evaluate_operation(op,state(op),{'G':sections()[0],'V':bad})
        with self.assertRaisesRegex(ValueError,'equal lengths'):
            evaluate_operation(op,state(op),{'G':sections(),'V':[VectorValue((0,0,1))]*2})

    def test_revolve_axis_line_plane_signed_angle_and_invalid_axis(self):
        op='revolve'
        source=inputs(op)['C']
        axis=line('axis',(10,20,30),(10,30,30))
        out=evaluate_operation(op,state(op),{'C':source,'A':axis,'D':-90})
        value=out['G'].values()[0]
        self.assertEqual(value.axis.origin,(10,20,30))
        self.assertEqual(value.axis.normal,(0,1,0))
        self.assertEqual(value.angle,-90)
        for angle in (0,361,-361,float('nan')):
            with self.assertRaises(ValueError):
                evaluate_operation(op,state(op),{'C':source,'D':angle})
        for axis in (sections()[0],VectorValue((0,0,1)),polyline('p',((0,0,0),(0,0,10)),False)):
            with self.assertRaises(ValueError):
                evaluate_operation(op,state(op),{'C':source,'A':axis})

    def test_loft_one_per_branch_options_and_flatten_graft(self):
        curves=sections()
        tree=DataTree((Branch((4,),tuple(curves)),Branch((7,),tuple(curves))))
        out=evaluate_operation('loft',state('loft'),{'C':tree,'T':1})
        self.assertEqual(out['Count'],2)
        self.assertEqual(out['SC'].values(),(3,3))
        self.assertEqual([b.path for b in out['G'].branches],[(4,),(7,)])
        self.assertTrue(all(v.ruled for v in out['G'].values()))
        with self.assertRaisesRegex(ValueError,'2..240'):
            evaluate_operation('loft',state('loft',tree_modes={'C':'graft'}),{'C':curves})
        separate=DataTree((Branch((4,),tuple(curves[:1])),Branch((7,),tuple(curves[1:]))))
        joined=evaluate_operation('loft',state('loft',tree_modes={'C':'flatten'}),{'C':separate})
        self.assertEqual(joined['Count'],1)
        self.assertEqual(joined['SC'].values(),(3,))
        # Local part keys can coincide across two independent source nodes.
        same_local_key=[circle('slot',(0,0,z),5,PlaneValue()) for z in (0,10)]
        self.assertEqual(evaluate_operation('loft',state('loft'),{'C':same_local_key})['Count'],1)
        for args in ({'Cl':True,'C':curves[:2]},{'C':[curves[0],curves[0]]},{'C':curves,'T':[0,1]}):
            with self.assertRaises(ValueError):
                evaluate_operation('loft',state('loft'),args)

    def test_nested_surface_expression_and_depth_budget(self):
        base=evaluate_operation('extrude',state('extrude'),{'G':line('l',(0,0,0),(5,0,0)),
            'V':VectorValue((0,5,0))})['G'].values()[0]
        nested=evaluate_operation('extrude',state('extrude'),{'G':base,'V':VectorValue((0,0,5))})['G'].values()[0]
        self.assertEqual(operation_from_wire(nested.to_wire()),nested)
        value=nested
        while value.depth<16:
            value=OperationValue(str(value.depth),'extrude',(value,))
        with self.assertRaisesRegex(ValueError,'budget'):
            OperationValue('deep','extrude',(value,))
        bad=copy.deepcopy(value.to_wire())
        bad['sources'][0]['kind']='invalid'
        with self.assertRaises(ValueError):
            operation_from_wire(bad)


class OperationPropertiesTests(unittest.TestCase):
    setUpClass=classmethod(ui_fixture.CurveWindowTests.setUpClass.__func__)
    setUp=ui_fixture.CurveWindowTests.setUp
    tearDown=ui_fixture.CurveWindowTests.tearDown
    def test_fillet_modes_keep_the_wire_and_ignore_invalid_edge_points_in_all(self):
        box = self.window.add_node('NoodleS.Geometry.BoxNode')
        number = self.window.add_node('NoodleS.Inputs.NumberNode')
        node = self.window.add_node('NoodleS.Geometry.FilletEdgeNode')
        box.outputs()['G'].connect_to(node.inputs()['G'])
        number.outputs()['Number'].connect_to(node.inputs()['E'])
        self.settle()
        panel = self.window.properties.curve_properties
        self.assertTrue(panel.fillet_buttons['all'].isChecked())
        self.assertIsNone(self.window.evaluation.results[node.id].error)
        self.assertFalse(panel.modifiers['E'].isEnabled())
        QTest.mouseClick(panel.fillet_buttons['selected'], QtCore.Qt.LeftButton)
        self.settle()
        self.assertTrue(panel.fillet_buttons['selected'].isChecked())
        self.assertFalse(panel.fillet_capture.isEnabled())
        self.assertIsNotNone(self.window.evaluation.results[node.id].error)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(panel.fillet_buttons['all'].isChecked())
        self.assertEqual(node.inputs()['E'].connected_ports(), [number.outputs()['Number']])
    def test_offset_checkboxes_are_exclusive_and_undoable(self):
        node = self.window.add_node('NoodleS.Geometry.OffsetNode')
        self.settle()
        panel = self.window.properties.curve_properties
        fill, solid = (panel.offset_checks[mode] for mode in ('fill', 'solid'))
        for box in (fill, solid):
            QTest.mouseClick(box, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, box.height() // 2))
            self.settle()
        self.assertFalse(node.get_property('parameters')['fill'])
        self.assertTrue(node.get_property('parameters')['solid'])
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(fill.isChecked())
        self.assertFalse(solid.isChecked())

    def test_show_parent_checkbox_is_undoable_and_requests_source_visibility(self):
        first = self.window.add_node('NoodleS.Geometry.BoxNode')
        second = self.window.add_node('NoodleS.Geometry.BoxNode')
        merge = self.window.add_node('NoodleS.Data.MergeNode')
        union = self.window.add_node('NoodleS.Geometry.BooleanUnionParametricNode')
        first.outputs()['G'].connect_to(merge.inputs()['A'])
        second.outputs()['G'].connect_to(merge.inputs()['B'])
        merge.outputs()['D'].connect_to(union.inputs()['O'])
        self.settle()
        checkbox = self.window.properties.curve_properties.show_parent
        self.assertTrue(checkbox.isChecked())
        QTest.mouseClick(checkbox, QtCore.Qt.LeftButton, pos=QtCore.QPoint(7, checkbox.height() // 2))
        self.settle()
        request = self.window.point_service.models[union.id]
        self.assertEqual({target[2] for target in request['hidden_parents']},
                         {node.curve_state()['node_uuid'] for node in (first, second)})
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertNotIn('hidden_parents', self.window.point_service.models[union.id])

    def settle(self):
        import time
        ui_fixture.CurveWindowTests.settle(self)
        deadline=time.monotonic()+3
        while self.window._graph_worker and self.window._graph_worker.running and time.monotonic()<deadline:
            self.app.processEvents()
            QTest.qWait(2)

    def test_vector_defaults_cap_checkbox_graft_and_undo_real_events(self):
        node=self.window.add_node('NoodleS.Geometry.ExtrudeNode')
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertEqual(len(panel.editors['V']),3)
        z=panel.editors['V'][2]
        z.setFocus()
        QTest.keyClick(z,QtCore.Qt.Key_A,QtCore.Qt.ControlModifier)
        QTest.keyClicks(z,'25')
        QTest.keyClick(z,QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property('parameters')['V'],[0,0,25])
        cap=panel.editors['C'][0]
        QTest.mouseClick(cap,QtCore.Qt.LeftButton,pos=QtCore.QPoint(8,cap.height()//2))
        self.settle()
        self.assertFalse(node.get_property('parameters')['C'])
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertTrue(cap.isChecked())
        QTest.mouseClick(panel.modifiers['G'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'G':'graft'})

    def test_loft_choices_and_save_roundtrip(self):
        node=self.window.add_node('NoodleS.Geometry.LoftNode')
        self.settle()
        panel=self.window.properties.curve_properties
        editor=panel.editors['T'][0]
        editor.setFocus()
        QTest.keyClick(editor,QtCore.Qt.Key_Down)
        self.settle()
        self.assertEqual(node.get_property('parameters')['T'],1)
        self.window.add_node('NoodleS.Geometry.RevolveNode')
        self.settle()
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path=Path(folder)/'operations.noodles'
            write_document(path,self.window.graph.serialize_session())
            loaded=read_document(path,self.window.node_ports)
            self.assertEqual(len(loaded['nodes']),2)

    def test_loft_options_node_drives_existing_loft_port_contract(self):
        from noodles.backend.data_helpers import evaluate_data_helper
        options = evaluate_data_helper('loft_options', {}, {'T': 1, 'A': False})['O']
        loft = evaluate_operation('loft', state('loft'), {'C': sections(), 'O': options})['G'].values()[0]
        self.assertTrue(loft.ruled)
        self.assertFalse(loft.adjust)
        explicit = evaluate_operation('loft', state('loft'), {'C': sections(), 'O': options, 'T': 0})
        self.assertFalse(explicit['G'].values()[0].ruled)
        unsupported = evaluate_data_helper('loft_options', {}, {'B': True})['O']
        with self.assertRaisesRegex(ValueError, 'Rebuild or Refit'):
            evaluate_operation('loft', state('loft'), {'C': sections(), 'O': unsupported})
