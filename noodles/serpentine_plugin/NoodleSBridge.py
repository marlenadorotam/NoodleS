"""Local bridge between the NoodleS editor and Serpentine3D.

The installer deploys this entry point and the shared CAD modules in
_noodles_core. The authenticated JSON protocol exposes explicit methods for
scene status, geometry, references and previews. Geometry is prepared by a
worker and the resulting scene changes are applied on Serpentine's Qt thread.
"""
from __future__ import annotations

import hmac
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import uuid
import weakref

from PySide6 import QtCore, QtNetwork, QtWidgets

PROTOCOL_VERSION = 1
MAX_FRAME = 1048576
GRAPH_LINK = 'NoodleS.graph_link'
DOCUMENT_UUID = 'NoodleS.document_uuid'
PANEL_DOCK_NAMES = {'properties': 'propertiesDock', 'layers': 'layersDock'}
CAPABILITIES = ["status", "scene_summary", "points.generate", "points.reference", "points.drive", "events"]
CAPABILITIES += ['curves.generate', 'curves.reference']
CAPABILITIES += ['solids.generate', 'solids.reference']
CAPABILITIES += ['geometry.drive', 'geometry.pull', 'geometry.sample']
CAPABILITIES += ['geometry.mass_properties']
CAPABILITIES += ['geometry.ungroup']
CAPABILITIES += ['grids.generate', 'grids.reference']
CAPABILITIES += ['previews.vector', 'previews.plane', 'previews.uv_grid', 'previews.annotations']
CAPABILITIES += ['previews.hide']
CAPABILITIES += ['operations.generate']
CAPABILITIES += ['surfaces.generate']
CAPABILITIES += ['surfaces.reference', 'geometry.surface_domain', 'geometry.surface_closest']
CAPABILITIES += ['sweeps.generate']
CAPABILITIES += ['moves.generate','moves.reference']
CAPABILITIES += ['booleans.native']


