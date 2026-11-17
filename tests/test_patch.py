"""Patch grouping/Qt controls and true OCC filling of planar/non-planar outlines."""
import unittest
from types import SimpleNamespace
from Qt import QtCore
from PySide6.QtTest import QTest
import test_operations as ui
import test_sweep_native as native
from noodles.backend.operations import evaluate_operation,operation_from_wire
from noodles.backend.curves import line,polyline,circle,PlaneValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.scene_curves import materialize
from noodles.backend.surface_native import patch_shape,register_commands


def corners(z=1):
    return ((0,0,0),(5,0,0),(6,3,z),(3,6,0),(0,4,0))


def boundary(z=1):
    pts=corners(z)
    return tuple(line(str(i),a,b) for i,(a,b) in enumerate(zip(pts,pts[1:]+pts[:1])))


class PatchDataTests(unittest.TestCase):
    def test_branch_grouping_flatten_and_recipe_roundtrip(self):
        curves=boundary()
        data=DataTree((Branch((5,),curves),Branch((9,),curves)))
        result=evaluate_operation('patch',ui.state('patch'),{'C':data})
        self.assertEqual(result['Count'],2)
        self.assertEqual([b.path for b in result['G'].branches],[(5,),(9,)])
        for value in result['G'].values():
            self.assertEqual(len(value.sources),5)
            self.assertEqual(operation_from_wire(value.to_wire()),value)
        separated=DataTree(tuple(Branch((i,),(c,)) for i,c in enumerate(curves)))
        joined=evaluate_operation('patch',ui.state('patch',tree_modes={'C':'flatten'}),{'C':separated})
        self.assertEqual(joined['Count'],1)
        self.assertEqual(len(joined['G'].values()[0].sources),5)
        split=evaluate_operation('patch',ui.state('patch',tree_modes={'C':'graft'}),{'C':curves})
        self.assertEqual(split['Count'],5)  # Native validation rejects the open singleton loops.

    def test_duplicate_boundaries_and_numeric_data_are_rejected(self):
        c=boundary()[0]
        for values in ([c,c],123):
            with self.assertRaises(ValueError):
                evaluate_operation('patch',ui.state('patch'),{'C':values})


class PatchPropertiesTests(unittest.TestCase):
    setUpClass=classmethod(ui.OperationPropertiesTests.setUpClass.__func__)
    setUp=ui.OperationPropertiesTests.setUp
    tearDown=ui.OperationPropertiesTests.tearDown
    settle=ui.OperationPropertiesTests.settle

    def test_flatten_click_toggle_and_undo_on_compact_patch_node(self):
        node=self.window.add_node('NoodleS.Geometry.PatchNode')
        self.settle()
        panel=self.window.properties.curve_properties
        self.assertEqual(tuple(node.inputs()),('C',))
        self.assertEqual(tuple(node.outputs()),('G','K','EC','Count'))
        self.assertFalse(panel.source_modes.isVisible())
        for expected in ({'C':'flatten'},{}):
            QTest.mouseClick(panel.modifiers['C'].buttons['flatten'],QtCore.Qt.LeftButton)
            self.settle()
            self.assertEqual(node.get_property('tree_modes'),expected)
        self.window.graph.undo_stack().undo()
        self.settle()
        self.assertEqual(node.get_property('tree_modes'),{'C':'flatten'})


class NativePatchTests(unittest.TestCase):
    setUpClass=classmethod(native.NativeSweepTests.setUpClass.__func__)
    setUp=native.NativeSweepTests.setUp
    tearDown=native.NativeSweepTests.tearDown
    call=native.NativeSweepTests.call
    wait_for=native.NativeSweepTests.wait_for
    publish=native.NativeSweepTests.publish
    model=native.NativeSweepTests.model

    def test_planar_and_nonplanar_five_edge_boundaries_and_multi_edge_wire(self):
        for z in (0,1,3):
            shapes=[materialize(c) for c in boundary(z)]
            points=[self.geo.sample_curve(s,3) for s in shapes]
            result=patch_shape(list(reversed(shapes)))
            self.assertEqual(len(self.geo.faces_of(result)),1)
            self.assertEqual(len(self.geo.edges_of(result)),5)
            self.assertGreater(self.geo.surface_area(result),1)
            single=patch_shape([materialize(polyline('outline',corners(z),True))])
            self.assertAlmostEqual(self.geo.surface_area(single),self.geo.surface_area(result),delta=1e-3)
            self.assertEqual([self.geo.sample_curve(s,3) for s in shapes],points)

    def test_closed_outline_required_no_disconnected_holes_or_single_edge(self):
        bad=[boundary()[:3],(circle('outer',(0,0,0),5,PlaneValue()),circle('hole',(0,0,0),2,PlaneValue())),
             (circle('single',(0,0,0),2,PlaneValue()),),
             (polyline('cross',((0,0,0),(2,2,0),(0,2,0),(2,0,0)),True),)]
        for curves in bad:
            with self.subTest(curves=curves),self.assertRaises(ValueError):
                patch_shape([materialize(c) for c in curves])

    def test_collection_native_measurements_attributes_and_invalid_job_rollback(self):
        data={'C':DataTree((Branch((3,),boundary(1)),Branch((7,),boundary(3))))}
        model=self.model('patch',data)
        owner=self.publish(model)
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertEqual(len(self.geo.faces_of(owner.shape)),2)
        self.assertTrue(owner.mesh_ready)
        job=next(reversed(self.bridge.geometry.jobs.values()))
        out=evaluate_operation('patch',{**ui.state('patch'),'curve_details':job['curve_details']},data)
        self.assertEqual(out['K'].values(),('surface','surface'))
        self.assertEqual(out['EC'].values(),(5,5))
        self.window.scene.update(owner.id,name='Five sided caps',color=(.2,.4,.8))
        shape=owner._shape
        request=self.call('geometry.prepare',{'model':self.model('patch',{'C':boundary()[:3]})})
        self.wait_for(lambda:self.bridge.geometry.jobs[request['job_id']]['state']!='preparing')
        self.assertEqual(self.call('geometry.job',request)['state'],'error')
        self.assertIs(self.window.scene.get(owner.id)._shape,shape)
        self.assertEqual(self.window.scene.get(owner.id).name,'Five sided caps')

    def test_async_command_uses_same_factory_and_preserves_builtin(self):
        from serpentine3d.commands import base,surfaces2
        self.window._noodles_bridge=self.bridge
        original=base.resolve('patch')
        register_commands(self.ctx)
        self.assertIs(base.resolve('patch'),original)
        sources=[self.window.scene.add(materialize(c)) for c in boundary()]
        messages=[]
        generator=base.resolve('patchparam').fn(SimpleNamespace(echo=messages.append))
        next(generator)
        with self.assertRaises(StopIteration):
            generator.send(sources)
        self.wait_for(lambda:any(m.startswith('Created ') for m in messages))
        self.assertEqual(len(self.window.scene.objects),6)
