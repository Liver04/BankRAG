"""Explicit development subset of the existing authorized regression pack."""
import argparse,json,sys,threading
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from evaluation.holdout_runner import PROJECT,load_pack,digest,dump,snapshot_runtime,run_routes
def select_cases(cases,ids):
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_case_id')
    available={c['case_id'] for c in cases}
    if set(ids)-available:raise ValueError('unknown_case_id')
    return [c for c in cases if c['case_id'] in ids]
def main():
    p=argparse.ArgumentParser();p.add_argument('--pack',type=Path,default=PROJECT/'evaluation/holdout_v1_1');p.add_argument('--cases',nargs='+',required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    manifest,cases,_=load_pack(a.pack,'diagnostic');selected=select_cases(cases,a.cases)
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'schema_version':1,'dataset_version':manifest['dataset_version'],'questions_sha256':digest(a.pack/'questions.jsonl'),'gold_sha256':digest(a.pack/'answer_key.jsonl'),
        'scope':'targeted_development_regression_subset','selected_case_ids':a.cases,'mode':'diagnostic','independent_human_reviews':0,'independent_blind_benchmark':False,
        'status':'initializing','planned':2*sum(len(c['turns']) for c in selected),'attempted':0,'completed':0,'request_retries':0,'workers':2,
        'runner_sha256':digest(Path(__file__)),'actual_started_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    dump(out/'manifest.json',report);qa=None;lock=threading.Lock();count=[0]
    def save(row):
        with lock:
            with (out/'trace_rows.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            count[0]+=1;print('TARGETED_PROGRESS',count[0],'/',report['planned'],flush=True)
    try:
        from integrated_qa import IntegratedQASystem
        from fastapi.testclient import TestClient
        from app import create_app
        from base.config import config
        qa=IntegratedQASystem();qa.client.timeout=60;qa.client.max_retries=0;qa.rag_system.strategy_selector.client.timeout=60;qa.rag_system.strategy_selector.client.max_retries=0
        report['runtime_before']=snapshot_runtime(qa)
        with TestClient(create_app(qa,allow_trace=True)) as client:
            health=client.get('/health');report['health']=health.json()
            if health.status_code!=200:raise RuntimeError('dependency_health_failed')
            report['status']='collecting';dump(out/'manifest.json',report)
            rows=run_routes(client,selected,['http','websocket'],config.DISCLAIMER,save,workers=2)
            report['runtime_after']=snapshot_runtime(qa);report['runtime_stable']=report['runtime_before']==report['runtime_after']
        qa=None;report.update(attempted=len(rows),completed=sum(r['protocol']['transport_completed'] for r in rows),status='collected' if len(rows)==report['planned'] and report['runtime_stable'] else 'partial_or_drifted')
        dump(out/'traces.json',{'dataset_version':report['dataset_version'],'scope':report['scope'],'rows':rows});report['trace_sha256']=digest(out/'traces.json')
    except Exception as exc:report.update(status='failed',error_type=type(exc).__name__,attempted=count[0])
    finally:
        if qa is not None:
            try:qa.close()
            except Exception:pass
        report['actual_finished_at']=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();dump(out/'manifest.json',report)
    print('TARGETED_COLLECTION',json.dumps({k:report.get(k) for k in ('status','planned','attempted','completed','runtime_stable')},ensure_ascii=False),flush=True)
    return 0 if report['status']=='collected' else 1
if __name__=='__main__':sys.exit(main())
