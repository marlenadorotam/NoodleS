"""Vectorize Serpentine's native point crosses, preserving its renderer/styles.

No custom renderer, mesh substitution or changes to installed Serpentine files.
The plugin replaces only the scalar numpy loop used by the native marker method.
"""
from functools import cache


@cache
def plain_brep_types():
    """OCC wrappers whose shape type fully describes their display behavior."""
    from OCP.TopoDS import (
        TopoDS_Compound, TopoDS_CompSolid, TopoDS_Edge, TopoDS_Face,
        TopoDS_Shape, TopoDS_Shell, TopoDS_Solid, TopoDS_Vertex, TopoDS_Wire,
    )

    return frozenset((
        TopoDS_Shape, TopoDS_Vertex, TopoDS_Edge, TopoDS_Wire, TopoDS_Face,
        TopoDS_Shell, TopoDS_Solid, TopoDS_CompSolid, TopoDS_Compound,
    ))


def marker_segments(points,size):
    import numpy as np
    pts=np.asarray(points,np.float32).reshape(-1,3)
    axes=np.eye(3,dtype=np.float32)*size
    segments=np.empty((len(pts),3,2,3),np.float32)
    segments[:,:,0,:]=pts[:,None,:]-axes[None,:,:]
    segments[:,:,1,:]=pts[:,None,:]+axes[None,:,:]
    return segments.reshape(-1,3)


def install(window):
    install_classification()
    if getattr(window,'viewport',None) is None:
        return
    from serpentine3d.ui import viewport as native
    cls=native.Viewport
    if getattr(cls._draw_point_markers,'_noodles_vectorized',False):
        return
    def draw(self,mvp,points,color,selected,anchor=None):
        size=self.camera.distance*(.009 if selected else .007)
        segments=marker_segments(native.rebased(points,anchor),size)
        self._preview.update(segments)
        self._set_line_uniforms(mvp,color)
        self._line_width(2.6 if selected else 1.8)
        gl=native.GL
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glBindVertexArray(self._preview.vao)
        gl.glDrawArrays(gl.GL_LINES,0,len(segments))
        gl.glEnable(gl.GL_DEPTH_TEST)
    draw._noodles_vectorized=True
    cls._draw_point_markers=draw


def install_classification():
    """Same native kinds, without repeating Python imports for every subshape."""
    from serpentine3d.core import geometry
    current = geometry.shape_kind
    if getattr(current, '_noodles_plain_brep', False):
        return
    # A session refreshed from an older bridge may still hold its classifier.
    original = getattr(current, '_noodles_original', current)
    from OCP.TopoDS import TopoDS_Iterator
    from OCP.TopAbs import (TopAbs_EDGE,TopAbs_WIRE,TopAbs_FACE,TopAbs_SHELL,
                           TopAbs_SOLID,TopAbs_COMPSOLID,TopAbs_VERTEX)
    kinds={TopAbs_EDGE:'curve',TopAbs_WIRE:'curve',TopAbs_FACE:'surface',TopAbs_SHELL:'surface',
           TopAbs_SOLID:'solid',TopAbs_COMPSOLID:'solid',TopAbs_VERTEX:'point'}
    brep_types = plain_brep_types()
    def fast(shape):
        if type(shape) not in brep_types:
            return original(shape)
        kind=kinds.get(shape.ShapeType())
        if kind is not None:
            return kind
        seen=set()
        children=TopoDS_Iterator(shape)
        while children.More():
            seen.add(fast(children.Value()))
            if len(seen)>1:
                return 'compound'
            children.Next()
        return next(iter(seen)) if seen else 'compound'
    fast._noodles_fast=True
    fast._noodles_plain_brep=True
    fast._noodles_original=original
    geometry.shape_kind=fast
    install_free_points()


def install_free_points():
    from serpentine3d.core import geometry
    if getattr(geometry.free_points,'_noodles_fast',False):
        return
    from OCP.TopAbs import TopAbs_VERTEX,TopAbs_EDGE,TopAbs_COMPOUND
    from OCP.TopoDS import TopoDS
    from OCP.TopExp import TopExp,TopExp_Explorer
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.BRep import BRep_Tool
    import time
    original=geometry.free_points
    def coordinates(vertex):
        p=BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex))
        return p.X(),p.Y(),p.Z()
    def fast(shape):
        if shape is None:
            return []
        if shape.ShapeType()==TopAbs_VERTEX:
            return [coordinates(shape)]
        if shape.ShapeType()!=TopAbs_COMPOUND:
            return []
        owners=TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape,TopAbs_VERTEX,TopAbs_EDGE,owners)
        vertices=TopExp_Explorer(shape,TopAbs_VERTEX)
        out,seen=[],set()
        deadline=time.perf_counter()+.004
        while vertices.More():
            vertex=vertices.Current()
            vertices.Next()
            key=hash(vertex)
            if key not in seen:
                seen.add(key)
                index=owners.FindIndex(vertex)
                if index==0 or owners.FindFromIndex(index).Size()==0:
                    out.append(coordinates(vertex))
            if time.perf_counter()>=deadline:
                time.sleep(.001)  # Yield the CPU; no scene mutation or delayed publication.
                deadline=time.perf_counter()+.004
        return out
    fast._noodles_fast=True
    fast._noodles_original=original
    geometry.free_points=fast
