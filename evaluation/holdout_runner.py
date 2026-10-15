"""First-attempt route traces. Same-case history is real, HTTP/WS sessions are separate.

Formal mode requires independent human gold approval; diagnostic mode is explicit.
No expected answers/labels are ever sent to the answer-generating model.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

PROJECT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def load_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]


def dump(path, obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def load_pack(pack, mode):
    pack = Path(pack)
    manifest = json.loads((pack/'manifest.json').read_text(encoding='utf-8'))
    for rel,h in manifest['artifacts_sha256'].items():
        path = (PROJECT/rel).resolve()
        if not path.is_relative_to(PROJECT.resolve()) or not path.is_file() or digest(path)!=h:
            raise ValueError('holdout_artifact_changed:'+rel)
    questions = load_jsonl(pack/'questions.jsonl')
    gold = load_jsonl(pack/'answer_key.jsonl')
    if mode == 'formal' and any(c.get('gold_status')!='approved_independent_human_review' for c in gold):
        raise ValueError('independent_human_gold_approval_required; use explicit diagnostic mode for provisional study')
    if len(questions)!=len(gold) or any(q['case_id']!=g['case_id'] for q,g in zip(questions,gold)):
        raise ValueError('question_gold_identity_mismatch')
    for q,g in zip(questions,gold):
        if q['turns'] != [{k:t[k] for k in ('turn_id','question','source_filter')} for t in g['turns']]:
            raise ValueError('question_gold_payload_mismatch')
    return manifest,questions,gold


def trace_turn(client, turn, sid, transport, disclaimer):
    req={'query':turn['question'],'source_filter':turn.get('source_filter'),
         'session_id':sid,'include_trace':True}
    start=time.perf_counter()
    row={'turn_id':turn['turn_id'],'question':turn['question'],'source_filter':turn.get('source_filter'),
         'session_id':sid,'transport':transport,'request':req,'frames':[], 'result':None,
         'http_status':None,'transport_error':None,'first_token_seconds':None,
         'first_body_seconds':None,'actual_visible_text':''}
    try:
        if transport=='http':
            r=client.post('/api/query',json=req)
            row['http_status']=r.status_code
            row['result']=r.json()
            row['actual_visible_text']=row['result'].get('answer','')
        else:
            with client.websocket_connect('/api/stream') as ws:
                ws.send_json(req)
                while True:
                    f=ws.receive_json();elapsed=time.perf_counter()-start
                    row['frames'].append({'elapsed_seconds':elapsed,**f})
                    if f['type']=='token':
                        row['actual_visible_text']+=f['token']
                        if row['first_token_seconds'] is None:row['first_token_seconds']=elapsed
                        if f['token'].replace(disclaimer,'').strip() and row['first_body_seconds'] is None:row['first_body_seconds']=elapsed
                    if f['type'] in ('end','error'):
                        row['result']=f
                        if f['type']=='error':row['transport_error']=f.get('error_code','ws_error')
                        break
        history=client.get('/api/history/'+sid)
        row['history_status']=history.status_code
        row['history_after']=history.json().get('history',[])
    except Exception as exc:
        row['transport_error']=type(exc).__name__  # No SDK exception bodies or credentials.
    row['elapsed_seconds']=time.perf_counter()-start
    return row


def protocol_checks(row, disclaimer):
    result=row.get('result') or {}
    answer=result.get('answer') or result.get('error') or ''
    contexts=result.get('contexts',[]);refs=result.get('citations',[])
    context_keys={(d.get('doc_id'),d.get('parent_id') or d.get('block_id'),d.get('version')) for d in contexts}
    bound=bool(refs) and all((c.get('doc_id'),c.get('block_id'),c.get('version')) in context_keys for c in refs)
    checks={'transport_completed':not row['transport_error'] and (row['http_status']==200 if row['transport']=='http' else result.get('type')=='end'),
            'final_disclaimer_once':answer.count(disclaimer)==1,
            'no_generation_error':result.get('decision')!='error',
            'history_saved':row.get('history_status')==200 and bool(row.get('history_after')),
            'citation_bindings_valid':bound if refs else None,
            'answered_has_citations':bool(refs) if result.get('decision')=='answered' else None,
            'context_count':len(contexts),'citation_count':len(refs)}
    if row['transport']=='websocket':
        tokens=[f for f in row['frames'] if f['type']=='token']
        checks['early_disclaimer']=bool(tokens) and disclaimer in tokens[0]['token']
        checks['visible_disclaimer_once']=row['actual_visible_text'].count(disclaimer)==1
        body=lambda t:t.replace(disclaimer,'').strip()
        checks['visible_body_matches_final']=body(row['actual_visible_text'])==body(answer)
    return checks


def run_routes(client, cases, transports, disclaimer, output_row, workers=1):
    """Output every attempt, including failure; no retries or cherry-picking."""
    def scenario(case,transport):
        response=client.post('/api/create_session')
        response.raise_for_status();sid=response.json()['session_id']
        rows=[]
        for index,turn in enumerate(case['turns'],1):
            row=trace_turn(client,turn,sid,transport,disclaimer)
            row.update(case_id=case['case_id'],category=case['category'],turn_index=index)
            row['protocol']=protocol_checks(row,disclaimer)
            row['protocol']['history_round_count_correct']=len(row.get('history_after',[]))==index
            output_row(row);rows.append(row)
        return rows
    # Establish the owner cookie before concurrent session creation.
    client.post('/api/create_session').raise_for_status()
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(scenario,c,t):(c,t) for t in transports for c in cases}
        for f in as_completed(futures):
            case,transport=futures[f]
            try:rows.extend(f.result())
            except Exception as exc:
                for i,turn in enumerate(case['turns'],1):
                    row=dict(case_id=case['case_id'],category=case['category'],turn_id=turn['turn_id'],
                        question=turn['question'],source_filter=turn.get('source_filter'),transport=transport,
                        session_id=None,turn_index=i,result=None,frames=[],actual_visible_text='',
                        transport_error=type(exc).__name__,http_status=None,elapsed_seconds=None,protocol={'transport_completed':False})
                    output_row(row);rows.append(row)
    return sorted(rows,key=lambda r:(r['transport'],r['case_id'],r['turn_index']))


def snapshot_runtime(qa):
    from base.config import config
    files={}
    for pat in ['*.py','base/*.py','mysql_qa/**/*.py','rag_qa/core/*.py','config.ini','requirements.txt']:
        for p in PROJECT.glob(pat):files[p.relative_to(PROJECT).as_posix()]=digest(p)
    for rel in ['config.json','model.safetensors']:
        p=Path(config.MODELS_DIR)/'finance_intent_classifier'/rel
        if p.exists():files['bert/'+rel]=digest(p)
    v=qa.rag_system.vector_store
    alias=v.client.describe_alias(v.alias)
    return {'runtime_files_sha256':files,'faq_revision':qa.mysql_client.knowledge_version(),
            'milvus_alias':v.alias,'milvus_collection':alias.get('collection_name'),
            'milvus_row_count':v.client.get_collection_stats(alias['collection_name']).get('row_count'),
            'generation_model':config.LLM_MODEL,'model_temperature':0,
            'provider_timeout_seconds':60,'provider_retries':0,
            'embedding':'local bge-m3','reranker':'local bge-reranker-large',
            'retrieval_k':config.RETRIEVAL_K,'candidate_m':config.CANDIDATE_M,'rerank_threshold':config.RERANK_THRESHOLD,
            'catalog_sha256':digest(PROJECT/'rag_qa/data/finance/knowledge_catalog.json'),
            'faq_row_registry_sha256':digest(PROJECT/'rag_qa/data/finance/faq_review_registry.json')}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pack',type=Path,default=PROJECT/'evaluation/holdout_v1_1')
    p.add_argument('--mode',choices=['formal','diagnostic'],default='formal')
    p.add_argument('--transport',choices=['http','websocket','both'],default='both')
    p.add_argument('--workers',type=int,choices=[1,2],default=1)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    manifest,cases,gold=load_pack(args.pack,args.mode)
    out=args.output_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)  # Never overwrite a first-attempt run.
    transports=['http','websocket'] if args.transport=='both' else [args.transport]
    report={'schema_version':1,'dataset_version':manifest['dataset_version'],
        'questions_sha256':digest(args.pack/'questions.jsonl'),'gold_sha256':digest(args.pack/'answer_key.jsonl'),
        'mode':args.mode,'backend':'live_default_adapter_asgi','status':'initializing',
        'client_date':manifest['as_of_date'],'actual_started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'independent_human_reviews':0,'independent_blind_benchmark':False,
        'planned':sum(len(c['turns']) for c in cases)*len(transports),'attempted':0,'completed':0,
        'request_retries':0,'workers':args.workers,'transports':transports,
        'meaning':'Provisional source-grounded first-run diagnosis, not independent human-scored benchmark'}
    dump(out/'manifest.json',report)
    lock=threading.Lock()
    progress={'count':0}
    def save(row):
        with lock:
            with (out/'trace_rows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            progress['count']+=1
            if progress['count']%5==0 or progress['count']==report['planned']:
                print('HOLDOUT_PROGRESS',progress['count'],'/',report['planned'],flush=True)
    qa=None
    try:
        from integrated_qa import IntegratedQASystem
        from fastapi.testclient import TestClient
        from app import create_app
        from base.config import config
        qa=IntegratedQASystem()
        qa.client.timeout=60;qa.client.max_retries=0
        qa.rag_system.strategy_selector.client.timeout=60
        qa.rag_system.strategy_selector.client.max_retries=0
        report['runtime_before']=snapshot_runtime(qa)
        with TestClient(create_app(qa,allow_trace=True)) as client:
            health=client.get('/health');report['health']=health.json()
            if health.status_code!=200:raise RuntimeError('dependency_health_failed')
            report['status']='collecting';dump(out/'manifest.json',report)
            rows=run_routes(client,cases,transports,config.DISCLAIMER,save,args.workers)
            report['runtime_after']=snapshot_runtime(qa)
            report['runtime_stable']=report['runtime_before']==report['runtime_after']
        qa=None
        report.update(attempted=len(rows),completed=sum(r['protocol']['transport_completed'] for r in rows),
            decisions=dict(Counter((r.get('result') or {}).get('decision','transport_failure') for r in rows)),
            status='collected' if len(rows)==report['planned'] and report['runtime_stable'] else 'partial_or_drifted')
        dump(out/'traces.json',{'dataset_version':report['dataset_version'],'questions_sha256':report['questions_sha256'],
            'gold_sha256':report['gold_sha256'],'mode':args.mode,'backend':report['backend'],'rows':rows})
        report['trace_sha256']=digest(out/'traces.json')
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,attempted=progress['count'])
    finally:
        if qa is not None:
            try:qa.close()
            except Exception:pass
        report['actual_finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        dump(out/'manifest.json',report)
    print('HOLDOUT_COLLECTION',json.dumps({k:report.get(k) for k in ['status','planned','attempted','completed','runtime_stable','error_type']},ensure_ascii=False),flush=True)
    return 0 if report['status']=='collected' else 1


if __name__=='__main__':
    sys.exit(main())
