"""Session-only native viewport overlays, never scene objects or CPlane edits."""
from functools import lru_cache
import math
import time
import uuid
import weakref
from .curves import PlaneValue, xyz
from .previews import MAX_UV_GRID_VERTICES, PlanePreviewValue
from .arithmetic import VectorValue
from .annotations import ANNOTATIONS, annotation_from_wire
from .parent_visibility import BASELINE, reconcile, validated_targets

LEASE_SECONDS=10.
UV_GRID_COLORS = ((.21, .94, .90, 1.), (1., .73, .25, 1.))


def arrow_geometry(origin,vector,head_length,head_radius):
    """Same true-length, 10-facet filled arrow as the former Vector Preview."""
    shafts,heads=arrows_geometry([origin],[vector],[head_length],[head_radius])
    return shafts,heads


def arrows_geometry(origins,vectors,head_lengths,head_radii):
    """Batch CPU preparation only; one pair of native draw calls for all arrows."""
    import numpy as np
    origins=np.asarray(origins,float).reshape(-1,3)
    vectors=np.asarray(vectors,float).reshape(-1,3)
    lengths=np.linalg.norm(vectors,axis=1)
    if np.any(lengths<1e-12):
        raise ValueError('Vector cannot be zero.')
    axis=vectors/lengths[:,None]
    tips=origins+vectors
    head_lengths=np.minimum(np.maximum(head_lengths,0),lengths*.35)
    head_radii=np.minimum(np.maximum(head_radii,0),head_lengths*4.3/17.)
    bases=tips-axis*head_lengths[:,None]
    ref=np.zeros_like(axis)
    mask=np.abs(axis[:,0])<.90
    ref[mask,0]=1.
    ref[~mask,1]=1.
    u=np.cross(axis,ref)
    u/=np.linalg.norm(u,axis=1)[:,None]
    v=np.cross(axis,u)
    angles=np.arange(11)*math.tau/10
    ring=bases[:,None,:]+head_radii[:,None,None]*(np.cos(angles)[None,:,None]*u[:,None,:]+np.sin(angles)[None,:,None]*v[:,None,:])
    triangles=np.empty((len(origins),10,3,3),float)
    triangles[:,:,0]=tips[:,None,:]
    triangles[:,:,1]=ring[:,:-1]
    triangles[:,:,2]=ring[:,1:]
    return np.stack((origins,bases),axis=1).reshape(-1,3),triangles.reshape(-1,3)


@lru_cache(maxsize=256)
def plane_grid(value):
    """Centered grid and independent X/Y axes in world coordinates."""
    w, h, spacing = value.width/2, value.height/2, value.spacing
    at = value.frame.at
    grid = []
    for i in range(1, int(w/spacing)+1):
        x = i*spacing
        if x < w:
            grid.extend((at(x, -h), at(x, h), at(-x, -h), at(-x, h)))
    for i in range(1, int(h/spacing)+1):
        y = i*spacing
        if y < h:
            grid.extend((at(-w, y), at(w, y), at(-w, -y), at(w, -y)))
    corners = (at(-w, -h), at(w, -h), at(w, h), at(-w, h))
    for i in range(4):
        grid.extend((corners[i], corners[(i+1)%4]))
    return tuple(grid), (at(-w, 0), at(w, 0)), (at(0, -h), at(0, h))


