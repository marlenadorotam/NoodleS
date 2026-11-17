"""Independent native and symmetric two-rail factories; no geometry monkey patch.

BiRail transports and blends the profile in both rail frames, following our
former sweep2rails_override algorithm. Only its mathematical construction is
reused; scheduling, ownership and publication belong to the common adapter.
"""
import math
import time
from .curves import add,sub,scale,dot,cross
from .splines import integer


def sweep1_shape(profile,rail):
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    return checked(g.sweep1(profile,rail))


def sweep2_shape(profile,rail1,rail2):
    from serpentine3d.core import geometry as g
    from .operation_native import checked
    # An accidentally enabled legacy override must not change this node's
    # meaning. The old plugin saved the genuine native function under this key.
    native=getattr(g,'_sweep2rails_original_native',g.sweep2)
    return checked(native(profile,rail1,rail2))


def unit(v):
    length=math.hypot(*v)
    if not math.isfinite(length) or length<=1e-12:
        raise ValueError('BiRail Sweep has a zero tangent or degenerate local frame.')
    return scale(v,1/length)


def tangent(points,index):
    if index==0:
        return unit(sub(points[1],points[0]))
    if index==len(points)-1:
        return unit(sub(points[-1],points[-2]))
    return unit(sub(points[index+1],points[index-1]))


def frame(tangent,chord,previous=None):
    t=unit(tangent)
    def reject(v):
        return sub(v,scale(t,dot(v,t)))
    candidate=reject(chord)
    if math.hypot(*candidate)<=1e-10 and previous is not None:
        candidate=reject(previous)
    if math.hypot(*candidate)<=1e-10:
        candidate=reject(min(((1,0,0),(0,1,0),(0,0,1)),key=lambda a:abs(dot(a,t))))
    x=unit(candidate)
    if previous is not None and dot(x,previous)<0:
        x=scale(x,-1)
    y=unit(cross(t,x))
    return unit(cross(y,t)),y,t


def oriented(profile,rail1,rail2):
    profile,rail1,rail2=map(list,(profile,rail1,rail2))
    def near(p,rail):
        return min(math.dist(p,rail[0]),math.dist(p,rail[-1]))
    if near(profile[-1],rail1)+near(profile[0],rail2)<near(profile[0],rail1)+near(profile[-1],rail2):
        profile.reverse()
    for endpoint,rail in ((profile[0],rail1),(profile[-1],rail2)):
        if math.dist(endpoint,rail[-1])<math.dist(endpoint,rail[0]):
            rail.reverse()
    gaps=(math.dist(profile[0],rail1[0]),math.dist(profile[-1],rail2[0]))
    if max(gaps)>1e-6:
        raise ValueError(f'BiRail Sweep profile ends must touch the rail ends (tolerance 1e-6). Gaps: {gaps[0]:.6g}, {gaps[1]:.6g}.')
    return profile,rail1,rail2


def sample_open(shape,count,label):
    from serpentine3d.core import geometry as g
    if g.shape_kind(shape)!='curve' or g.is_closed_curve(shape):
        raise ValueError('BiRail Sweep '+label+' must be an open Curve.')
    points=g.sample_curve(shape,count)
    if len(points)!=count or math.dist(points[0],points[-1])<=1e-9:
        raise ValueError('BiRail Sweep '+label+' cannot be sampled as an open Curve.')
    if any(math.dist(a,b)<=1e-12 for a,b in zip(points,points[1:])):
        raise ValueError('BiRail Sweep '+label+' contains collapsed samples.')
    return points


