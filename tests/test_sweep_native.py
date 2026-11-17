"""Real OCC distinction, BiRail boundary accuracy, common lifecycle and native CLI."""
import builtins
import math
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_operation_native as fixture
from test_operations import state
from test_sweeps import setup_inputs
from noodles.backend.operations import evaluate_operation
from noodles.backend.curves import line,arc,circle,PlaneValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.scene_curves import materialize
from noodles.backend.sweep_native import sweep2_shape,birail_shape,register_commands


class NativeSweepTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeOperationTests.setUpClass.__func__)
    setUp=fixture.NativeOperationTests.setUp
    tearDown=fixture.NativeOperationTests.tearDown
    call=fixture.NativeOperationTests.call
    wait_for=fixture.NativeOperationTests.wait_for
    publish=fixture.NativeOperationTests.publish
    model=fixture.NativeOperationTests.model

    def shapes(self,data=None):
        data=data or setup_inputs()
        return tuple(materialize(data[p]) for p in ('P','R1','R2'))

    def surface(self,shape):
        from OCP.BRep import BRep_Tool
        from OCP.BRepTools import BRepTools
        face=self.geo.faces_of(shape)[0]
        return BRep_Tool.Surface_s(face),BRepTools.UVBounds_s(face)

    def test_native_matches_serpentine_and_birail_reaches_the_second_rail(self):
        shapes=self.shapes()
        native=sweep2_shape(*shapes)
        baseline=self.geo.sweep2(*shapes)
        self.assertAlmostEqual(self.geo.surface_area(native),self.geo.surface_area(baseline),delta=1e-6)
        self.assertAlmostEqual(self.geo.surface_area(native),50,delta=1e-6)
        self.assertAlmostEqual(self.geo.bbox(native)[1][0],5,delta=1e-5)
        real_import = builtins.__import__

        def frozen_import(name, *args, **kwargs):
            if name == 'OCP.Approx':
                raise ModuleNotFoundError("No module named 'OCP.Approx'", name=name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', frozen_import):
            birail = birail_shape(*shapes)
        self.assertGreaterEqual(self.geo.bbox(birail)[1][0],10-1e-5)
        from OCP.gp import gp_Pnt
        surface,(u0,u1,v0,v1)=self.surface(birail)
        for t in (0,.13,.5,.87,1):
            v=v0+t*(v1-v0)
            self.assertLess(surface.Value(u0,v).Distance(gp_Pnt(0,0,t*10)),1e-5)
            self.assertLess(surface.Value(u1,v).Distance(gp_Pnt(5+5*t,0,t*10)),1e-5)
        # A legacy monkey patch cannot hijack the explicitly native variant.
        with patch.object(self.geo,'_sweep2rails_original_native',self.geo.sweep2,create=True),patch.object(self.geo,'sweep2',side_effect=AssertionError('legacy override')):
            self.assertAlmostEqual(self.geo.surface_area(sweep2_shape(*shapes)),50,delta=1e-6)

    def test_birail_reversals_swap_and_translation_preserve_shape_and_sources(self):
        data=setup_inputs()
        profile,r1,r2=self.shapes(data)
        baseline=birail_shape(profile,r1,r2)
        expected=self.geo.surface_area(baseline)
        curves=[profile,r1,r2]
        before=[self.geo.sample_curve(s,9) for s in curves]
        for mask in range(8):
            # Reverse the underlying curve parameters, not just TopAbs
            # orientation (BRepAdaptor may sample the latter identically).
            values=[data[key] for key in ('P','R1','R2')]
            shapes=[materialize(line(v.key,*reversed(v.points))) if mask&(1<<i) else s
                for i,(v,s) in enumerate(zip(values,curves))]
            result=birail_shape(*shapes)
            self.assertAlmostEqual(self.geo.surface_area(result),expected,delta=1e-5)
        swapped=birail_shape(profile,r2,r1)
        self.assertAlmostEqual(self.geo.surface_area(swapped),expected,delta=1e-5)
        moved=birail_shape(*(self.geo.translate(s,(100,-20,30)) for s in curves))
        self.assertAlmostEqual(self.geo.surface_area(moved),expected,delta=1e-5)
        self.assertEqual([self.geo.sample_curve(s,9) for s in curves],before)

    def test_curved_rails_and_profile_interpolate_every_sample_and_refine_between_samples(self):
        data={'R1':arc('a',(0,0,0),(0,-4,5),(0,0,10)),
            'R2':arc('b',(5,0,0),(9,3,5),(12,0,10)),
            'P':arc('p',(0,0,0),(2.5,-2,0),(5,0,0))}
        profile,r1,r2=self.shapes(data)
        owner=self.publish(self.model('birail_sweep',data))
        self.assertTrue(owner.mesh_ready)
        job=next(reversed(self.bridge.geometry.jobs.values()))
        out=evaluate_operation('birail_sweep',{**state('birail_sweep'),'curve_details':job['curve_details']},data)
        self.assertEqual(out['K'].values(),('surface',))
        from OCP.gp import gp_Pnt
        low=birail_shape(profile,r1,r2,9,9)
        high=birail_shape(profile,r1,r2,65,49)
        for shape,count,pcount in ((low,9,9),(high,65,49)):
            surface,(u0,u1,v0,v1)=self.surface(shape)
            for u,rail in ((u0,r1),(u1,r2)):
                for j,point in enumerate(self.geo.sample_curve(rail,count)):
                    v=v0+(v1-v0)*j/(count-1)
                    self.assertLess(surface.Value(u,v).Distance(gp_Pnt(*point)),1e-6)
            for i,point in enumerate(self.geo.sample_curve(profile,pcount)):
                u=u0+(u1-u0)*i/(pcount-1)
                self.assertLess(surface.Value(u,v0).Distance(gp_Pnt(*point)),1e-6)
        def error(shape):
            surface,(u0,u1,v0,v1)=self.surface(shape)
            return max(surface.Value(u,v0+(v1-v0)*j/256).Distance(gp_Pnt(*point))
                for u,rail in ((u0,r1),(u1,r2)) for j,point in enumerate(self.geo.sample_curve(rail,257)))
        self.assertLess(error(high),error(low))
        self.assertLess(error(high),1e-4)

    def test_closed_disconnected_collapsed_and_bad_resolution_are_errors(self):
        profile,r1,r2=self.shapes()
        badcases=[(materialize(circle('c',(0,0,0),2,PlaneValue())),r1,r2),
            (profile,r1,materialize(circle('c',(0,0,0),2,PlaneValue()))),
            (self.geo.translate(profile,(0,1,0)),r1,r2),
            (profile,r1,materialize(line('meet',(5,0,0),(0,0,10)))),
            (profile,r1,r1)]
        for shapes in badcases:
            with self.assertRaises(ValueError):
                birail_shape(*shapes)
        for r,p in ((3,25),(33,True),(129,129)):
            with self.assertRaises(ValueError):
                birail_shape(profile,r1,r2,r,p)

    def test_two_hundred_results_one_owner_worker_cache_and_attribute_lifecycle(self):
        from noodles.backend.sweep_native import birail_shape as factory
        data=setup_inputs()
        data['R2']=[line('r'+str(i),(5,0,0),(5+i*.03,0,10)) for i in range(200)]
        threads=[]
        def build(*args):
            threads.append(threading.get_ident())
            return factory(*args)
        with patch('noodles.backend.sweep_native.birail_shape',side_effect=build) as factory_mock:
            owner=self.publish(self.model('birail_sweep',data))
            self.assertEqual(factory_mock.call_count,200)
        self.assertTrue(all(t!=threading.get_ident() for t in threads))
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertTrue(owner.mesh_ready)
        data['R2'][70]=line('r70',(5,0,0),(8,0,10))
        with patch('noodles.backend.sweep_native.birail_shape',wraps=factory) as factory_mock:
            self.publish(self.model('birail_sweep',data))
            self.assertEqual(factory_mock.call_count,1)
        layer=self.window.scene.layers.create('Sweep layer')
        self.window.scene.update(owner.id,name='BiRail assembly',layer_id=layer.id,color=None)
        model=self.model('birail_sweep',data)
        shape=self.window.scene.get(owner.id)._shape
        self.call('geometry.remove',{k:model[k] for k in ('project_uuid','node_uuid')})
        restored=self.publish(model)
        self.assertEqual(restored.id,owner.id)
        self.assertEqual(restored.name,'BiRail assembly')
        self.assertEqual(restored.layer_id,layer.id)
        self.assertIsNone(restored.color)
        self.assertIs(restored._shape,shape)

    def test_invalid_job_preserves_previous_owner_and_native_sources(self):
        data=setup_inputs()
        native_sources=[self.window.scene.add(s) for s in self.shapes(data)]
        old_shapes=[s._shape for s in native_sources]
        owner=self.publish(self.model('birail_sweep',data))
        shape=owner._shape
        data['P']=line('disconnected',(0,1,0),(5,1,0))
        request=self.call('geometry.prepare',{'model':self.model('birail_sweep',data)})
        self.wait_for(lambda:self.bridge.geometry.jobs[request['job_id']]['state']!='preparing')
        self.assertEqual(self.call('geometry.job',request)['state'],'error')
        self.assertIs(self.window.scene.get(owner.id)._shape,shape)
        self.assertEqual([s._shape for s in native_sources],old_shapes)

    def test_exact_native_bounds_are_prepared_before_gui_reads_them(self):
        data=setup_inputs()
        data['R2']=[data['R2'],line('r3',(5,0,0),(8,2,12))]
        owner=self.publish(self.model('birail_sweep',data))
        expected=self.geo.bbox(owner.shape)
        self.assertIs(owner._bounds[0],owner._shape)
        for actual,wanted in zip(owner._bounds[1],expected):
            for a,b in zip(actual,wanted):
                self.assertAlmostEqual(a,b,delta=1e-7)
        with patch.object(self.geo,'bbox',side_effect=AssertionError('OCC bounds recomputed on GUI')):
            self.assertEqual(owner.bbox(),owner._bounds[1])

    def test_native_commands_preserve_sweep2_and_share_factories(self):
        from serpentine3d.commands import base,surfaces
        self.window._noodles_bridge=self.bridge
        original=base.resolve('sweep2')
        register_commands(self.ctx)
        self.assertIs(base.resolve('sweep2'),original)
        profile,r1,r2=[self.window.scene.add(s) for s in self.shapes()]
        for command,args in (('sweep2param',[[r1],[r2],[profile]]),('birailsweep',[[r1],[r2],[profile],33,25])):
            messages=[]
            generator=base.resolve(command).fn(SimpleNamespace(echo=messages.append))
            next(generator)
            before=len(self.window.scene.objects)
            for value in args:
                try:
                    generator.send(value)
                except StopIteration:
                    break
            self.wait_for(lambda:any(m.startswith('Created ') for m in messages))
            self.assertEqual(len(self.window.scene.objects),before+1)
            self.assertFalse(base.resolve(command).mutates)