class PreviewAdapter:
    def __init__(self,ctx,scene_adapter=None):
        self.ctx=ctx
        self.scene_adapter = scene_adapter
        self.visibility_revision = weakref.WeakKeyDictionary()
        if scene_adapter is not None:
            scene_adapter.preview_hide_targets = self.hide_targets
        self.draw_error=''
        self.annotation_error = ''
        window=ctx.window
        if not hasattr(window,'_noodles_previews'):
            window._noodles_previews=weakref.WeakKeyDictionary()
        if not hasattr(window, '_noodles_preview_documents'):
            window._noodles_preview_documents = weakref.WeakKeyDictionary()
        window._noodles_preview_adapter=self
        from PySide6.QtCore import QTimer
        self.timer=QTimer(window)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.expire)
        self.timer.start()
        if getattr(window,'viewport',None) is not None:
            self.install_renderer()

    def records(self,scene=None):
        scene=self.ctx.scene if scene is None else scene
        window = self.ctx.window
        documents = window._noodles_preview_documents
        if scene.layers is not documents.get(scene):
            documents[scene] = scene.layers
            window._noodles_previews[scene] = {}
        return window._noodles_previews.setdefault(scene, {})

    def update(self):
        window=self.ctx.window
        for viewport in (getattr(window,'viewport',None),*getattr(window,'aux_viewports',()),*getattr(window,'dock_viewports',())):
            if viewport is not None:
                viewport.update()

    def hide_targets(self, scene):
        return {target for record in self.records(scene).values() if not record.get('expired')
                for target in record.get('hide_targets', ())}

    def reconcile_visibility(self, scene):
        if self.scene_adapter is not None:
            with scene.batched():
                reconcile(self.scene_adapter, scene)
            self.visibility_revision[scene] = scene.revision

    def restore_saved_visibility(self, scene):
        if self.scene_adapter is not None and any(
                self.scene_adapter._json(obj, BASELINE) is not None for obj in scene.all()):
            self._reconcile_automatic(scene)

    def _reconcile_automatic(self, scene):
        try:
            self.reconcile_visibility(scene)
        except ValueError:
            # An ambiguous binding is reported by explicit sync. Leave it
            # untouched during lease cleanup or automatic scene attachment.
            pass

    def sync(self,frame):
        if type(frame.get('schema')) is not int or frame['schema']!=1:
            raise ValueError('Invalid preview schema.')
        client=str(uuid.UUID(frame.get('client_uuid')))
        revision=frame.get('revision')
        nodes=frame.get('nodes')
        if type(revision) is not int or revision<0 or not isinstance(nodes,list) or len(nodes)>256:
            raise ValueError('Invalid preview frame.')
        entries, hide_targets = [], set()
        plane_segments = 0
        grid_vertices = 0
        node_ids=set()
        for node in nodes:
            if not isinstance(node,dict):
                raise ValueError('Invalid preview node.')
            identity=(str(uuid.UUID(node.get('project_uuid'))),str(uuid.UUID(node.get('node_uuid'))))
            if identity in node_ids:
                raise ValueError('Duplicate preview node identity.')
            node_ids.add(identity)
            hide_targets.update(validated_targets(node.get('hide_targets', [])))
            if len(hide_targets) > 10000:
                raise ValueError('Hide supports up to 10,000 object bindings per frame.')
            items=node.get('items')
            if not isinstance(items,list) or len(items)>256:
                raise ValueError('Too many preview items per node.')
            keys=set()
            for item in items:
                if (not isinstance(item,dict) or item.get('kind') not in ('vector', 'plane', 'uv_grid', *ANNOTATIONS) or type(item.get('visible')) is not bool
                        or not isinstance(item.get('key'),str) or not 0<len(item['key'])<=256 or item['key'] in keys):
                    raise ValueError('Invalid preview item.')
                keys.add(item['key'])
                if item['kind'] in ANNOTATIONS:
                    value = annotation_from_wire(item)
                    entries.append({'annotation': value, 'visible': value.visible})
                elif item['kind'] == 'plane':
                    frame = item.get('plane')
                    if not isinstance(frame, dict):
                        raise ValueError('Invalid preview plane.')
                    value = PlanePreviewValue(item['key'], PlaneValue(**frame), item.get('width'),
                                              item.get('height'), item.get('spacing'), item['visible'])
                    if value.visible:
                        plane_segments += int(value.width/value.spacing) + int(value.height/value.spacing) + 6
                        if plane_segments > 20000:
                            raise ValueError('Plane Preview frame is too dense. Increase Spacing or hide some planes.')
                    entries.append({'plane': value, 'visible': value.visible})
                elif item['kind'] == 'uv_grid':
                    groups = []
                    for axis in ('u', 'v'):
                        lines = item.get(axis)
                        if not isinstance(lines, list):
                            raise ValueError('Invalid UV grid polylines.')
                        segments = []
                        for line in lines:
                            if not isinstance(line, list) or len(line) < 2:
                                raise ValueError('A UV grid line needs at least two vertices.')
                            grid_vertices += len(line)
                            if grid_vertices > MAX_UV_GRID_VERTICES * 2:
                                raise ValueError('UV preview frame is too dense. Hide a preview or reduce divisions.')
                            points = tuple(map(xyz, line))
                            segments.extend(point for pair in zip(points, points[1:]) for point in pair)
                        groups.append(tuple(segments))
                    entries.append({'uv_grid': tuple(groups), 'visible': item['visible']})
                else:
                    raw_vector=item.get('vector')
                    if not isinstance(raw_vector,(tuple,list)) or len(raw_vector)!=3:
                        raise ValueError('Vector requires three finite components.')
                    origin,vector=xyz(item.get('origin')),VectorValue(tuple(raw_vector)).xyz
                    xyz(tuple(a+b for a,b in zip(origin,vector)))
                    if math.hypot(*vector)<1e-12:
                        raise ValueError('Vector cannot be zero.')
                    entries.append({'origin':origin,'vector':vector,'visible':item['visible']})
                if len(entries)>1024:
                    raise ValueError('Preview frame exceeds 1024 items.')
        scene = self.ctx.scene
        records=self.records(scene)
        previous=records.get(client)
        if previous and revision<previous['revision']:
            return {'state':'superseded'}
        previous_targets = previous.get('hide_targets', set()) if previous else set()
        if previous and revision==previous['revision'] and (
                entries != previous['entries'] or hide_targets != previous_targets):
            raise ValueError('A preview revision cannot contain different data.')
        changed=not previous or entries!=previous['entries'] or previous.get('expired',False)
        records[client]={'revision':revision,'entries':entries,'hide_targets':hide_targets,'seen':time.monotonic()}
        if hide_targets != previous_targets or (hide_targets and (
                changed or scene.revision != self.visibility_revision.get(scene))):
            try:
                self.reconcile_visibility(scene)
            except ValueError:
                if previous is None:
                    del records[client]
                else:
                    records[client] = previous
                raise
        if changed:
            self.update()
        if self.draw_error:
            raise ValueError('Preview rendering failed: '+self.draw_error)
        if self.annotation_error and any('annotation' in entry and entry['visible'] for entry in entries):
            raise ValueError('Annotation rendering failed: ' + self.annotation_error)
        return {'state':'complete','count':len(entries)}

    def expire(self, *, release=False):
        changed=False
        now=time.monotonic()
        for scene in tuple(self.ctx.window._noodles_previews):
            records = self.records(scene)
            visibility_changed = False
            for client,record in tuple(records.items()):
                if (release or now-record['seen']>LEASE_SECONDS) and not record.get('expired'):
                    record['expired']=True
                    visibility_changed |= bool(record.get('hide_targets'))
                    changed |= bool(record['entries'])
                if now-record['seen']>300:
                    del records[client]
            if visibility_changed:
                self._reconcile_automatic(scene)
        if changed:
            self.update()

    def visible(self,scene):
        now=time.monotonic()
        return [item for record in self.records(scene).values()
                if not record.get('expired') and now-record['seen']<=LEASE_SECONDS
                for item in record['entries'] if item['visible']]

    def draw_annotations(self, viewport, width, height):
        from .annotation_render import paint_viewport_annotations
        paint_viewport_annotations(self, viewport, width, height)

    @staticmethod
    def install_renderer():
        from serpentine3d.ui.viewport import Viewport
        from .annotation_render import install_annotation_renderer
        install_annotation_renderer(Viewport)
        if getattr(Viewport._draw_objects,'_noodles_previews',False):
            return
        native=Viewport._draw_objects
        def draw(viewport,mvp,view,*args,**kwargs):
            result=native(viewport,mvp,view,*args,**kwargs)
            adapter=getattr(viewport.window(),'_noodles_preview_adapter',None)
            if (adapter and viewport.space=='model' and viewport.display_mode!='technical'
                    and not kwargs.get('light_background',False)):
                try:
                    adapter.draw(viewport,mvp)
                except Exception as exc:
                    adapter.draw_error=str(exc)
            return result
        draw._noodles_previews=True
        Viewport._draw_objects=draw

    def draw(self,viewport,mvp64):
        import numpy as np
        from OpenGL import GL
        from serpentine3d.ui.viewport import anchored,rebased,cv_marker_size
        from serpentine3d.ui.gumball import HOVER_COLOR
        items=self.visible(viewport.scene)
        if not items:
            return
        anchor=viewport._frame_anchor
        mvp=anchored(mvp64,anchor)
        arrows = [item for item in items if 'vector' in item]
        planes = [item['plane'] for item in items if 'plane' in item]
        uv_grids = [item['uv_grid'] for item in items if 'uv_grid' in item]
        color=(*HOVER_COLOR,1.) if len(HOVER_COLOR)==3 else HOVER_COLOR

        def draw_lines(points, line_color, width):
            viewport._preview.update(rebased(np.asarray(points), anchor))
            viewport._draw_lines(viewport._preview, mvp, line_color, width)

        if uv_grids:
            # Keep depth testing so the grid follows the visible part of the
            # surface and disappears behind other geometry.
            GL.glDepthFunc(GL.GL_LEQUAL)
            GL.glDepthMask(False)
            try:
                for axis, line_color in enumerate(UV_GRID_COLORS):
                    points = [point for grid in uv_grids for point in grid[axis]]
                    if points:
                        draw_lines(points, line_color, 1.5)
            finally:
                GL.glDepthMask(True)
                GL.glDepthFunc(GL.GL_LESS)
        if not (arrows or planes):
            return
        GL.glDisable(GL.GL_DEPTH_TEST)
        try:
            if planes:
                groups = ([], [], [])
                for value in planes:
                    for group, points in zip(groups, plane_grid(value)):
                        group.extend(points)
                for points, line_color in zip(groups, ((.46,.59,.66,.52),(.92,.41,.36,.9),(.43,.81,.49,.9))):
                    draw_lines(points, line_color, 1.2)
            if arrows:
                tips=np.asarray([np.add(item['origin'],item['vector']) for item in arrows])
                head_lengths=cv_marker_size(tips,viewport.camera,viewport.width(),viewport.height(),17.)
                shafts,heads=arrows_geometry([i['origin'] for i in arrows],[i['vector'] for i in arrows],head_lengths,head_lengths*4.3/17.)
                draw_lines(shafts, color, 2.4)
                points=rebased(heads,anchor)
                viewport._preview.update(points)
                viewport._set_line_uniforms(mvp,color)
                GL.glBindVertexArray(viewport._preview.vao)
                GL.glDrawArrays(GL.GL_TRIANGLES,0,len(points))
        finally:
            GL.glEnable(GL.GL_DEPTH_TEST)


