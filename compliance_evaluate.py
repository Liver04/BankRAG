"""Versioned route-level regression. Fixture scores are NEVER production/model scores."""
import argparse,json,platform
from pathlib import Path
from datetime import datetime,timezone
from evaluation.runner import load_cases,build_client,request_answer,score
def main():
    p=argparse.ArgumentParser();p.add_argument('--backend',choices=['fixture','live'],default='fixture')
    p.add_argument('--transport',choices=['http','websocket','both'],default='both')
    p.add_argument('--output',default='evaluation/results/compliance_v2.json')
    a=p.parse_args();dataset,sha=load_cases();rows=[]
    with build_client(a.backend) as client:
        for case in dataset['cases']:
            for transport in (['http','websocket'] if a.transport=='both' else [a.transport]):
                result=request_answer(client,case['question'],transport)
                rows.append({'case_id':case['id'],'question':case['question'],'transport':transport,
                    **score(case,result),'result':result})
    report={'schema_version':2,'dataset_version':dataset['version'],'dataset_sha256':sha,
        'backend':a.backend,'python':platform.python_version(),'created_at':datetime.now(timezone.utc).isoformat(),
        'passed':sum(r['passed'] for r in rows),'total':len(rows),'cases':rows,
        'meaning':'route regression, NOT an estimate of general financial compliance'}
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['backend','passed','total','dataset_version']},ensure_ascii=False))
    return 0 if report['passed']==report['total'] else 1
if __name__=='__main__':raise SystemExit(main())
