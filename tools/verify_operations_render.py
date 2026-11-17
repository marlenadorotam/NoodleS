"""Real isolated Serpentine viewport + operation publisher responsiveness probe."""
from pathlib import Path
import sys
import time
import json
import uuid
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from benchmark_grids import qt_runtime,pump,Probe


def main():
    surface_cases='--surfaces' in sys.argv
    sweep_cases='--sweeps' in sys.argv
    app=qt_runtime(True)
    if '--phases' in sys.argv:
        import threading
        from functools import wraps
        from serpentine3d.core import geometry,tessellate
        def wrap(module,name):
            original=getattr(module,name)
            depth=threading.local()
            @wraps(original)
            def measured(*args,**kwargs):
                if getattr(depth,'active',False):
                    return original(*args,**kwargs)
                depth.active=True
                start=time.perf_counter()
                try:
                    return original(*args,**kwargs)
                finally:
                    depth.active=False
                    elapsed=(time.perf_counter()-start)*1000
                    if elapsed>20:
                        print(json.dumps({'phase':name,'thread':threading.current_thread().name,'ms':round(elapsed,2)}),file=sys.stderr,flush=True)
            setattr(module,name,measured)
        for name in ('bbox','shape_kind','make_compound','surface_area'):
            wrap(geometry,name)
        for name in ('default_deflection','tessellate','BRepMesh_IncrementalMesh','_face_mesh','_edge_polyline'):
            wrap(tessellate,name)
    from PySide6 import QtCore,QtWidgets
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.core.history import History
    from serpentine3d.ui.viewport import Viewport
    from noodles.backend.scene_points import ParametricSceneAdapter
    from noodles.backend.viewport_acceleration import install
    from noodles.backend.operations import normalize_operation_state,evaluate_operation,operation_object_from_outputs
    from noodles.backend.curves import circle,line,PlaneValue
    from noodles.backend.arithmetic import VectorValue
    from noodles.backend.point import PointValue
    from noodles.backend.datatree import Branch,DataTree
    window=QtWidgets.QMainWindow()
    window.setWindowTitle('NoodleS operations — isolated render test')
    window.scene=Scene()
    window.selection=SelectionManager(window.scene)
    window.history=History(window.scene)
    window.ctx=SimpleNamespace(current_path=None)
    viewport=Viewport(window.scene,window.selection)
    window.viewport=viewport
    window.setCentralWidget(viewport)
    window.resize(1100,720)
    install(window)
    adapter=ParametricSceneAdapter(SimpleNamespace(window=window,scene=window.scene))
    render=QtCore.QTimer(window)
    render.setInterval(16)
    render.timeout.connect(viewport.update)
    render.start()
    window.show()
    pump(app,.3)
    probe=Probe(window)
    records=[]
    cases=[('extrude',{'G':circle('p',(0,0,0),5,PlaneValue())}),
           ('revolve',{'C':line('p',(5,0,0),(5,0,20))}),
           ('loft',{'C':[circle(str(i),(0,0,i*10),5+i,PlaneValue()) for i in range(3)]}),
           ('extrude',{'G':circle('p',(0,0,0),5,PlaneValue()),'V':[VectorValue((0,0,i)) for i in range(1,201)]})]
    if surface_cases:
        def grid(u,v,z=0):
            return tuple(PointValue(str(j*u+i),(i,j,z+.02*i*j)) for j in range(v) for i in range(u))
        cases=[('planar_surface',{'C':[circle('outer',(0,0,0),10,PlaneValue()),circle('hole',(0,0,0),4,PlaneValue())]}),
            ('edge_surface',{'C':[line('a',(0,0,0),(5,0,0)),line('b',(0,5,0),(5,5,2))]}),
            ('surface_from_points',{'P':grid(50,50),'U':50}),
            ('surface_from_points',{'P':DataTree(tuple(Branch((i,),grid(5,5,i*4)) for i in range(200))),'U':5})]
    if sweep_cases:
        from noodles.backend.curves import arc
        simple={'R1':line('r1',(0,0,0),(0,0,10)),'R2':line('r2',(5,0,0),(10,0,10)),
            'P':line('p',(0,0,0),(5,0,0))}
        curved={'R1':arc('a',(0,0,0),(0,-4,5),(0,0,10)),
            'R2':arc('b',(5,0,0),(9,3,5),(12,0,10)),'P':arc('p',(0,0,0),(2.5,-2,0),(5,0,0))}
        cases=[('sweep2',simple),('birail_sweep',simple),('birail_sweep',curved),
            ('birail_sweep',{**simple,'R2':[line(str(i),(5,0,0),(5+i*.03,0,10)) for i in range(200)]})]
    if '--sweep1' in sys.argv:
        from noodles.backend.curves import arc
        simple={'R':line('r',(0,0,0),(0,0,10)),'P':line('p',(0,0,0),(5,0,0))}
        cases=[('sweep1',simple),('sweep1',{'R':arc('r',(0,0,0),(5,0,5),(10,0,0)),
            'P':circle('p',(0,0,0),1,PlaneValue())}),
            ('sweep1',{**simple,'P':[line(str(i),(0,0,0),(1+i*.01,0,0)) for i in range(200)]})]
    if '--patch' in sys.argv:
        from noodles.backend.curves import polyline
        def outline(z,offset=0):
            return polyline(str(z)+':'+str(offset),((offset,0,0),(offset+5,0,0),(offset+6,3,z),
                (offset+3,6,0),(offset,4,0)),True)
        cases=[('patch',{'C':outline(0)}),('patch',{'C':outline(3)}),
            ('patch',{'C':DataTree(tuple(Branch((i,),(outline(1+i*.01,i*8),)) for i in range(50)))})]
    for op,inputs in cases:
        state=normalize_operation_state(op,{'project_uuid':str(uuid.uuid4()),'node_uuid':str(uuid.uuid4())})
        outputs=evaluate_operation(op,state,inputs)
        model=operation_object_from_outputs(state,outputs)
        window.scene.clear()
        window.history=History(window.scene)
        pump(app,.02)
        probe.reset()
        start=time.perf_counter()
        job=adapter.submit({'model':model.to_wire(),'name':op})
        while adapter.jobs[job['job_id']]['state']=='preparing' and time.perf_counter()-start<40:
            app.processEvents()
            time.sleep(.001)
        elapsed=(time.perf_counter()-start)*1000
        result=adapter.jobs[job['job_id']]
        assert result['state']=='complete',result.get('error')
        viewport.zoom_extents()
        pump(app,.1)
        assert len(window.scene.objects)==1
        assert not viewport.paint_failed
        records.append({'operation':op,'parts':model.parts.count,'publish_ms':round(elapsed,2),**probe.report()})
    print(json.dumps(records),flush=True)
    adapter.stop()
    window.scene.clear()
    window.close()


if __name__=='__main__':
    main()
