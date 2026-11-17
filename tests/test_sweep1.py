"""Sweep 1 Rail: branch/Qt contracts and true native OCC publication."""
import math
import unittest
from types import SimpleNamespace
from Qt import QtCore
from PySide6.QtTest import QTest
import test_operations as ui
import test_sweep_native as native
from noodles.backend.operations import evaluate_operation,operation_from_wire
from noodles.backend.curves import line,circle,arc,PlaneValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.scene_curves import materialize
from noodles.backend.sweep_native import sweep1_shape,register_commands


def inputs():
    return {'R':line('rail',(0,0,0),(0,0,10)), 'P':line('profile',(0,0,0),(5,0,0))}


class Sweep1DataTests(unittest.TestCase):
    def test_matching_tree_modifiers_roundtrip_and_invalid_input(self):
        data=inputs()
        data['R']=[data['R'],line('r2',(0,0,0),(0,0,15))]
        def result(data,modes=None):
            return evaluate_operation('sweep1',ui.state('sweep1',tree_modes=modes or {}),data)
        flat=result(data)
        graft=result(data,{'R':'graft'})
        self.assertEqual(flat['Count'],2)
        self.assertEqual([b.path for b in graft['G'].branches],[(0,0),(0,1)])
        self.assertEqual([v.key for v in flat['G'].values()],[v.key for v in graft['G'].values()])
        for value in flat['G'].values():
            self.assertEqual(operation_from_wire(value.to_wire()),value)
        with self.assertRaisesRegex(ValueError,'equal lengths'):
            result({**data,'P':[data['P']]*3})
        with self.assertRaises(ValueError):
            result({**data,'P':17})
        tree=DataTree((Branch((5,),(data['R'][0],)),Branch((9,),(data['R'][1],))))
        self.assertEqual(len(result({**data,'R':tree})['G'].branches),2)
        self.assertEqual(len(result({**data,'R':tree},{'R':'flatten'})['G'].branches),1)


class Sweep1PropertiesTests(unittest.TestCase):
    setUpClass=classmethod(ui.OperationPropertiesTests.setUpClass.__func__)
    setUp=ui.OperationPropertiesTests.setUp
    tearDown=ui.OperationPropertiesTests.tearDown
    settle=ui.OperationPropertiesTests.settle

    def test_real_modifier_clicks_undo_and_port_names(self):
        node=self.window.add_node('NoodleS.Geometry.Sweep1Node')
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertEqual(node.NODE_NAME,'Sweep 1 Rail')
        self.assertEqual(tuple(node.inputs()),('R','P'))
        self.assertFalse(panel.source_modes.isVisible())
        QTest.mouseClick(panel.modifiers['P'].buttons['graft'],QtCore.Qt.LeftButton)
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'P':'graft'})
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{})
        self.assertEqual(node.inputs()['R'].view.toolTip(),'Rail Curve')


class NativeSweep1Tests(unittest.TestCase):
    setUpClass=classmethod(native.NativeSweepTests.setUpClass.__func__)
    setUp=native.NativeSweepTests.setUp
    tearDown=native.NativeSweepTests.tearDown
    call=native.NativeSweepTests.call
    wait_for=native.NativeSweepTests.wait_for
    publish=native.NativeSweepTests.publish
    model=native.NativeSweepTests.model

    def test_open_and_closed_profiles_match_native_without_caps(self):
        rail=materialize(inputs()['R'])
        for profile in (inputs()['P'],circle('c',(0,0,0),2,PlaneValue())):
            shape=sweep1_shape(materialize(profile),rail)
            baseline=self.geo.sweep1(materialize(profile),rail)
            self.assertAlmostEqual(self.geo.surface_area(shape),self.geo.surface_area(baseline),delta=1e-6)
            self.assertEqual(self.geo.shape_kind(shape),'surface')
            expected=50 if profile.kind=='line' else 40*math.pi
            self.assertAlmostEqual(self.geo.surface_area(shape),expected,delta=1e-5)
            owner=self.publish(self.model('sweep1',{'R':inputs()['R'],'P':profile}))
            self.assertTrue(owner.mesh_ready)
            self.assertEqual(len(self.window.scene.objects),1)

    def test_curved_and_closed_rails_with_actual_kind_feedback(self):
        cases=[(arc('rail',(0,0,0),(5,0,5),(10,0,0)),circle('p',(0,0,0),1,PlaneValue())),
            (circle('rail',(0,0,0),10,PlaneValue()),circle('p',(10,0,0),1,PlaneValue(normal=(0,1,0))))]
        for rail,profile in cases:
            data={'R':rail,'P':profile}
            owner=self.publish(self.model('sweep1',data))
            job=next(reversed(self.bridge.geometry.jobs.values()))
            result=evaluate_operation('sweep1',{**ui.state('sweep1'),'curve_details':job['curve_details']},data)
            self.assertEqual(result['K'].values(),('surface',))
            self.assertGreater(self.geo.surface_area(owner.shape),1)

    def test_two_hundred_profiles_one_owner_and_bad_job_keeps_previous_geometry(self):
        data=inputs()
        data['P']=[line(str(i),(0,0,0),(1+i*.01,0,0)) for i in range(200)]
        owner=self.publish(self.model('sweep1',data))
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertEqual(len(self.geo.faces_of(owner.shape)),200)
        shape=owner._shape
        # A straight profile parallel to its rail produces zero-area geometry.
        bad={'R':inputs()['R'],'P':line('parallel',(0,0,0),(0,0,5))}
        request=self.call('geometry.prepare',{'model':self.model('sweep1',bad)})
        self.wait_for(lambda:self.bridge.geometry.jobs[request['job_id']]['state']!='preparing')
        self.assertEqual(self.call('geometry.job',request)['state'],'error')
        self.assertIs(self.window.scene.get(owner.id)._shape,shape)

    def test_async_command_keeps_builtin_and_native_sources(self):
        from serpentine3d.commands import base,surfaces
        self.window._noodles_bridge=self.bridge
        original=base.resolve('sweep1')
        register_commands(self.ctx)
        self.assertIs(base.resolve('sweep1'),original)
        rail=self.window.scene.add(materialize(inputs()['R']))
        profile=self.window.scene.add(materialize(inputs()['P']))
        messages=[]
        generator=base.resolve('sweep1param').fn(SimpleNamespace(echo=messages.append))
        next(generator)
        generator.send([rail])
        with self.assertRaises(StopIteration):
            generator.send([profile])
        self.wait_for(lambda:any(m.startswith('Created ') for m in messages))
        self.assertEqual(len(self.window.scene.objects),3)
        self.assertIsNotNone(self.window.scene.get(rail.id))
        self.assertIsNotNone(self.window.scene.get(profile.id))
