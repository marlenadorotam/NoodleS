"""Native grid factories/commands using the universal OCC worker and publisher."""
import uuid
import math

from .grids import GridValue, GRID_SPECS
from .grid_topology import topology
from .curves import PlaneValue
from .datatree import Branch, DataTree
from .parametric import ParametricObject


def materialize(value):
    from serpentine3d.core import geometry as g
    vertices,edges,_,centres=topology(value.kind,*value.extents)
    # No scene.add here. These are native subshapes of one deferred owner.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex,BRepBuilderAPI_MakeEdge
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Pnt
    import time
    parts=[]
    deadline=time.perf_counter()+.003
    def checkpoint():
        nonlocal deadline
        if time.perf_counter()>=deadline:
            time.sleep(.001)
            deadline=time.perf_counter()+.003
    sx,sy=value.spacing if len(value.spacing)==2 else (value.spacing[0],)*2
    points={}
    for records in (vertices,centres):
        for role,(xy,_) in records.items():
            point=value.frame.at(xy[0]*sx,xy[1]*sy)
            if records is vertices:
                points[role]=point
            parts.append(BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex())
            checkpoint()
    for role,(a,b,_,is_arc) in edges.items():
        if is_arc:
            _,r,index=role.split(':')
            radius=int(r)*sx
            angle=math.tau*(int(index)+.5)/value.extents[1]
            midpoint=value.frame.at(radius*math.cos(angle),radius*math.sin(angle))
            arc=GC_MakeArcOfCircle(gp_Pnt(*points[a]),gp_Pnt(*midpoint),gp_Pnt(*points[b]))
            if not arc.IsDone():
                raise ValueError('OpenCascade could not construct a grid arc.')
            parts.append(BRepBuilderAPI_MakeEdge(arc.Value()).Edge())
        else:
            parts.append(BRepBuilderAPI_MakeEdge(gp_Pnt(*points[a]),gp_Pnt(*points[b])).Edge())
        checkpoint()
    return g.make_compound(parts)


def register_commands(ctx, kinds=None):
    """Commands work without the editor, through the installed common publisher."""
    req=ctx.requests()
    def command(kind):
        def run(c):
            window=ctx.window
            bridge=getattr(window,'_noodles_bridge',None)
            if bridge is None:
                c.echo('Load NoodleSBridge with the plugins command before creating a grid.')
                return
            spec=GRID_SPECS[kind]
            name=yield req.TextReq('Grid name',default=spec['name'])
            origin=yield req.PointReq('Grid origin',default=tuple(map(float,c.cplane.origin)))
            frame=PlaneValue(tuple(map(float,origin)),tuple(map(float,c.cplane.xdir)),tuple(map(float,c.cplane.normal)))
            spacing=[]
            for label in (('Cell Size X','Cell Size Y') if kind=='grid_rectangle' else ('Ring Spacing',) if kind=='grid_radial' else ('Edge Size',)):
                spacing.append((yield req.LengthReq(label,default=10.,minimum=1e-7)))
            extents=[]
            for label,default,minimum in (('Radial Cells',4,1),('Polar Cells',8,3)) if kind=='grid_radial' else (('Cells X',4,1),('Cells Y',3,1)):
                extents.append((yield req.IntReq(label,default=default,minimum=minimum)))
            try:
                value=GridValue('grid',kind,frame,tuple(spacing),tuple(extents))
                model=ParametricObject(str(uuid.uuid4()),str(uuid.uuid4()),DataTree((Branch((0,),(value,)),)),kind='grids')
                job=bridge.geometry.submit({'model':model.to_wire(),'name':name})
            except (ValueError,TypeError,OverflowError) as exc:
                c.echo(str(exc))
                return
            c.echo('Preparing '+spec['name']+'…')
            # A completion notification, not a separate geometry scheduler.
            from PySide6.QtCore import QTimer
            timer=QTimer(window)
            timer.setInterval(40)
            def completed():
                result=bridge.geometry.jobs.get(job['job_id'],{})
                if result.get('state')=='preparing':
                    return
                timer.stop()
                timer.deleteLater()
                if result.get('state')=='complete':
                    c.echo('Created '+str(name)+' as one ParametricObject.')
                else:
                    c.echo(result.get('error') or 'Grid creation was cancelled.')
            timer.timeout.connect(completed)
            timer.start()
        return run
    aliases={'grid_rectangle':('gridrectangle','rectgrid'), 'grid_triangle':('gridtriangle','trigrid'),
             'grid_hexagon':('gridhexagon','hexgrid'), 'grid_radial':('gridradial','radgrid')}
    for kind in kinds or GRID_SPECS:
        name,alias=aliases[kind]
        ctx.command(name,aliases=(alias,),label=GRID_SPECS[kind]['name'],mutates=False)(command(kind))
