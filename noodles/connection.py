"""Asynchronous connection supervision; networking never runs in the UI thread."""
from __future__ import annotations

import threading

from Qt import QtCore

from .bridge import BridgeClient, BridgeError, BridgeProtocolError, BridgeReplyTimeout, BridgeUnavailable


REPLY_TIMEOUT_GRACE = 3


class SerpentineConnection(QtCore.QObject):
    changed = QtCore.Signal(str, object)
    _received = QtCore.Signal(int, str, object)

    def __init__(self, parent=None, client=None, interval=1.0, *, session_id=None):
        super().__init__(parent)
        self.client = client or BridgeClient()
        self.interval = interval
        self.state = "disconnected"
        self.info = None
        self._generation = 0
        self._stop = None
        self._last_payload = None
        self._session_id = session_id
        self.graph_target = None
        self._received.connect(self._deliver)

    def start(self, *, allow_new_session=False):
        if self._stop is not None and not self._stop.is_set():
            return
        self._start_monitor(connecting=True, allow_new_session=allow_new_session)

    def _start_monitor(self, *, connecting=False, allow_new_session=False):
        self._generation += 1
        self._stop = threading.Event()
        if connecting:
            self._deliver(self._generation, "connecting", {"message": "Looking for Serpentine3D…"})
        thread = threading.Thread(target=self._monitor, args=(self._generation, self._stop, allow_new_session),
                                  name="NoodleS-Serpentine", daemon=True)
        thread.start()

    def stop(self):
        if self._stop is not None:
            self._stop.set()
        self._generation += 1
        self._deliver(self._generation, "disconnected", {"message": "Automatic connection is paused. Click to reconnect."})

    def reconnect(self):
        self.stop()
        self.start(allow_new_session=True)

    def client_for_session(self, session_id):
        if session_id and getattr(self.client, "discover", False):
            return self.client.for_session(session_id)
        return self.client

    def observe_status(self, payload):
        session_id = payload["session_id"]
        if getattr(self.client, "discover", False) and session_id != self._session_id:
            self._session_id = session_id
            if self._stop is not None and not self._stop.is_set():
                self._stop.set()
                self._start_monitor()
        self._deliver(self._generation, 'connected', payload)

    @QtCore.Slot(int, str, object)
    def _deliver(self, generation, state, payload):
        if generation != self._generation:
            return  # Discard late replies from a stopped/replaced connection.
        if state == self.state and payload == self._last_payload:
            return  # Healthy heartbeats do not need to repaint/restyle the GUI.
        if state == "connected" and getattr(self.client, "discover", False):
            self._session_id = payload["session_id"]
        self.state = state
        self.info = payload if state == "connected" else None
        self._last_payload = payload
        self.changed.emit(state, payload)

    def _monitor(self, generation, stop, allow_new_session):
        client = self.client_for_session(self._session_id)
        discover = getattr(client, "discover", False)
        connected = False
        reply_timeouts = 0
        delay = self.interval
        while not stop.is_set():
            try:
                method = "status" if connected else "hello"
                if discover:
                    target = self.graph_target
                    try:
                        info = (client.find_scene(*target) if target and not client.session_id
                                else client.read_status(method))
                        if info is None:
                            raise BridgeUnavailable("Open the linked Serpentine document to resume scene updates.")
                    except BridgeUnavailable as exc:
                        if connected or isinstance(exc, BridgeReplyTimeout) or not client.session_id:
                            raise
                        if target:
                            info = client.find_scene(*target)
                            if info is None:
                                raise
                        elif allow_new_session:
                            info = self.client.read_status(method)
                        else:
                            raise
                    client = client.for_session(info["session_id"])
                else:
                    info = client.call(method)
                state, payload = "connected", info
                allow_new_session = False
                connected = True
                reply_timeouts = 0
                delay = self.interval
            except BridgeError as exc:
                if connected and isinstance(exc, BridgeReplyTimeout):
                    reply_timeouts += 1
                    if reply_timeouts < REPLY_TIMEOUT_GRACE:
                        # Serpentine's Qt thread can be temporarily occupied by
                        # CAD work even though its socket is still accepting requests.
                        stop.wait(self.interval)
                        continue
                state = "incompatible" if isinstance(exc, BridgeProtocolError) else "disconnected"
                payload = {"message": str(exc)}
                connected = False
                reply_timeouts = 0
                delay = min(max(self.interval, delay * 2), 5.0)
            if stop.is_set():
                return
            try:
                self._received.emit(generation, state, payload)
            except RuntimeError:
                return  # The window was destroyed while a bounded request was in flight.
            stop.wait(delay)