def code_digest(directory=None):
    directory = Path(directory) if directory else Path(__file__).parent
    backend = directory / "_noodles_core"
    if not backend.exists():
        backend = directory.parent / "backend"
    digest = hashlib.sha256()
    for path in [directory / "NoodleSBridge.py", *sorted(backend.glob("*.py"))]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class BridgeServer(QtCore.QObject):
    def __init__(self, ctx, descriptor=None):
        super().__init__(ctx.window)
        self.ctx = ctx
        self.code_digest = code_digest()
        self.descriptor = Path(descriptor) if descriptor else Path.home() / ".serpentine3d" / "noodles" / "bridge.json"
        self.session_id = str(uuid.uuid4())  # Connection session, NOT a persistent project/object ID.
        self.instance_descriptor = self.descriptor.with_suffix(".instances") / (self.session_id + ".json")
        self.token = secrets.token_urlsafe(32)
        self.server = QtNetwork.QTcpServer(self)
        self.server.setMaxPendingConnections(8)
        self.server.newConnection.connect(self._accept)
        self.clients = {}
        self.subscribers = set()
        self._listened_scene = None
        self._visibility_document = None
        self._visibility_objects = None
        self._panel_visibility = {}
        self._panel_revision = 0
        self.event_timer = QtCore.QTimer(self)
        self.event_timer.setSingleShot(True)
        self.event_timer.timeout.connect(lambda: self._broadcast("scene_changed"))
        self.heartbeat = QtCore.QTimer(self)
        self.heartbeat.timeout.connect(lambda: self._broadcast("heartbeat"))
        if __package__ and __package__.startswith("noodles"):
            from ..backend.scene_points import ParametricSceneAdapter
            from ..backend.scene_previews import PreviewAdapter
        else:
            directory = str(Path(__file__).parent)
            if directory not in sys.path:
                sys.path.insert(0, directory)
            # Older refresh commands reload only Point/Scene. The new server
            # must own a coherent current core, even during that upgrade path.
            for name in list(sys.modules):
                if name == '_noodles_core' or name.startswith('_noodles_core.'):
                    sys.modules.pop(name, None)
            from _noodles_core.scene_points import ParametricSceneAdapter
            from _noodles_core.scene_previews import PreviewAdapter
        version_module = importlib.import_module(f'{_core_package()}.version', __package__)
        self.version = version_module.__version__
        self.points = ParametricSceneAdapter(ctx, self)
        self.previews = PreviewAdapter(ctx, self.points)
        self.geometry = self.points  # One publisher for all generated geometry kinds.
        self.cad_viewport = None
        if getattr(ctx.window,'viewport',None) is not None:
            cad = importlib.import_module(f'{_core_package()}.cad_viewport', __package__)
            self.cad_viewport = cad.CadViewport(ctx)
            _register_commands(ctx)
            cad.register_commands(ctx, self.cad_viewport)
        self.points.references_updated.connect(lambda: self.event_timer.start(0))

    def start(self):
        if not self.server.listen(QtNetwork.QHostAddress.SpecialAddress.LocalHost, 0):
            raise RuntimeError("Unable to start NoodleS bridge: " + self.server.errorString())
        record = {"host": "127.0.0.1", "port": self.server.serverPort(),
                  "protocol": PROTOCOL_VERSION, "token": self.token,
                  "session_id": self.session_id, "pid": os.getpid()}
        try:
            self.instance_descriptor.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(record)
            for path in (self.instance_descriptor, self.descriptor):
                temporary = path.with_name(f".{self.session_id}.tmp")
                try:
                    temporary.write_text(data, encoding="utf-8")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
        except Exception:
            self.server.close()
            self.instance_descriptor.unlink(missing_ok=True)
            raise
        self._attach_scene()
        self.heartbeat.start(1000)
        return self.server.serverPort()

    def stop(self):
        self.server.close()
        self.heartbeat.stop()
        self.event_timer.stop()
        self.points.stop()
        self.previews.timer.stop()
        self.previews.expire(release=True)
        if self.cad_viewport is not None:
            self.cad_viewport.stop()
        for socket in list(self.clients):
            socket.abort()
        try:
            self.instance_descriptor.unlink(missing_ok=True)
            record = json.loads(self.descriptor.read_text(encoding="utf-8"))
            if record.get("session_id") == self.session_id:
                self.descriptor.unlink()
        except (OSError, ValueError):
            pass

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self.clients) >= 8:
                socket.abort()
                socket.deleteLater()
                continue
            socket.setReadBufferSize(MAX_FRAME + 1)
            self.clients[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._drop(s))
            timer = QtCore.QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(3000)

    def _drop(self, socket):
        self.clients.pop(socket, None)
        self.subscribers.discard(socket)
        socket.deleteLater()

    def _read(self, socket):
        buffer = self.clients.get(socket)
        if buffer is None:
            return
        if socket in self.subscribers:
            socket.abort()
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_FRAME:
            socket.abort()
            return
        if b"\n" not in buffer:
            return
        line = bytes(buffer).split(b"\n", 1)[0]
        response = self.handle_line(line)
        socket.write(json.dumps(response, allow_nan=False).encode("utf-8") + b"\n")
        if "error" not in response and json.loads(line).get("method") == "events.subscribe":
            self.clients[socket].clear()
            self.subscribers.add(socket)
            socket.findChild(QtCore.QTimer).stop()
            return
        socket.disconnectFromHost()  # One bounded request per connection.

    def _attach_scene(self):
        scene = self.ctx.scene
        document = getattr(scene, 'layers', None)
        objects = getattr(scene, 'objects', None)
        if document is not None:
            self._document_uuid()
        if document is not None and (document is not self._visibility_document or objects is not self._visibility_objects):
            self._visibility_document = document
            self._visibility_objects = objects
            self.previews.restore_saved_visibility(scene)
        if scene is self._listened_scene or not callable(getattr(scene, "add_listener", None)):
            return
        self._listened_scene = scene
        ref = weakref.ref(self)
        def changed():
            bridge = ref()
            if bridge is not None:
                try:
                    if bridge.server.isListening():
                        if getattr(bridge.ctx.scene, 'layers', None) is not None:
                            bridge._document_uuid()
                        if not bridge.event_timer.isActive():
                            bridge.event_timer.start(0)
                except RuntimeError:
                    pass
        scene.add_listener(changed)

    def _broadcast(self, event):
        self._attach_scene()
        frame = json.dumps({"event": event, "revision": self.ctx.scene.revision,
                            "session_id": self.session_id}).encode() + b"\n"
        for socket in list(self.subscribers):
            if socket.bytesToWrite() > MAX_FRAME:
                socket.abort()
            else:
                socket.write(frame)

    def summary(self):
        self._attach_scene()
        # Query the current window scene each time; a new/open document must
        # never leave the bridge attached to a previous Scene instance.
        scene = self.ctx.scene
        window = self.ctx.window
        ungroup = importlib.import_module(f'{_core_package()}.scene_ungroup', __package__)
        path = getattr(getattr(window, "ctx", None), "current_path", None)
        docks = self._panel_docks()
        panels = {name: not dock.isHidden() for name, dock in docks.items()}
        if panels != self._panel_visibility:
            self._panel_visibility = panels
            self._panel_revision += 1
        scene_token = self._scene_token()
        link = (getattr(scene, 'session', None) or {}).get(GRAPH_LINK) or {}
        return {"application": "Serpentine3D", "serpentine_version": str(self.ctx.version),
                "plugin_version": self.version, "protocol": PROTOCOL_VERSION,
                "session_id": self.session_id,
                "capabilities": CAPABILITIES + (['viewport.set'] if self.cad_viewport else []),
                "ungrouped_owners": ungroup.detached_owners(scene),
                **({'viewport': self.cad_viewport.state()} if self.cad_viewport else {}),
                **({'panels': {'revision': self._panel_revision, 'visible': panels}} if panels else {}),
                "scene": {"revision": int(scene.revision), "object_count": len(scene.objects),
                          "path": str(path) if path else None,
                          **({'token': scene_token, 'document_uuid': self._document_uuid(),
                              'persistent_document_uuid': True,
                              'graph_link': link} if scene_token else {}),
                          "busy": bool(getattr(getattr(window, "processor", None), "busy", False))}}

    def _scene_token(self):
        if hasattr(self.ctx.scene, 'layers'):
            native = importlib.import_module(f'{_core_package()}.scene_boolean', __package__)
            return native.scene_token(self.points)
        return None

    def _document_uuid(self):
        # Stamp the scene before the native Save can run, including when the
        # editor has never saved a graph. Keep the per-opening token separate.
        scene = self.ctx.scene
        session = getattr(scene, 'session', None) or {}
        link = session.get(GRAPH_LINK) or {}
        document_uuid = link.get('document_uuid') or session.get(DOCUMENT_UUID)
        if not document_uuid:
            document_uuid = self._scene_token()
            scene.session = {**session, DOCUMENT_UUID: document_uuid}
        return document_uuid

    def _link_graph(self, params):
        scene = self.ctx.scene
        document_uuid = self._document_uuid()
        session = dict(scene.session or {})
        previous = session.get(GRAPH_LINK) or {}
        link = {
            'document_uuid': document_uuid,
            'project_uuid': str(uuid.UUID(params['project_uuid'])),
            'revision': uuid.UUID(params['revision']).hex,
        }
        if params['document_uuid'] != link['document_uuid']:
            raise ValueError('The Serpentine document link changed. Save the graph again.')
        if previous != link:
            session[GRAPH_LINK] = link
            scene.session = session
            # Saving a graph after the CAD file does not dirty CAD geometry.
            self.event_timer.start(0)

    def _panel_docks(self):
        return {panel: dock for panel, name in PANEL_DOCK_NAMES.items()
                if (dock := self.ctx.window.findChild(QtWidgets.QDockWidget, name)) is not None}

    def handle_line(self, line):
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Expected a JSON object.")
            request_id = request.get("id")
            if type(request_id) not in (int, str):
                raise ValueError("A request ID is required.")
            token = request.get("token")
            if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
                raise ValueError("Invalid connection token.")
            if type(request.get("protocol")) is not int or request["protocol"] != PROTOCOL_VERSION:
                raise ValueError("Incompatible NoodleS bridge protocol.")
            method = request.get("method")
            if method not in ("hello", "status", "events.subscribe", "points.prepare", "points.job",
                              "points.remove", "points.capture", "points.read", "points.drive",
                              'geometry.prepare', 'geometry.job', 'geometry.remove', 'geometry.capture', 'geometry.read', 'geometry.drive', 'geometry.pull', 'geometry.sample', 'geometry.surface_domain', 'geometry.move_refs', 'curves.capture', 'curves.read','previews.sync',
                              'geometry.boolean_apply', 'geometry.boolean_read', 'geometry.topology', 'geometry.uv_grid',
                              'geometry.mass_properties', 'geometry.ungroup',
                              'geometry.population', 'geometry.tessellation', 'geometry.surface_structure', 'geometry.surface_closest',
                              'viewport.set', 'ui.panels.set', 'scene.link_graph'):
                raise ValueError("Unsupported NoodleS bridge method.")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("Expected method parameters.")
            geometry_method = method.startswith(('points.', 'geometry.', 'curves.','previews.'))
            expected_scene = request.get('scene_token')
            if expected_scene is not None or method == 'scene.link_graph':
                if not expected_scene or expected_scene != self._scene_token():
                    raise ValueError('The active Serpentine document changed.')
            if method == 'scene.link_graph':
                self._link_graph(params)
            elif method == 'viewport.set':
                if self.cad_viewport is None:
                    raise ValueError('CAD View requires a Serpentine viewport.')
                if params.get('session_id') != self.session_id:
                    raise ValueError('Invalid CAD View request or expired Serpentine session.')
                if set(params) == {'enabled', 'session_id'} and type(params['enabled']) is bool:
                    self.cad_viewport.set_enabled(params['enabled'])
                elif set(params) == {'high_smooth', 'session_id'} and type(params['high_smooth']) is bool:
                    self.cad_viewport.set_high_smooth(params['high_smooth'])
                else:
                    raise ValueError('Invalid CAD View request.')
            elif method == 'ui.panels.set':
                if (set(params) != {'panel', 'visible', 'session_id'} or type(params['visible']) is not bool
                        or type(params['panel']) is not str or params['session_id'] != self.session_id):
                    raise ValueError('Invalid panel request or expired Serpentine session.')
                dock = self._panel_docks().get(params['panel'])
                if dock is None:
                    raise ValueError('This Serpentine panel is unavailable.')
                dock.setVisible(params['visible'])
            elif not geometry_method and params != {}:
                raise ValueError("This method does not accept parameters.")
            data = (self.previews.sync(params) if method=='previews.sync' else self.points.dispatch(method, params)) if geometry_method else None
            result = self.summary()
            if data is not None:
                result["data"] = data
            return {"id": request_id, "result": result}
        except Exception as exc:
            return {"id": request_id, "error": str(exc),
                    "code": "operation_failed" if locals().get('geometry_method') or locals().get('method') == 'scene.link_graph' else "protocol"}


