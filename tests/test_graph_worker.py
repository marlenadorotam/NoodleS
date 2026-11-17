"""Coalescing/data-thread isolation, real Qt scheduling and safe shutdown."""
import threading
import time
import unittest
from types import SimpleNamespace
from Qt import QtCore,QtWidgets
from noodles.evaluation import GraphWorker


class GraphWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait(self,condition):
        end=time.monotonic()+3
        while not condition() and time.monotonic()<end:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(condition())

    def test_only_latest_snapshot_publishes_and_qt_runs_while_worker_waits(self):
        calls,threads,ready,ticks=[],[],[],[]
        gate=threading.Event()
        def evaluate(snapshot):
            calls.append(snapshot)
            threads.append(threading.get_ident())
            if snapshot=='first':
                gate.wait(2)
            return snapshot
        worker=GraphWorker(SimpleNamespace(evaluate=evaluate))
        worker.ready.connect(ready.append)
        timer=QtCore.QTimer()
        timer.setInterval(2)
        timer.timeout.connect(lambda:ticks.append(1))
        timer.start()
        try:
            worker.request('first')
            self.wait(lambda:bool(calls))
            worker.request('discarded')
            worker.request('latest')
            self.wait(lambda:len(ticks)>=3)
            self.assertFalse(ready)
            gate.set()
            self.wait(lambda:ready==['latest'])
            self.assertEqual(calls,['first','latest'])
            self.assertTrue(all(t!=threading.get_ident() for t in threads))
        finally:
            gate.set()
            timer.stop()
            worker.stop()

    def test_edit_invalidates_an_already_running_result_and_close_drops_work(self):
        gate=threading.Event()
        entered=threading.Event()
        def evaluate(snapshot):
            entered.set()
            gate.wait(2)
            return snapshot
        ready=[]
        worker=GraphWorker(SimpleNamespace(evaluate=evaluate))
        worker.ready.connect(ready.append)
        worker.request('stale')
        self.wait(entered.is_set)
        worker.invalidate()
        worker.request('pending')
        worker.stop()
        gate.set()
        self.wait(lambda:not worker.running or worker.stopped)
        self.app.processEvents()
        self.assertFalse(ready)
