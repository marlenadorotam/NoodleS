"""Preview queue coalescing, stop/start races and GUI delivery."""
import copy
import threading
import time
import unittest
from Qt import QtWidgets
from noodles.preview_service import PreviewService
from noodles.bridge import BridgeUnavailable


class PreviewServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(predicate())

    def test_latest_snapshot_replaces_intermediate_updates_and_delivers_on_qt(self):
        entered,release=threading.Event(),threading.Event()
        calls,deliveries=[],[]
        class Client:
            def call(self,method,frame):
                calls.append(copy.deepcopy(frame))
                if len(calls)==1:
                    entered.set()
                    release.wait(2)
                return {'data':{'state':'complete'}}
        service=PreviewService(client=Client())
        service.result.connect(lambda nodes,error:deliveries.append((nodes,error,threading.get_ident())))
        service.sync({'node':{'value':0}})
        service.start()
        try:
            self.wait(entered.is_set)
            for i in range(1,41):
                service.sync({'node':{'value':i}})
            release.set()
            self.wait(lambda:bool(deliveries))
            self.assertEqual(deliveries[-1][0],{'node':{'value':40}})
            self.assertEqual(deliveries[-1][2],threading.get_ident())
            self.assertEqual([c['nodes'] for c in calls],[ [{'value':0}],[{'value':40}] ])
        finally:
            release.set()
            service.stop()
        self.wait(lambda:bool(calls and calls[-1]['nodes']==[]))

    def test_reconnect_replay_supersedes_old_workers_late_release(self):
        entered,release=threading.Event(),threading.Event()
        calls=[]
        class Client:
            def call(self,method,frame):
                if not entered.is_set():
                    entered.set()
                    release.wait(2)
                calls.append(copy.deepcopy(frame))
                return {'data':{'state':'complete'}}
        service=PreviewService(client=Client())
        service.sync({'node':{'value':1}})
        service.start()
        try:
            self.wait(entered.is_set)
            service.stop()
            old_release=service.revision
            service.start()
            self.wait(lambda:bool(calls))
            self.assertGreater(calls[-1]['revision'],old_release)
            release.set()
            self.wait(lambda:any(c['revision']==old_release and not c['nodes'] for c in calls))
            # Native adapter rejects the late lower revision; desired replay remains latest.
            latest=max(calls,key=lambda c:c['revision'])
            self.assertEqual(latest['nodes'],[{'value':1}])
        finally:
            release.set()
            service.stop()

    def test_transport_failure_retries_latest_and_stale_errors_do_not_replace_status(self):
        calls=[]
        class Client:
            def call(self,method,frame):
                calls.append(copy.deepcopy(frame))
                if len(calls)==1:
                    raise BridgeUnavailable('temporarily disconnected')
                return {'data':{'state':'complete'}}
        service=PreviewService(client=Client())
        delivered=[]
        service.result.connect(lambda nodes,error:delivered.append(error))
        service.sync({'node':{'value':3}})
        service.start()
        try:
            self.wait(lambda:len(delivered)>=2)
            self.assertEqual(delivered[-1],'')
            self.assertEqual(calls[0],calls[1])
        finally:
            service.stop()
