import unittest,asyncio,time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app import create_app,check_greeting
from base.config import config
from tests.support import build_system,faq_row
class APITests(unittest.TestCase):
    def setUp(self):
        self.system=build_system(rows=[faq_row()])
        self.client=TestClient(create_app(self.system,allow_trace=True))
    def session(self):return self.client.post('/api/create_session').json()['session_id']
    def test_http_history(self):
        sid=self.session()
        r=self.client.post('/api/query',json={'query':'整存整取最低多少钱','session_id':sid}).json()
        self.assertEqual(r['channel'],'faq')
        self.assertEqual(len(self.client.get('/api/history/'+sid).json()['history']),1)
    def test_cross_owner_denied(self):
        sid=self.session();other=TestClient(create_app(self.system))
        self.assertEqual(other.get('/api/history/'+sid).status_code,403)
        self.assertEqual(other.delete('/api/history/'+sid).status_code,403)
        self.assertEqual(other.post('/api/query',json={'query':'存款','session_id':sid}).status_code,403)
    def test_ws_owned_and_refusal(self):
        sid=self.session()
        with self.client.websocket_connect('/api/stream') as ws:
            ws.send_json({'query':'推荐收益最高的存款','session_id':sid})
            frames=[]
            while True:
                f=ws.receive_json();frames.append(f)
                if f['type']=='end':break
        self.assertEqual(frames[-1]['decision'],'refused')
        self.assertIn(config.DISCLAIMER,frames[1]['token'])
    def test_ws_foreign_denied(self):
        sid=self.session();other=TestClient(create_app(self.system))
        with other.websocket_connect('/api/stream') as ws:
            ws.send_json({'query':'存款','session_id':sid})
            r=ws.receive_json()
            self.assertEqual(r['type'],'error');self.assertIn(config.DISCLAIMER,r['error'])
    def test_http_injection(self):
        r=self.client.post('/api/query',json={'query':'存款','source_filter':'faq" or true'})
        self.assertEqual(r.status_code,422);self.assertIn(config.DISCLAIMER,r.json()['answer'])
    def test_ws_injection(self):
        sid=self.session()
        with self.client.websocket_connect('/api/stream') as ws:
            ws.send_json({'query':'存款','source_filter':'faq" or true','session_id':sid})
            self.assertEqual(ws.receive_json()['type'],'error')
    def test_health_degraded(self):
        self.system.mysql_client.ok=False
        self.assertEqual(self.client.get('/health').status_code,503)
    def test_health_ready(self):
        self.assertEqual(self.client.get('/health').status_code,200)
    def test_trace_protected(self):
        c=TestClient(create_app(self.system))
        self.assertEqual(c.post('/api/query',json={'query':'存款','include_trace':True}).status_code,403)
    def test_trace_actual_context(self):
        r=self.client.post('/api/query',json={'query':'起存金额','include_trace':True}).json()
        self.assertEqual(r['contexts'][0]['doc_id'],r['citations'][0]['doc_id'])
    def test_greeting_fullmatch(self):
        self.assertIsNotNone(check_greeting('你好！'))
        self.assertIsNone(check_greeting('你好，我要投诉'))
    def test_event_loop_not_blocked(self):
        original=self.system.query_result
        from threading import Event
        started,finished=Event(),Event()
        def slow(*a,**kw):
            started.set();time.sleep(.4);r=original(*a,**kw);finished.set();return r
        self.system.query_result=slow
        with self.client:
            with ThreadPoolExecutor(1) as pool:
                future=pool.submit(self.client.post,'/api/query',json={'query':'起存金额'})
                self.assertTrue(started.wait(2))
                self.assertEqual(self.client.get('/health').status_code,200)
                self.assertFalse(finished.is_set())
                self.assertEqual(future.result().status_code,200)
if __name__=='__main__':unittest.main()
