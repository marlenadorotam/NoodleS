"""Sweep node inputs, DataTree matching, persistent options and real Qt actions."""
import tempfile
from pathlib import Path
import unittest
from Qt import QtCore
from PySide6.QtTest import QTest
import test_operations as fixture
from noodles.backend.operations import evaluate_operation,operation_from_wire
from noodles.backend.curves import line,arc,curve_from_wire
from noodles.backend.datatree import Branch,DataTree
from noodles.port_names import full_port_name
from noodles.document import write_document,read_document


def setup_inputs():
    return {'R1':line('r1',(0,0,0),(0,0,10)),
            'R2':line('r2',(5,0,0),(10,0,10)), 'P':line('p',(0,0,0),(5,0,0))}


class SweepDataTests(unittest.TestCase):
    def evaluate(self,operation,data,**changes):
        return evaluate_operation(operation,fixture.state(operation,**changes),data)

    def test_native_and_birail_have_independent_recipe_roundtrips_and_options(self):
        for op in ('sweep2','birail_sweep'):
            out=self.evaluate(op,setup_inputs())
            value=out['G'].values()[0]
            self.assertEqual(value.sources,tuple(setup_inputs()[p] for p in ('R1','R2','P')))
            self.assertEqual(operation_from_wire(value.to_wire()),value)
            self.assertEqual(out['Count'],1)
            if op=='birail_sweep':
                self.assertEqual((value.rail_samples,value.profile_samples),(33,25))
            else:
                self.assertNotIn('rail_samples',value.to_wire())
        for parameters in ({'Rs':3},{'Ps':2.2},{'Rs':130},{'Rs':True},{'Rs':129,'Ps':129}):
            with self.subTest(parameters=parameters),self.assertRaises(ValueError):
                self.evaluate('birail_sweep',{**setup_inputs(),**parameters})

    def test_explicit_matching_graft_flatten_and_stable_keys(self):
        data=setup_inputs()
        r=data['R2']
        data['R2']=[r,line('r3',(5,0,0),(15,0,10))]
        for op in ('sweep2','birail_sweep'):
            flat=self.evaluate(op,data)
            graft=self.evaluate(op,data,tree_modes={'R2':'graft'})
            self.assertEqual(flat['Count'],2)
            self.assertEqual([b.path for b in graft['G'].branches],[(0,0),(0,1)])
            self.assertEqual([v.key for v in flat['G'].values()],[v.key for v in graft['G'].values()])
            changed=self.evaluate(op,{**data,'R2':[r,line('r3',(5,0,0),(16,0,10))]})
            self.assertEqual([v.key for v in changed['G'].values()],[v.key for v in flat['G'].values()])
            # A flattened connected input retains provenance and item order.
            joined=self.evaluate(op,{**data,'R2':DataTree((Branch((7,),(r,)),Branch((9,),(r,))))},tree_modes={'R2':'flatten'})
            self.assertEqual(len(joined['G'].branches),1)
            self.assertEqual(joined['Count'],2)
            with self.assertRaisesRegex(ValueError,'equal lengths'):
                self.evaluate(op,{**data,'R1':[data['R1']]*3})
            with self.assertRaises(ValueError):
                self.evaluate(op,{**data,'P':(0,0,0)})
        # Sample count can vary per result, never generates an implicit product.
        result=self.evaluate('birail_sweep',{**data,'Rs':[17,49]})
        self.assertEqual([v.rail_samples for v in result['G'].values()],[17,49])

    def test_asymmetric_three_point_arcs_roundtrip_without_weakening_validation(self):
        value=arc('rail',(5,0,0),(9,3,5),(12,0,10))
        wire=value.to_wire()
        self.assertEqual(curve_from_wire(wire),value)
        for mid in ((9,3.1,5),(9,3,5.1),(5,0,0)):
            bad={**wire,'points':[wire['points'][0],list(mid),wire['points'][2]]}
            with self.assertRaises(ValueError):
                curve_from_wire(bad)


class SweepPropertiesTests(unittest.TestCase):
    setUpClass=classmethod(fixture.OperationPropertiesTests.setUpClass.__func__)
    setUp=fixture.OperationPropertiesTests.setUp
    tearDown=fixture.OperationPropertiesTests.tearDown
    settle=fixture.OperationPropertiesTests.settle

    def test_sample_typing_undo_modifiers_tooltips_names_and_saved_graph(self):
        native=self.window.add_node('NoodleS.Geometry.Sweep2Node')
        node=self.window.add_node('NoodleS.Geometry.BiRailSweepNode')
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertEqual(native.NODE_NAME,'Sweep 2 Rails')
        self.assertEqual(node.NODE_NAME,'BiRail Sweep')
        editor=panel.editors['Rs'][0]
        editor.setFocus()
        QTest.keyClick(editor,QtCore.Qt.Key_A,QtCore.Qt.ControlModifier)
        QTest.keyClicks(editor,'49')
        QTest.keyClick(editor,QtCore.Qt.Key_Return)
        self.settle()
        self.assertEqual(node.get_property('parameters')['Rs'],49)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(editor.value(),33)
        QTest.mouseClick(panel.modifiers['R2'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'R2':'graft'})
        self.assertEqual(full_port_name('birail_sweep','Rs',True),'Rail Samples')
        self.assertEqual(full_port_name('sweep2','R2',True),'Rail 2 (Orientation Guide)')
        with tempfile.TemporaryDirectory(prefix="noodles-test-") as folder:
            path=Path(folder)/'sweeps.noodles'
            write_document(path,self.window.graph.serialize_session())
            loaded=read_document(path,self.window.node_ports)
            self.assertEqual(len(loaded['nodes']),2)
        category=self.window.palette._category_items['NoodleS.Operations']
        names=[category.child(i).text(0) for i in range(category.childCount())]
        self.assertIn('Sweep 2 Rails',names)
        self.assertIn('BiRail Sweep',names)
