"""One coalescing worker for large data graphs; snapshots contain no Qt items."""
from concurrent.futures import ThreadPoolExecutor
from Qt import QtCore


class GraphWorker(QtCore.QObject):
    completed=QtCore.Signal(int,object,object)
    ready=QtCore.Signal(object)
    failed=QtCore.Signal(str)

    def __init__(self,engine,parent=None):
        super().__init__(parent)
        self.engine=engine
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='NoodleS-Data')
        self.generation=0
        self.running=False
        self.pending=None
        self.stopped=False
        self.completed.connect(self._completed,QtCore.Qt.QueuedConnection)

    def invalidate(self):
        self.generation+=1

    def request(self,snapshot):
        self.invalidate()
        self.pending=(self.generation,snapshot)
        if not self.running:
            self._start()

    def _start(self):
        token,snapshot=self.pending
        self.pending=None
        self.running=True
        future=self.pool.submit(self.engine.evaluate,snapshot)
        def finished(task):
            result,error=None,None
            try:
                result=task.result()
            except Exception as exc:
                error=str(exc)
            if not self.stopped:
                try:
                    self.completed.emit(token,result,error)
                except RuntimeError:
                    pass  # Parent was closed while the pure data worker finished.
        future.add_done_callback(finished)

    @QtCore.Slot(int,object,object)
    def _completed(self,token,result,error):
        self.running=False
        if self.stopped:
            return
        if token==self.generation:
            self.failed.emit(error) if error else self.ready.emit(result)
        if self.pending is not None:
            self._start()

    def stop(self):
        self.stopped=True
        self.invalidate()
        self.pending=None
        self.pool.shutdown(wait=False,cancel_futures=True)
