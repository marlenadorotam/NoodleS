"""Prepare Serpentine's own DisplayMesh from face-free OCC geometry on a worker.

The native tessellator is retained for surfaces/solids and curved-edge sampling.
Lines avoid repeated per-edge imports/array allocations, and CPU slices yield
to Qt. There is still one atomic scene publication, irrespective of size.
"""
def _cooperative_faces(native,shape,deflection=None):
    """Keep native sampling/mesh topology, yielding between completed faces/edges."""
    import threading
    import time
    if not hasattr(native,'_noodles_cpu_budget'):
        native._noodles_cpu_budget=threading.local()
    for name in ('_face_mesh','_edge_polyline'):
        original=getattr(native,name)
        if getattr(original,'_noodles_cooperative',False):
            continue
        def wrapped(*args,_original=original,**kwargs):
            result=_original(*args,**kwargs)
            state=native._noodles_cpu_budget
            if getattr(state,'active',False) and time.perf_counter()>=state.deadline:
                time.sleep(.001)
                state.deadline=time.perf_counter()+.004
            return result
        wrapped._noodles_cooperative=True
        setattr(native,name,wrapped)
    state=native._noodles_cpu_budget
    was_active=getattr(state,'active',False)
    state.active=True
    state.deadline=time.perf_counter()+.004
    try:
        return native.tessellate(shape,deflection)
    finally:
        state.active=was_active


def geometry_bounds(parts):
    """Exact native BREP bounds, accumulated per part with the worker CPU budget."""
    import time
    from serpentine3d.core import geometry
    low,high=None,None
    deadline=time.perf_counter()+.004
    for part in parts:
        a,b=geometry.bbox(part)
        low=tuple(min(x,y) for x,y in zip(low,a)) if low is not None else a
        high=tuple(max(x,y) for x,y in zip(high,b)) if high is not None else b
        if time.perf_counter()>=deadline:
            time.sleep(.001)
            deadline=time.perf_counter()+.004
    return (low,high) if low is not None else ((0.,0.,0.),(0.,0.,0.))


def tessellate(shape,parts=None,bounds=None,wire_edges=None):
    from serpentine3d.core import tessellate as native,geometry
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    if wire_edges is None and TopExp_Explorer(shape,TopAbs_FACE).More():
        import math
        if bounds is None and parts:
            bounds=geometry_bounds(parts)
        deflection=max(math.dist(*bounds)*.002,1e-4) if bounds is not None else native.default_deflection(shape)
        if parts and len(parts)>1:
            # Pre-mesh using the final compound's exact native deflection.
            # The final native tessellator reuses those triangulations; there
            # is no concatenation guessing at face/edge IDs, nor partial scene.
            import time
            deadline=time.perf_counter()+.004
            for part in parts:
                if TopExp_Explorer(part,TopAbs_FACE).More():
                    native.BRepMesh_IncrementalMesh(part,deflection,False,.35,True)
                if time.perf_counter()>=deadline:
                    time.sleep(.001)
                    deadline=time.perf_counter()+.004
        return _cooperative_faces(native,shape,deflection)
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    import numpy as np
    import time
    if bounds is None:
        deflection = native.default_deflection(shape)
    else:
        import math
        deflection = max(math.dist(*bounds)*.002, 1e-4)
    segments,ids=[],[]
    deadline=time.perf_counter()+.003
    for index,edge in enumerate(geometry.edges_of(shape) if wire_edges is None else wire_edges):
        curve=BRepAdaptor_Curve(edge)
        if curve.GetType()==GeomAbs_Line:
            a,b=curve.Value(curve.FirstParameter()),curve.Value(curve.LastParameter())
            segments.append(((a.X(),a.Y(),a.Z()),(b.X(),b.Y(),b.Z())))
            ids.append(index)
        else:
            points=native._edge_polyline(edge,deflection)
            if points is not None and len(points)>=2:
                segments.extend(zip(points[:-1],points[1:]))
                ids.extend([index]*(len(points)-1))
        if time.perf_counter()>=deadline:
            time.sleep(.001)
            deadline=time.perf_counter()+.003
    points=geometry.free_points(shape) if wire_edges is None else ()
    mesh=native.DisplayMesh()
    mesh.place(edge_segments=np.asarray(segments,float) if segments else None,
               points=np.asarray(points,float) if points else None)
    if ids:
        mesh.edge_of_segment=np.asarray(ids,np.int32)
    # Prepare the native spatial cache here, rather than racing a first click.
    mesh.segment_index()
    return mesh
