"""Isolated grid benchmark. Never connects to the user's bridge or CAD scene.

Run with .venv/Scripts/python.exe tools/benchmark_grids.py --mode data|ui|native
The native mode uses the reference Serpentine viewport and real OCC/display mesh.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['QT_PREFERRED_BINDING']='PySide6'

from noodles.backend.grids import evaluate_grid,normalize_grid_state,grid_object_from_outputs

SIZES={'grid_rectangle':[(10,10),(30,30),(50,50),(70,70)],
       'grid_triangle':[(10,10),(30,30),(50,50),(57,57)],
       'grid_hexagon':[(10,10),(30,30),(50,50),(57,57)],
       'grid_radial':[(10,20),(20,40),(40,80),(50,100)]}


def inputs(op,extent):
    return dict(zip(('Er','Ep') if op=='grid_radial' else ('Ex','Ey'),extent))


def state(op):
    return normalize_grid_state(op,{'project_uuid':str(uuid.uuid4()),'node_uuid':str(uuid.uuid4())})


def emit(record):
    print(json.dumps(record),flush=True)


def data_benchmark():
    for op,sizes in SIZES.items():
        params=state(op)
        for extent in sizes:
            timings=[]
            for i in range(4):
                start=time.perf_counter()
                out=evaluate_grid(op,params,inputs(op,extent))
                timings.append((time.perf_counter()-start)*1000)
            value=out['G'].values()[0]
            emit(dict(mode='data',kind=op,size=extent,cells=value.counts[0],points=value.counts[1],edges=value.counts[2],
                      cold_ms=round(timings[0],2),warm_ms=round(statistics.median(timings[1:]),2),
                      wire_bytes=len(json.dumps(grid_object_from_outputs(params,out).to_wire()))))


def qt_runtime(native=False):
    if native:
        configured_source = os.environ.get("NOODLES_TEST_SERPENTINE_SOURCE")
        if not configured_source:
            raise SystemExit("Set NOODLES_TEST_SERPENTINE_SOURCE as described in CONTRIBUTING.md.")
        source = Path(configured_source).resolve()
        if not (source / "serpentine3d" / "__init__.py").is_file():
            raise SystemExit("NOODLES_TEST_SERPENTINE_SOURCE must point to the Serpentine3D source root.")
        sys.path.insert(0, str(source))
    from PySide6 import QtWidgets
    if native:
        from serpentine3d.utils.glsetup import set_default_gl_format
        set_default_gl_format()
    return QtWidgets.QApplication([])


class Probe:
    def __init__(self,parent):
        from PySide6 import QtCore
        self.gaps=[]
        self.last=time.perf_counter()
        self.timer=QtCore.QTimer(parent)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.setInterval(5)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        now=time.perf_counter()
        self.gaps.append((now-self.last)*1000)
        self.last=now

    def reset(self):
        self.gaps=[]
        self.last=time.perf_counter()

    def report(self):
        return {'qt_max_gap_ms':round(max(self.gaps,default=0),2),
                'qt_ticks':len(self.gaps),'qt_gaps_over_50ms':sum(g>50 for g in self.gaps)}


def pump(app,seconds):
    deadline=time.perf_counter()+seconds
    while time.perf_counter()<deadline:
        app.processEvents()
        time.sleep(.001)


def ui_benchmark():
    app=qt_runtime()
    from noodles.window import MainWindow
    from noodles.backend.grids import GRID_SPECS
    window=MainWindow()
    window.setWindowTitle('NoodleS — isolated grid benchmark')
    window.show()
    probe=Probe(window)
    pump(app,.2)
    for op,sizes in SIZES.items():
        node=window.add_node('NoodleS.Geometry.'+GRID_SPECS[op]['class'])
        pump(app,.1)
        for extent in sizes:
            probe.reset()
            start=time.perf_counter()
            parameters=dict(node.get_property('parameters'),**inputs(op,extent))
            node.set_property('parameters',parameters)
            app.processEvents()
            duration=(time.perf_counter()-start)*1000
            while window._graph_worker and (window._graph_worker.running or window._graph_worker.pending is not None):
                app.processEvents()
                time.sleep(.001)
            pump(app,.02)
            emit(dict(mode='ui',kind=op,size=extent,change_ms=round(duration,2),evaluation_ms=round((time.perf_counter()-start)*1000-20,2),**probe.report()))
        window.graph.delete_node(node)
        pump(app,.05)
    window.graph.undo_stack().setClean()
    window.close()


def native_benchmark():
    import cProfile
    profile=cProfile.Profile()
    app=qt_runtime(True)
    from PySide6 import QtCore,QtWidgets
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.core.history import History
    from serpentine3d.ui.viewport import Viewport
    from noodles.backend.scene_points import ParametricSceneAdapter
    if os.environ.get('GRID_PHASE'):
        import threading
        from serpentine3d.core import geometry,tessellate
        from functools import wraps
        def wrap(module,name):
            original=getattr(module,name)
            depth=threading.local()
            @wraps(original)
            def measured(*args,**kw):
                if getattr(depth,'active',False):
                    return original(*args,**kw)
                depth.active=True
                start=time.perf_counter()
                try:
                    return original(*args,**kw)
                finally:
                    depth.active=False
                    duration=(time.perf_counter()-start)*1000
                    if duration>15:
                        emit(dict(phase=name,thread=threading.current_thread().name,ms=round(duration,2)))
            setattr(module,name,measured)
        for name in ('make_compound','shape_kind','free_points'):
            wrap(geometry,name)
        for name in ('tessellate','BRepMesh_IncrementalMesh'):
            wrap(tessellate,name)
    from types import SimpleNamespace
    window=QtWidgets.QMainWindow()
    window.setWindowTitle('Serpentine — isolated grid benchmark')
    window.scene=Scene()
    window.selection=SelectionManager(window.scene)
    window.history=History(window.scene)
    window.ctx=SimpleNamespace(current_path=None)
    viewport=Viewport(window.scene,window.selection)
    window.viewport=viewport
    from noodles.backend.viewport_acceleration import install
    install(window)
    if os.environ.get('GRID_PHASE'):
        for name in ('_sync_gpu','_draw_objects','_draw_grid','_refresh_camera_bounds','_draw_point_markers','_draw_control_points','_draw_combs','_draw_direction_arrows','_draw_clip_normals','_paint_dots','_reset_gl_state','_draw_image_planes','_draw_pending','_draw_axis_triad','_draw_frame_guides','_draw_selection_box','_update_gumball_readout','_update_draw_readout','note_view_change','_use','_set_line_uniforms','_line_width'):
            wrap(viewport,name)
        wrap(viewport.gumball,'paint')
    window.setCentralWidget(viewport)
    window.resize(1100,720)
    ctx=SimpleNamespace(scene=window.scene,window=window)
    adapter=ParametricSceneAdapter(ctx,None)
    render=QtCore.QTimer(window)
    render.setInterval(16)
    render.timeout.connect(viewport.update)
    render.start()
    window.scene.add_listener(lambda *args:viewport.update())
    window.show()
    pump(app,.5)
    probe=Probe(window)
    paint_times=[]
    original=viewport._paint_frame
    def paint():
        start=time.perf_counter()
        try:
            return profile.runcall(original) if os.environ.get('GRID_PROFILE') else original()
        finally:
            paint_times.append((time.perf_counter()-start)*1000)
    viewport._paint_frame=paint
    for op,sizes in SIZES.items():
        params=state(op)
        for extent in sizes:
            if os.environ.get('GRID_STRESS'):
                params=state(op)
            out=evaluate_grid(op,params,inputs(op,extent))
            model=grid_object_from_outputs(params,out)
            # Avoid measuring old test objects, retained History snapshots/cache.
            if not os.environ.get('GRID_STRESS'):
                window.scene.clear()
                window.history=History(window.scene)
            adapter._part_cache.clear()
            pump(app,.05)
            paint_times.clear()
            probe.reset()
            start=time.perf_counter()
            job=adapter.submit({'model':model.to_wire(),'name':'Benchmark grid'})
            while adapter.jobs[job['job_id']]['state']=='preparing' and time.perf_counter()-start<60:
                app.processEvents()
                time.sleep(.001)
            duration=(time.perf_counter()-start)*1000
            result=adapter.jobs[job['job_id']]
            if result['state']!='complete':
                raise RuntimeError(result.get('error',result['state']))
            viewport.zoom_extents()
            pump(app,.15)
            building_probe=probe.report()
            build_paints=list(paint_times)
            probe.reset()
            paint_times.clear()
            pump(app,.35)
            value=out['G'].values()[0]
            emit(dict(mode='native',kind=op,size=extent,cells=value.counts[0],points=value.counts[1],edges=value.counts[2],
                      publication_ms=round(duration,2),objects=len(window.scene.objects),**building_probe,
                      build_max_paint_ms=round(max(build_paints,default=0),2),
                      steady_max_paint_ms=round(max(paint_times,default=0),2),
                      steady_median_paint_ms=round(statistics.median(paint_times),2) if paint_times else None,
                      steady_qt=probe.report(),paint_failed=viewport.paint_failed))
    adapter.stop()
    window.scene.clear()
    window.close()
    if os.environ.get('GRID_PROFILE'):
        output = ROOT / ".test-output"
        output.mkdir(exist_ok=True)
        profile.dump_stats(str(output / "grid-paint.prof"))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('data','ui','native','stress'),required=True)
    args=parser.parse_args()
    if os.environ.get('GRID_PROFILE') or os.environ.get('GRID_PHASE'):
        SIZES={'grid_hexagon':[(50,50)]}
    if args.mode=='stress':
        os.environ['GRID_STRESS']='1'
        SIZES={'grid_rectangle':[(50,50)]*10}
    {'data':data_benchmark,'ui':ui_benchmark,'native':native_benchmark,'stress':native_benchmark}[args.mode]()
