"""Real OpenGL overlay verification, in a private native scene without RPC."""
import json
from pathlib import Path
import sys
import time
import uuid
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from benchmark_grids import qt_runtime,pump,Probe


def main():
    app=qt_runtime(True)
    import numpy as np
    from PySide6 import QtCore,QtGui,QtWidgets
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    from noodles.backend.scene_previews import PreviewAdapter
    from noodles.backend.viewport_acceleration import install
    window=QtWidgets.QMainWindow()
    window.setWindowTitle('Vector Preview — isolated OpenGL verification')
    window.scene=Scene()
    window.selection=SelectionManager(window.scene)
    viewport=Viewport(window.scene,window.selection)
    window.viewport=viewport
    window.setCentralWidget(viewport)
    window.resize(1000,700)
    install(window)
    adapter=PreviewAdapter(SimpleNamespace(window=window,scene=window.scene))
    viewport.camera.zoom_extents(((-10,-10,-10),(30,30,30)),1000/700)
    window.show()
    pump(app,.3)
    def pixels():
        viewport.update()
        pump(app,.04)
        image=viewport.grabFramebuffer().convertToFormat(QtGui.QImage.Format_RGBA8888)
        return image,np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*4].reshape(image.height(),image.width(),4).copy()
    base,before=pixels()
    client,project,node=(str(uuid.uuid4()) for _ in range(3))
    def frame(revision,items):
        return {'schema':1,'client_uuid':client,'revision':revision,'nodes':[{'project_uuid':project,'node_uuid':node,'items':items}]}
    item={'key':'arrow','kind':'vector','origin':[0,0,0],'vector':[20,10,15],'visible':True}
    adapter.sync(frame(1,[item]))
    shown,after=pixels()
    changed=int(np.any(np.abs(after[:,:,:3].astype(int)-before[:,:,:3])>8,axis=2).sum())
    assert changed>50,('No visible arrow pixels',changed,adapter.draw_error)
    assert not adapter.draw_error,adapter.draw_error
    adapter.sync(frame(2,[dict(item,visible=False)]))
    _,hidden=pixels()
    assert np.array_equal(hidden,before),'Hidden preview changed the native image.'
    adapter.sync(frame(3,[]))
    _,removed=pixels()
    assert np.array_equal(removed,before),'Removal left overlay pixels.'
    output = ROOT / ".test-output"
    output.mkdir(exist_ok=True)
    if not shown.save(str(output / "vector-preview-native.png")):
        raise OSError("Unable to save the Vector Preview test image.")
    timings=[]
    native=viewport._paint_frame
    def paint():
        start=time.perf_counter()
        try:
            return native()
        finally:
            timings.append((time.perf_counter()-start)*1000)
    viewport._paint_frame=paint
    probe=Probe(window)
    timer=QtCore.QTimer(window)
    timer.setInterval(16)
    timer.timeout.connect(viewport.update)
    timer.start()
    results=[]
    for revision,count in ((4,1),(5,200),(6,256)):
        items=[dict(item,key=str(i),origin=[i%16,i//16,0]) for i in range(count)]
        timings.clear()
        probe.reset()
        adapter.sync(frame(revision,items))
        pump(app,.5)
        assert not adapter.draw_error,adapter.draw_error
        results.append({'arrows':count,'paint_median_ms':round(float(np.median(timings)),2),'paint_max_ms':round(max(timings),2),**probe.report()})
    assert not window.scene.objects,'Preview created CAD geometry.'
    assert not viewport.paint_failed
    print(json.dumps({'changed_pixels':changed,'hidden_matches_native':True,'removed_matches_native':True,'scene_objects':0,'timings':results}),flush=True)
    adapter.timer.stop()
    window.close()


if __name__=='__main__':
    main()
