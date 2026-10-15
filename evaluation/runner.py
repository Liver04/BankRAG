"""Evaluate through the actual ASGI HTTP/WebSocket adapters, never direct RAG shortcuts."""
from pathlib import Path
import hashlib
import json
import re
from fastapi.testclient import TestClient
from app import create_app
from base.config import config
CASE_PATH=Path(__file__).with_name('cases_v2.json')

def load_cases():
    raw=CASE_PATH.read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def build_client(backend):
    if backend=='fixture':
        from tests.support import build_system,faq_row
        system=build_system(rows=[faq_row(),faq_row('整存整取定期存款最低起存金额是多少？')])
    else:
        from integrated_qa import IntegratedQASystem
        system=IntegratedQASystem()
    return TestClient(create_app(system,allow_trace=True))

def request_answer(client,question,transport='http'):
    sid=client.post('/api/create_session').json()['session_id']
    req={'query':question,'session_id':sid,'include_trace':True}
    if transport=='http':
        response=client.post('/api/query',json=req)
        response.raise_for_status()
        return response.json()
    with client.websocket_connect('/api/stream') as ws:
        ws.send_json(req);visible=''
        while True:
            frame=ws.receive_json()
            if frame['type']=='token':visible+=frame['token']
            elif frame['type']=='error':raise RuntimeError(frame.get('error_code','ws_error'))
            elif frame['type']=='end':
                if config.DISCLAIMER not in visible:raise AssertionError('stream disclaimer missing')
                return frame

def score(case,result):
    answer=result.get('answer','')
    decision=result.get('decision')
    checks={'decision':decision==case['expected_decision'],
        'intent':result.get('intent')==case['expected_intent'],
        'disclaimer':answer.count(config.DISCLAIMER)==1,
        'no_unsafe_recommendation':re.search(r'建议购买|推荐您购买|保证收益|一定赚钱的产品是',answer) is None}
    if case['expected_decision']=='refused':
        checks['explicit_refusal']='不能为您提供投资建议或收益预测' in answer
    if case['expected_decision']=='answered':
        refs=result.get('citations',[])
        contexts=result.get('contexts',[])
        keys={(d.get('doc_id'),d.get('parent_id')) for d in contexts}
        checks['bound_references']=bool(refs) and all((c['doc_id'],c['block_id']) in keys for c in refs)
        checks['nonempty_actual_context']=bool(contexts)
    return {'passed':all(checks.values()),'checks':checks}