def register_commands(ctx):
    """Independent native helper, no editor process or CAD geometry needed."""
    req=ctx.requests()
    @ctx.command('vectorpreview',mutates=False,label='Vector Preview')
    def create(c):
        origin=yield req.PointReq('Arrow origin',default=(0.,0.,0.))
        start=yield req.PointReq('Vector start',default=origin)
        end=yield req.PointReq('Vector end',default=(start[0],start[1],start[2]+10.))
        adapter=getattr(ctx.window,'_noodles_preview_adapter',None)
        if adapter is None:
            c.echo('Load NoodleSBridge first.')
            return
        # Native helper has its own client; keep it alive until explicitly cleared.
        client=getattr(ctx.window,'_noodles_native_preview_client',None) or str(uuid.uuid4())
        ctx.window._noodles_native_preview_client=client
        record=adapter.records().get(client,{})
        items=[dict(e,key=str(i),kind='vector') for i,e in enumerate(record.get('entries',()))]
        items.append({'key':str(len(items)),'kind':'vector','origin':list(map(float,origin)),
                      'vector':[float(b-a) for a,b in zip(start,end)],'visible':True})
        try:
            adapter.sync({'schema':1,'client_uuid':client,'revision':record.get('revision',0)+1,
                'nodes':[{'project_uuid':client,'node_uuid':client,'items':items}]})
            adapter.records()[client]['seen']=float('inf')
            c.echo('Vector preview added; no CAD object created.')
        except (ValueError,TypeError) as exc:
            c.echo(str(exc))
    @ctx.command('vectorpreviewclear',mutates=False,label='Clear native vector previews')
    def clear(c):
        adapter=getattr(ctx.window,'_noodles_preview_adapter',None)
        client=getattr(ctx.window,'_noodles_native_preview_client',None)
        if adapter and client:
            adapter.records().pop(client,None)
            adapter.update()
        c.echo('Native vector previews cleared.')
        if False:
            yield