def _launch_editor(session_id):
    config = Path(__file__).with_name('_noodles_core') / 'editor-path.txt'
    if not config.is_file():
        raise RuntimeError('Run the NoodleS bridge installer to register the editor location.')
    root = Path(config.read_text(encoding='utf-8'))
    script = root / 'NoodleS.pyw'
    interpreter = root / '.venv' / 'Scripts' / 'pythonw.exe'
    if not root.is_absolute() or not script.is_file():
        raise RuntimeError('NoodleS was moved or removed. Reinstall the bridge from its current folder.')
    if not interpreter.is_file():
        raise RuntimeError('Prepare the NoodleS Python environment before opening the editor.')

    environment = os.environ.copy()
    for name in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM'):
        environment.pop(name, None)
    bundle = getattr(sys, '_MEIPASS', None)
    set_dll_directory = None
    if sys.platform == 'win32' and bundle:
        # A frozen Serpentine can point DLL and Qt plugin lookup at its own runtime.
        import ctypes

        bundle_path = Path(bundle)
        paths = environment.get('PATH', '').split(os.pathsep)
        environment['PATH'] = os.pathsep.join(
            entry for entry in paths if entry and not Path(entry.strip('"')).is_relative_to(bundle_path))
        set_dll_directory = ctypes.WinDLL('kernel32', use_last_error=True).SetDllDirectoryW
        set_dll_directory.argtypes = [ctypes.c_wchar_p]
        if not set_dll_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        subprocess.Popen([str(interpreter), '-E', str(script), '--bridge-session', session_id], cwd=root, env=environment,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        if set_dll_directory is not None:
            set_dll_directory(bundle)


def _core_package():
    return '..backend' if __package__ and __package__.startswith('noodles') else '_noodles_core'


def _register_commands(ctx):
    prefix = _core_package()
    for family in ('primitive_shapes', 'grid_native', 'scene_previews', 'operation_native', 'offset_native',
                   'placement_native', 'population_native', 'map_surface_native', 'tessellation_native',
                   'surface_structure_native', 'mesh_native', 'penrose_native', 'scene_ungroup'):
        importlib.import_module(f'{prefix}.{family}', __package__).register_commands(ctx)
    importlib.import_module(f'{prefix}.viewport_acceleration', __package__).install(ctx.window)

    @ctx.command('noodles', mutates=False, repeatable=False)
    def launch(c):
        try:
            _launch_editor(ctx.window._noodles_bridge.session_id)
        except (OSError, RuntimeError, UnicodeError) as exc:
            c.echo(f'Unable to open NoodleS. {exc}')
        else:
            c.echo('Starting NoodleS…')
        if False:
            yield

    @ctx.command('noodlesrefresh', mutates=False, repeatable=False)
    def command(c):
        refresh(ctx)
        c.echo('NoodleS adapter is up to date.')
        if False:
            yield


def _start(ctx, descriptor=None):
    bridge = BridgeServer(ctx, descriptor)
    bridge.start()
    ctx.window._noodles_bridge = bridge
    QtCore.QCoreApplication.instance().aboutToQuit.connect(bridge.stop)
    return bridge


def refresh(ctx):
    """Reload the installed modules without touching the active CAD document."""
    previous = getattr(ctx.window, '_noodles_bridge', None)
    if previous is not None and previous.code_digest == code_digest():
        return
    path = Path(__file__).resolve()
    spec = importlib.util.spec_from_file_location('serpentine3d_noodles_bridge_current', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    descriptor = previous.descriptor if previous is not None else None
    if previous is not None:
        previous.stop()
    module._start(ctx, descriptor)
    if previous is not None:
        previous.deleteLater()


def serpentine3d_plugin(ctx):
    if ctx.window is not None and getattr(ctx.window, '_noodles_bridge', None) is None:
        _start(ctx)
