"""Latest complete preview frame, bounded retries and leases off the Qt thread."""
import copy
import threading
import uuid
from Qt import QtCore
from .bridge import BridgeClient,BridgeError


class PreviewService(QtCore.QObject):
    result=QtCore.Signal(object,str)
    delivered=QtCore.Signal(int,object,str)

    def __init__(self,parent=None,client=None):
        super().__init__(parent)
        self.client=client or BridgeClient(timeout=2)
        self.client_uuid=str(uuid.uuid4())
        self.nodes={}
        self.revision=0
        self.generation=0
        self.active=False
        self.condition=threading.Condition()
        self.stop_event=None
        self.delivered.connect(self._receive)

    def _receive(self,generation,nodes,error):
        if generation==self.generation and self.active and nodes==self.nodes:
            self.result.emit(nodes,error)

    def sync(self,nodes):
        with self.condition:
            if nodes==self.nodes:
                return
            self.nodes=copy.deepcopy(nodes)
            self.revision+=1
            self.condition.notify_all()

    def start(self, scene_scope=None):
        if self.active:
            return
        self.active=True
        self.generation+=1
        with self.condition:
            self.revision+=1  # New replay must supersede the previous worker's release.
        self.stop_event=threading.Event()
        client = self.client.for_scene(scene_scope) if scene_scope else self.client
        threading.Thread(target=self._work,args=(self.generation,self.stop_event,client),daemon=True,name='NoodleS-Preview').start()

    def stop(self):
        if not self.active:
            return
        self.active=False
        self.generation+=1
        with self.condition:
            self.revision+=1
            self.stop_event.release_revision=self.revision
            self.stop_event.set()
            self.condition.notify_all()

    def _frame(self,revision,nodes):
        return {'schema':1,'client_uuid':self.client_uuid,'revision':revision,'nodes':list(nodes.values())}

    def _work(self,generation,stop,client):
        seen=None
        try:
            while not stop.is_set():
                with self.condition:
                    revision,nodes=self.revision,copy.deepcopy(self.nodes)
                error=''
                try:
                    client.call('previews.sync',self._frame(revision,nodes))
                except BridgeError as exc:
                    error=str(exc)
                if seen!=(revision,error):
                    try:
                        self.delivered.emit(generation,nodes,error)
                    except RuntimeError:
                        return
                    seen=(revision,error)
                with self.condition:
                    if self.revision==revision and not stop.is_set():
                        self.condition.wait(.25 if error else 2.)
        finally:
            try:
                client.call('previews.sync',self._frame(stop.release_revision,{}))
            except (BridgeError,AttributeError):
                pass  # Native leases also remove overlays after a killed editor.
