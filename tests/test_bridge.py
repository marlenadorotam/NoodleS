"""Connection tests with real localhost sockets and the real Qt plugin server."""
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

os.environ["QT_PREFERRED_BINDING"] = "PySide6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from Qt import QtCore, QtWidgets
from PySide6.QtTest import QTest
from noodles import __version__
from noodles.bridge import BridgeClient, BridgeProtocolError, BridgeReplyTimeout, BridgeUnavailable, MAX_FRAME
from noodles.connection import SerpentineConnection
from noodles.install_bridge import install
from noodles.serpentine_plugin.NoodleSBridge import BridgeServer


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        output = Path(__file__).resolve().parents[1] / ".test-output"
        output.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=output)
        self.path = Path(self.folder.name) / "bridge.json"
        self.window = QtWidgets.QWidget()
        self.window.ctx = SimpleNamespace(current_path=None)
        self.window.processor = SimpleNamespace(busy=False)
        self.ctx = SimpleNamespace(window=self.window, version="0.12.2",
                                   scene=SimpleNamespace(revision=0, objects={}))
        self.server = BridgeServer(self.ctx, self.path)
        self.server.start()
        self.client = BridgeClient(self.path, timeout=0.4)
        self.controllers = []

    def tearDown(self):
        for controller in self.controllers:
            controller.stop()
        self.server.stop()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def wait_for(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertTrue(predicate(), "Condition did not become true in time.")

    def run_call(self, fn):
        result = {}
        def invoke():
            try:
                result["value"] = fn()
            except Exception as exc:
                result["error"] = exc
        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()
        self.wait_for(lambda: not thread.is_alive())
        if "error" in result:
            raise result["error"]
        return result["value"]

    def raw_request(self, **changes):
        request = {"id": "test", "method": "hello", "protocol": 1,
                   "token": self.server.token, "params": {}}
        request.update(changes)
        return self.server.handle_line(json.dumps(request).encode())

    def test_toolbar_buttons_sync_native_dock_visibility_over_real_socket(self):
        from noodles.window import MainWindow

        host = QtWidgets.QMainWindow(self.window)
        docks = {}
        for panel in ('properties', 'layers'):
            dock = QtWidgets.QDockWidget(panel.title(), host)
            dock.setObjectName(panel + 'Dock')
            dock.setWidget(QtWidgets.QLabel(panel))
            host.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            docks[panel] = dock
        host.show()
        editor = MainWindow()
        editor.serpentine.client = self.client
        editor.serpentine.interval = .02
        editor.show()
        try:
            properties, layers = editor.s3d_panel_buttons.values()
            self.assertFalse(properties.isEnabled())
            editor.serpentine.start()
            self.wait_for(lambda: properties.isEnabled() and properties.isChecked() and layers.isChecked())
            self.assertLess(properties.x(), layers.x())
            self.assertLess(layers.x(), editor.library_button.x())
            for button in (properties, layers):
                self.assertEqual(button.grab().toImage().pixelColor(8, button.height() // 2).name(), '#5c3921')
            rejected = self.raw_request(method='ui.panels.set',
                params={'session_id': 'expired', 'panel': 'properties', 'visible': False})
            self.assertIn('error', rejected)
            self.assertFalse(docks['properties'].isHidden())
            QTest.mouseClick(properties, QtCore.Qt.LeftButton)
            self.wait_for(lambda: properties.isEnabled() and not properties.isChecked() and docks['properties'].isHidden())
            self.assertFalse(docks['layers'].isHidden())
            self.assertTrue(editor.properties_button.isChecked())
            QTest.mouseClick(properties, QtCore.Qt.LeftButton)
            self.wait_for(lambda: properties.isEnabled() and properties.isChecked() and docks['properties'].isVisible())
            docks['layers'].close()
            self.wait_for(lambda: not layers.isChecked())
            QTest.mouseClick(layers, QtCore.Qt.LeftButton)
            self.wait_for(lambda: layers.isEnabled() and layers.isChecked() and docks['layers'].isVisible())
            self.assertTrue(editor.library_button.isChecked())
            self.assertTrue(editor.graph.undo_stack().isClean())
            self.assertEqual(self.ctx.scene.revision, 0)
            editor.serpentine.stop()
            self.assertFalse(properties.isEnabled())
            self.assertFalse(properties.isChecked())
        finally:
            editor.close()
            host.close()

    def test_handshake_and_status_over_real_socket(self):
        info = self.run_call(self.client.call)
        self.assertEqual(info["serpentine_version"], "0.12.2")
        self.assertEqual(info["plugin_version"], __version__)
        self.assertEqual(info["session_id"], self.server.session_id)
        self.assertEqual(info["scene"], {"revision": 0, "object_count": 0, "path": None, "busy": False})
        self.ctx.scene.revision = 7
        self.ctx.scene.objects["test"] = object()
        self.window.ctx.current_path = Path("drawing.serp")
        self.window.processor.busy = True
        info = self.run_call(lambda: self.client.call("status"))
        self.assertEqual(info["scene"], {"revision": 7, "object_count": 1, "path": "drawing.serp", "busy": True})

    def test_status_uses_current_scene_and_does_not_enumerate_geometry(self):
        class MetadataOnly(dict):
            def values(self):
                raise AssertionError("Geometry must not be enumerated for a heartbeat.")
        self.ctx.scene = SimpleNamespace(revision=19, objects=MetadataOnly({"a": object()}))
        info = self.run_call(lambda: self.client.call("status"))
        self.assertEqual(info["scene"]["revision"], 19)
        self.assertEqual(info["scene"]["object_count"], 1)

    def test_server_rejects_bad_token_protocol_and_arbitrary_commands(self):
        for changes in ({"token": "wrong"}, {"protocol": 9}, {"protocol": True},
                        {"method": "command"}, {"method": "exec"}, {"method": "noodles"},
                        {"params": {"code": "x"}}, {"id": None}):
            self.assertIn("error", self.raw_request(**changes))
        self.assertIn("error", self.server.handle_line(b"not json"))
        self.assertIn("error", self.server.handle_line(b"[]"))

    def test_client_rejects_missing_invalid_and_remote_descriptors(self):
        record = json.loads(self.path.read_text())
        self.path.unlink()
        with self.assertRaises(BridgeUnavailable):
            self.client.call()
        for changes in ({"host": "example.com"}, {"port": True}, {"port": 70000}, {"token": ""}):
            self.path.write_text(json.dumps({**record, **changes}))
            with self.assertRaises(BridgeUnavailable):
                self.client.call()
        self.path.write_text(json.dumps({**record, "protocol": 2}))
        with self.assertRaises(BridgeProtocolError):
            self.client.call()

    def test_monitor_connects_disconnects_and_recovers_without_blocking_ui(self):
        controller = SerpentineConnection(client=self.client, interval=0.02)
        self.controllers.append(controller)
        delivered_on = []
        controller.changed.connect(lambda *_: delivered_on.append(threading.get_ident()))
        controller.start()
        self.wait_for(lambda: controller.state == "connected")
        self.server.stop()
        self.wait_for(lambda: controller.state == "disconnected")
        self.server = BridgeServer(self.ctx, self.path)
        self.server.start()
        self.wait_for(lambda: controller.state == "connected")
        self.assertEqual(controller.info["session_id"], self.server.session_id)
        self.assertEqual(set(delivered_on), {threading.get_ident()})
        controller.stop()
        self.assertIsNone(controller.info)
        self.assertEqual(controller.state, "disconnected")

    def test_manual_disconnect_discards_late_reply(self):
        pending = threading.Event()
        release = threading.Event()
        info = self.server.summary()
        class DelayedClient:
            def call(self, method):
                pending.set()
                release.wait(1)
                return info
        controller = SerpentineConnection(client=DelayedClient(), interval=0.02)
        self.controllers.append(controller)
        controller.start()
        self.wait_for(pending.is_set)
        generation = controller._generation
        controller.stop()
        release.set()
        controller._deliver(generation, "connected", info)
        self.app.processEvents()
        self.assertEqual(controller.state, "disconnected")
        self.assertIsNone(controller.info)

    def test_manual_reconnect_for_unlinked_graph_prefers_live_pinned_session(self):
        client = BridgeClient(self.path, timeout=0.4, discover=True)
        controller = SerpentineConnection(client=client, interval=0.02)
        self.controllers.append(controller)
        controller.start()
        self.wait_for(lambda: controller.state == "connected")
        other = BridgeServer(self.ctx, self.path)
        try:
            other.start()
            controller.reconnect()
            self.wait_for(lambda: controller.state == "connected")
            self.assertEqual(controller.info["session_id"], self.server.session_id)
            self.server.stop()
            self.wait_for(lambda: controller.state == "disconnected")
            controller.reconnect()
            self.wait_for(lambda: controller.state == "connected")
            self.assertEqual(controller.info["session_id"], other.session_id)
        finally:
            other.stop()

    def test_monitor_tolerates_two_missed_replies_and_recovers_after_three(self):
        from queue import Queue, Empty

        responses = Queue()
        info = self.server.summary()

        class ScriptedClient:
            def call(self, method):
                try:
                    reply = responses.get(timeout=.5)
                except Empty:
                    raise BridgeReplyTimeout("No status reply.")
                if isinstance(reply, Exception):
                    raise reply
                return reply

        controller = SerpentineConnection(client=ScriptedClient(), interval=.02)
        self.controllers.append(controller)
        states = []
        controller.changed.connect(lambda state, _: states.append(state))
        responses.put(info)
        controller.start()
        self.wait_for(lambda: controller.state == "connected")

        for _ in range(2):
            responses.put(BridgeReplyTimeout("No status reply."))
        responses.put({**info, "scene": {**info["scene"], "revision": 1}})
        self.wait_for(lambda: controller.info and controller.info["scene"]["revision"] == 1)
        self.assertEqual(states, ["connecting", "connected", "connected"])

        for _ in range(3):
            responses.put(BridgeReplyTimeout("No status reply."))
        self.wait_for(lambda: controller.state == "disconnected")
        responses.put(info)
        self.wait_for(lambda: controller.state == "connected")

    def test_slow_reply_does_not_block_qt_events(self):
        release = threading.Event()
        info = self.server.summary()
        class SlowClient:
            def call(self, method):
                release.wait(1)
                return info
        controller = SerpentineConnection(client=SlowClient(), interval=0.02)
        self.controllers.append(controller)
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        try:
            controller.start()
            self.wait_for(lambda: len(ticks) >= 5)
            self.assertEqual(controller.state, "connecting")
            release.set()
            self.wait_for(lambda: controller.state == "connected")
        finally:
            release.set()
            timer.stop()

    def test_status_button_and_reconnect_leave_graph_unchanged(self):
        from noodles.window import MainWindow
        window = MainWindow()
        try:
            before = window.graph.serialize_session()
            window.serpentine.client = self.client
            window.point_service.client = self.client
            window.serpentine.interval = 0.02
            window.serpentine.start()
            self.wait_for(lambda: window.serpentine.state == "connected")
            self.assertIn("Connected", window.connection_status.text())
            self.assertIn("Serpentine3D 0.12.2", window.connection_status.toolTip())
            self.assertIn(f"NoodleSBridge {__version__}", window.connection_status.toolTip())
            window.serpentine.stop()
            self.assertIn("Disconnected", window.connection_status.text())
            window.connection_status.click()
            self.wait_for(lambda: window.serpentine.state == "connected")
            self.assertEqual(window.graph.serialize_session(), before)
            self.assertTrue(window.graph.undo_stack().isClean())
        finally:
            window.graph.undo_stack().setClean()
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_installer_is_idempotent_and_preserves_existing_plugin(self):
        directory = Path(self.folder.name) / "plugins"
        target = install(directory)
        runtime = directory / "_noodles_core"
        project_root = Path(__file__).resolve().parents[1]
        launcher = runtime / "editor-path.txt"
        self.assertEqual(Path(launcher.read_text(encoding="utf-8")), project_root)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            self.assertEqual((runtime / name).read_bytes(), (project_root / name).read_bytes())
        expected = target.read_bytes()
        install(directory)
        self.assertEqual(list(directory.glob("*.bak")), [])
        target.write_text("# old plugin")
        (runtime / "THIRD_PARTY_NOTICES.md").write_bytes(b"stale notice")
        install(directory)
        backups = list(directory.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "# old plugin")
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual((runtime / "THIRD_PARTY_NOTICES.md").read_bytes(),
                         (project_root / "THIRD_PARTY_NOTICES.md").read_bytes())

    def test_stop_does_not_delete_another_sessions_descriptor(self):
        other = BridgeServer(self.ctx, self.path)
        try:
            other.start()
            self.server.stop()
            self.assertEqual(json.loads(self.path.read_text())["session_id"], other.session_id)
        finally:
            other.stop()

    def fake_response(self, responder):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        record = json.loads(self.path.read_text())
        record["port"] = listener.getsockname()[1]
        self.path.write_text(json.dumps(record))
        def serve():
            with listener:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(1)
                    request = bytearray()
                    while b"\n" not in request:
                        request.extend(connection.recv(8192))
                    try:
                        responder(connection, json.loads(request))
                    except (ConnectionError, OSError):
                        pass
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        return thread

    def test_fragmented_response_is_assembled(self):
        def respond(connection, request):
            raw = json.dumps({"id": request["id"], "result": self.server.summary()}).encode() + b"\n"
            connection.sendall(raw[:17])
            time.sleep(0.01)
            connection.sendall(raw[17:])
        thread = self.fake_response(respond)
        self.assertEqual(self.client.call()["application"], "Serpentine3D")
        thread.join(1)

    def test_mismatched_response_is_rejected(self):
        thread = self.fake_response(lambda c, r: c.sendall(b'{"id":"wrong","result":{}}\n'))
        with self.assertRaises(BridgeProtocolError):
            self.client.call()
        thread.join(1)

    def test_oversized_response_is_rejected(self):
        thread = self.fake_response(lambda c, r: c.sendall(b"x" * (MAX_FRAME + 1)))
        with self.assertRaises(BridgeProtocolError):
            self.client.call()
        thread.join(1)

    def test_total_deadline_prevents_a_slow_response_from_hanging(self):
        def respond(connection, request):
            for _ in range(100):
                connection.sendall(b" ")
                time.sleep(0.02)
        thread = self.fake_response(respond)
        self.client.timeout = 0.08
        start = time.monotonic()
        with self.assertRaises(BridgeUnavailable):
            self.client.call()
        self.assertLess(time.monotonic() - start, 0.5)
        thread.join(1)


if __name__ == "__main__":
    unittest.main()
