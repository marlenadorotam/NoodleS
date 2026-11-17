"""Exact OCC checks for point interpolation, boundaries, publication and CLI."""
import builtins
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_operation_native as fixture
from test_operations import state
from test_surfaces import grid
from noodles.backend.operations import evaluate_operation,operation_object_from_outputs
from noodles.backend.curves import circle,line,polyline,PlaneValue
from noodles.backend.datatree import Branch,DataTree
from noodles.backend.arithmetic import VectorValue
from noodles.backend.surface_native import make_surface_from_points,planar_surface_shape,edge_surface_shape
from noodles.backend.scene_curves import materialize


class NativeSurfaceTests(unittest.TestCase):
    setUpClass=classmethod(fixture.NativeOperationTests.setUpClass.__func__)
    setUp=fixture.NativeOperationTests.setUp
    tearDown=fixture.NativeOperationTests.tearDown
    call=fixture.NativeOperationTests.call
    wait_for=fixture.NativeOperationTests.wait_for
    publish=fixture.NativeOperationTests.publish
    model=fixture.NativeOperationTests.model

    def check_interpolation(self,shape,points,u):
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.gp import gp_Pnt
        surface=BRep_Tool.Surface_s(shape)
        bounds=BRepAdaptor_Surface(shape)
        # Both paths use uniform sample parameters. Check exact evaluation at
        # every sample, not mesh proximity or a single central control point.
        v=len(points)//u
        maximum=0
        for j in range(v):
            for i in range(u):
                a=bounds.FirstUParameter()+(bounds.LastUParameter()-bounds.FirstUParameter())*i/(u-1)
                b=bounds.FirstVParameter()+(bounds.LastVParameter()-bounds.FirstVParameter())*j/(v-1)
                maximum=max(maximum,surface.Value(a,b).Distance(gp_Pnt(*points[j*u+i])))
        self.assertLess(maximum,1e-5)
        self.assertTrue(BRepCheck_Analyzer(shape).IsValid())
        self.assertGreater(self.geo.surface_area(shape),1e-9)
        return maximum

    def test_point_interpolation_planes_saddles_steep_rotated_mirrored_irregular_and_sizes(self):
        cases=[(2,2,lambda x,y:(x,y,0)),(5,3,lambda x,y:(x,y,x*y)),
            (4,5,lambda x,y:(x,y,20*(x*x-y*y))),
            (4,3,lambda x,y:(-x,y,x*y)),(3,5,lambda x,y:(y,2*x,3*x*y)),
            (4,4,lambda x,y:(x,.7*y+x*.2,math.sin(x)*math.cos(y))),
            (3,4,lambda x,y:(0,x,y)),(5,4,lambda x,y:(1e6+x,2e6+y,x*y)),
            (10,9,lambda x,y:(x,y,math.sin(x*.4)*math.cos(y*.3))),
            (50,50,lambda x,y:(x,y,.002*x*y))]
        for u,v,fn in cases:
            with self.subTest(u=u,v=v,fn=fn):
                points=[p.xyz for p in grid(u,v,fn)]
                self.check_interpolation(make_surface_from_points(points,u),points,u)

    def test_point_grid_rejects_collinear_duplicate_rows_nan_and_bad_dimensions(self):
        cases=[([(i,0,0) for i in range(9)],3), ([(0,0,0)]*4,2),
            ([(0,0,0),(1,0,0),(0,0,0),(1,0,0)],2),
            ([(0,0,0),(1,0,0),(0,1,float('nan')),(1,1,0)],2),
            ([p.xyz for p in grid()],5),([p.xyz for p in grid()],2.5)]
        for points,u in cases:
            with self.subTest(points=points[:4],u=u),self.assertRaises(Exception):
                make_surface_from_points(points,u)

    def test_periodic_point_rows_cap_into_one_valid_solid(self):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.gp import gp_Pnt

        u, v = 200, 11
        def sample(i, j):
            a, r = math.tau*i/u, 10. - .2*j
            return r*math.cos(a), r*math.sin(a), .4*j

        points = grid(u, v, sample)
        rows = DataTree(tuple(Branch((0, j), points[j*u:(j+1)*u]) for j in range(v)))
        parameters = state('surface_from_points', tree_modes={'P': 'flatten'},
                           parameters={'periodic_u': True})
        output = evaluate_operation('surface_from_points', parameters, {'P': rows})
        source = self.publish(operation_object_from_outputs(parameters, output).to_wire())
        face, = self.geo.faces_of(source.shape)
        surface = BRepAdaptor_Surface(face)
        self.assertTrue(surface.IsUPeriodic())
        self.assertFalse(surface.IsVPeriodic())
        u0, u1 = surface.FirstUParameter(), surface.LastUParameter()
        v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
        for j in range(v):
            height = v0+(v1-v0)*j/(v-1)
            self.assertLess(surface.Value(u0, height).Distance(surface.Value(u1, height)), 1e-7)
            for i in range(u):
                self.assertLess(surface.Value(u0+(u1-u0)*i/u, height).Distance(gp_Pnt(*sample(i, j))), 1e-7)

        parameters = state('cap_holes', node_uuid=str(uuid4()))
        capped = self.publish(self.model('cap_holes', {'B': output['G']}, parameters))
        self.assertEqual(self.geo.shape_kind(self.geo.unwrap_compound(capped.shape)), 'solid')
        self.assertEqual(len(self.geo.faces_of(capped.shape)), 3)
        self.assertTrue(BRepCheck_Analyzer(capped.shape).IsValid())
        expected_volume = math.pi*4*(100+80+64)/3
        self.assertAlmostEqual(self.geo.volume(capped.shape), expected_volume, delta=.01)
        self.assertEqual(set(self.window.scene.objects), {source.id, capped.id})
        self.assertEqual(len(self.geo.faces_of(self.window.scene.get(source.id).shape)), 1)

        duplicated = [point.xyz for row in rows.branches for point in (*row.items, row.items[0])]
        with self.assertRaisesRegex(ValueError, 'first point only once'):
            make_surface_from_points(duplicated, u+1, periodic_u=True)

    def test_saddle_publishes_without_the_ocp_approx_python_wrapper(self):
        points = grid(11, 17, lambda x, y: (x, y, x*x - y*y))
        model = self.model('surface_from_points', {'P': points, 'U': 11})
        real_import = builtins.__import__

        def without_wrapper(name, *args, **kwargs):
            if name == 'OCP.Approx':
                raise ModuleNotFoundError("No module named 'OCP.Approx'", name=name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', without_wrapper):
            owner = self.publish(model)
        self.assertEqual(len(self.window.scene.objects), 1)
        self.assertTrue(owner.mesh_ready)
        face, = self.geo.faces_of(owner.shape)
        self.check_interpolation(face, [point.xyz for point in points], 11)

    def test_planar_holes_nested_islands_disjoint_and_invalid_boundaries(self):
        curves=[circle(str(i),(0,0,0),r,PlaneValue()) for i,r in enumerate((10,5,2))]
        shapes=[materialize(c) for c in curves]
        for order in (shapes,list(reversed(shapes))):
            result=planar_surface_shape(order)
            self.assertEqual(len(self.geo.faces_of(result)),2)
            self.assertAlmostEqual(self.geo.surface_area(result),math.pi*(100-25+4),delta=1e-5)
        other=materialize(circle('disjoint',(30,0,0),2,PlaneValue()))
        result=planar_surface_shape([shapes[0],other])
        self.assertAlmostEqual(self.geo.surface_area(result),math.pi*104,delta=1e-5)
        for boundaries in ([materialize(line('open',(0,0,0),(1,0,0)))],
            [shapes[0],materialize(circle('overlap',(10,0,0),8,PlaneValue()))],
            [shapes[0],shapes[0]],
            [shapes[0],materialize(circle('off',(0,0,1),2,PlaneValue()))],
            [materialize(polyline('cross',((0,0,0),(2,2,0),(0,2,0),(2,0,0)),True))],
            [materialize(polyline('bent',((0,0,0),(2,0,0),(2,2,1),(0,2,0)),True))]):
            with self.subTest(count=len(boundaries)),self.assertRaises(Exception):
                planar_surface_shape(boundaries)

    def test_edge_surface_two_three_four_reordered_reversed_and_bad_loops(self):
        a,b,c,d=(0,0,0),(5,0,0),(5,4,1),(0,4,0)
        cases=[[(a,b),(d,c)],[(a,b),(b,c),(c,a)],[(a,b),(d,c),(d,a),(c,b)]]
        for boundaries in cases:
            shapes=[materialize(line(str(i),start,end)) for i,(start,end) in enumerate(boundaries)]
            result=edge_surface_shape(shapes)
            self.assertEqual(len(self.geo.faces_of(result)),1)
            self.assertGreater(self.geo.surface_area(result),1)
        for boundaries in ([line('a',a,b)], [line('a',a,b),line('b',c,d),line('c',(10,0,0),(11,0,0))],
            [polyline('multi',(a,b,c),False),line('a',d,c)]):
            with self.assertRaises(Exception):
                edge_surface_shape([materialize(v) for v in boundaries])

    def test_common_owner_measurements_extrude_and_failure_preserves_scene(self):
        outer=circle('outer',(0,0,0),10,PlaneValue())
        inner=circle('inner',(0,0,0),3,PlaneValue())
        data={'C':[outer,inner]}
        model=self.model('planar_surface',data)
        owner=self.publish(model)
        job=next(reversed(self.bridge.geometry.jobs.values()))
        details=job['curve_details']
        out=evaluate_operation('planar_surface',{**state('planar_surface'),'curve_details':details},data)
        self.assertEqual(out['EC'].values(),(2,))
        self.assertAlmostEqual(abs(out['N'].values()[0].xyz[2]),1)
        base=out['G'].values()[0]
        solid=self.publish(self.model('extrude',{'G':base,'V':VectorValue((0,0,7))}))
        self.assertEqual(solid.id,owner.id)
        self.assertAlmostEqual(self.geo.volume(solid.shape),math.pi*91*7,delta=1e-4)
        points=DataTree((Branch((4,),tuple(grid())),Branch((8,),tuple(grid()))))
        model=self.model('surface_from_points',{'P':points,'U':4})
        owner=self.publish(model)
        self.assertEqual(len(self.window.scene.objects),1)
        self.assertEqual(len(self.geo.faces_of(owner.shape)),2)
        self.assertTrue(owner.mesh_ready)
        shape=owner._shape
        bad=self.model('surface_from_points',{'P':grid(3,3,lambda x,y:(x+y,0,0)),'U':3})
        request=self.call('geometry.prepare',{'model':bad})
        self.wait_for(lambda:self.bridge.geometry.jobs[request['job_id']]['state']!='preparing')
        self.assertEqual(self.call('geometry.job',request)['state'],'error')
        self.assertIs(self.window.scene.get(owner.id)._shape,shape)

    def test_native_surface_commands_share_pool_and_preserve_builtins(self):
        from serpentine3d.commands import base,surfaces,surfaces2
        from noodles.backend.surface_native import register_commands
        self.window._noodles_bridge=self.bridge
        old=[base.resolve(n) for n in ('planarsrf','edgesrf')]
        register_commands(self.ctx)
        self.assertEqual(old,[base.resolve(n) for n in ('planarsrf','edgesrf')])
        boundary=self.window.scene.add(materialize(circle('c',(0,0,0),3,PlaneValue())))
        edges=[self.window.scene.add(materialize(line(str(i),(0,y,0),(3,y,0)))) for i,y in enumerate((0,4))]
        points=[self.window.scene.add(self.geo.make_point(p.xyz)) for p in grid(3,3)]
        ring_points = [self.window.scene.add(self.geo.make_point(p.xyz)) for p in grid(8, 3, lambda i, j:
            (3*math.cos(math.tau*i/8), 3*math.sin(math.tau*i/8), j))]
        for name,values in [('planarsurfaceparam',[[boundary]]),('edgesurfaceparam',[edges]),
                            ('surfacefrompoints',[points,3]),('surfacefrompointsperiodic',[ring_points,8])]:
            messages=[]
            generator=base.resolve(name).fn(SimpleNamespace(echo=messages.append))
            next(generator)
            before=len(self.window.scene.objects)
            for value in values:
                try:
                    generator.send(value)
                except StopIteration:
                    break
            self.wait_for(lambda:any(s.startswith('Created ') for s in messages))
            self.assertEqual(len(self.window.scene.objects),before+1)
            self.assertFalse(base.resolve(name).mutates)