def transported_grid(profile,rail1,rail2):
    """Grid [profile index][rail index], matching the legacy symmetric model."""
    if len(rail1)!=len(rail2):
        raise ValueError('BiRail Sweep requires matching rail sample counts.')
    distances=[math.dist(a,b) for a,b in zip(profile,profile[1:])]
    length=sum(distances)
    if length<=1e-9:
        raise ValueError('BiRail Sweep profile has zero length.')
    fractions=[0.]
    for distance in distances:
        fractions.append(fractions[-1]+distance/length)
    chord=sub(rail2[0],rail1[0])
    frames=[frame(tangent(rail,0),chord) for rail in (rail1,rail2)]
    locals_=[tuple(tuple(dot(sub(p,rail[0]),axis) for axis in axes) for p in profile)
        for rail,axes in zip((rail1,rail2),frames)]
    grid=[[None]*len(rail1) for _ in profile]
    previous=[None,None]
    deadline=time.perf_counter()+.004
    for j in range(len(rail1)):
        chord=sub(rail2[j],rail1[j])
        if math.hypot(*chord)<=1e-9:
            raise ValueError('BiRail Sweep rails meet or collapse at a sampled station.')
        axes=[frame(tangent(rail,j),chord,previous[n]) for n,rail in enumerate((rail1,rail2))]
        previous=[f[0] for f in axes]
        for i,u in enumerate(fractions):
            if i==0:
                p=rail1[j]
            elif i==len(profile)-1:
                p=rail2[j]
            elif j==0:
                p=profile[i]
            else:
                positions=[]
                for rail,f,local in zip((rail1,rail2),axes,locals_):
                    p=rail[j]
                    for axis,value in zip(f,local[i]):
                        p=add(p,scale(axis,value))
                    positions.append(p)
                p=add(scale(positions[0],1-u),scale(positions[1],u))
            grid[i][j]=p
        if time.perf_counter()>=deadline:
            time.sleep(.001)
            deadline=time.perf_counter()+.004
    return grid


def birail_shape(profile,rail1,rail2,rail_samples=33,profile_samples=25):
    from .operation_native import checked
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    # The frozen Serpentine build omits the Python wrapper OCP.Approx.
    from OCP.OCP.Approx import Approx_IsoParametric
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    r=integer(rail_samples,'Rail Samples',4,129)
    p=integer(profile_samples,'Profile Samples',4,129)
    if r*p>10000:
        raise ValueError('BiRail Sweep exceeds the 10000-sample grid limit per part.')
    profile,rail1,rail2=oriented(sample_open(profile,p,'Profile'),sample_open(rail1,r,'Rail 1'),sample_open(rail2,r,'Rail 2'))
    grid=transported_grid(profile,rail1,rail2)
    points=TColgp_Array2OfPnt(1,p,1,r)
    for i in range(p):
        for j in range(r):
            points.SetValue(i+1,j+1,gp_Pnt(*grid[i][j]))
    builder=GeomAPI_PointsToBSplineSurface()
    builder.Interpolate(points,Approx_IsoParametric)
    if not builder.IsDone():
        raise ValueError('OpenCascade could not interpolate the BiRail Sweep.')
    face=BRepBuilderAPI_MakeFace(builder.Surface(),1e-7)
    if not face.IsDone():
        raise ValueError('OpenCascade could not construct the BiRail Sweep face.')
    return checked(face.Face())


def register_commands(ctx):
    from .operation_native import native_job
    req=ctx.requests()
    @ctx.command('sweep1param',mutates=False,label='Sweep 1 Rail')
    def one_rail(c):
        rails=yield req.SelectReq('Select rail curve',kinds=('curve',),min_count=1,max_count=1)
        profiles=yield req.SelectReq('Select profile curve',kinds=('curve',),min_count=1,max_count=1,allow_preselected=False)
        if not rails or not profiles:
            raise ValueError('Sweep 1 Rail needs one rail and one profile.')
        native_job(ctx,c,[rails[0],profiles[0]],lambda shapes:[sweep1_shape(shapes[1],shapes[0])],'Sweep 1 Rail')
    def select():
        rail1=yield req.SelectReq('Select Rail 1',kinds=('curve',),min_count=1,max_count=1)
        rail2=yield req.SelectReq('Select Rail 2',kinds=('curve',),min_count=1,max_count=1,allow_preselected=False)
        profile=yield req.SelectReq('Select profile',kinds=('curve',),min_count=1,max_count=1,allow_preselected=False)
        if not rail1 or not rail2 or not profile:
            raise ValueError('Sweep needs two rails and one profile.')
        return [rail1[0],rail2[0],profile[0]]
    @ctx.command('sweep2param',mutates=False,label='Sweep 2 Rails')
    def native(c):
        sources=yield from select()
        native_job(ctx,c,sources,lambda shapes:[sweep2_shape(shapes[2],shapes[0],shapes[1])],'Sweep 2 Rails')
    @ctx.command('birailsweep',mutates=False,label='BiRail Sweep')
    def birail(c):
        sources=yield from select()
        r=yield req.NumberReq('Rail samples (4..129)',default=33,minimum=4)
        p=yield req.NumberReq('Profile samples (4..129)',default=25,minimum=4)
        native_job(ctx,c,sources,lambda shapes:[birail_shape(shapes[2],shapes[0],shapes[1],r,p)],'BiRail Sweep')
