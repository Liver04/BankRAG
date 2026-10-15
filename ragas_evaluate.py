"""Collect exact generation traces through HTTP, score once, preserve per-case artifacts."""
import argparse,csv,json,math
from pathlib import Path
from datetime import datetime,timezone
from evaluation.runner import load_cases,build_client,request_answer

def main():
    p=argparse.ArgumentParser();p.add_argument('--backend',choices=['fixture','live'],default='live')
    p.add_argument('--collect-only',action='store_true');p.add_argument('--limit',type=int,default=0)
    p.add_argument('--from-traces',default=None)
    p.add_argument('--output-dir',default='evaluation/results/ragas_v2')
    args=p.parse_args();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    dataset,sha=load_cases();rows=[];excluded=[]
    manifest={'dataset_version':dataset['version'],'dataset_sha256':sha,'backend':args.backend,
        'created_at':datetime.now(timezone.utc).isoformat(),'status':'collecting','metrics':None,'independent_blind_test':False,'dataset_use':'development_regression','generation_model':'qwen-plus',
        'meaning':'answerable subset only; refusals scored separately; no retriever re-execution'}
    try:
        candidates=[c for c in dataset['cases'] if c.get('reference')]
        if args.limit:candidates=candidates[:args.limit]
        if args.from_traces:
            saved=json.loads(Path(args.from_traces).read_text(encoding='utf-8'))
            if saved.get('backend')!='live' or saved.get('dataset_sha256')!=sha:
                raise ValueError('Trace backend/version mismatch')
            answers={r['case_id']:r['result'] for r in saved['cases'] if r['transport']=='http'}
            manifest['source_trace_sha256']=__import__('hashlib').sha256(Path(args.from_traces).read_bytes()).hexdigest()
            samples=[(c,answers[c['id']]) for c in candidates]
        else:
            with build_client(args.backend) as client:
                samples=[(c,request_answer(client,c['question'],'http')) for c in candidates]
        for case,result in samples:
            if result['decision']!='answered':
                excluded.append({'id':case['id'],'decision':result['decision'],'result':result});continue
            rows.append({'case_id':case['id'],'question':case['question'],
                'answer':result['answer'].split('【服务端来源】')[0].strip(),
                'contexts':[d['text'] for d in result['contexts']],'ground_truth':case['reference'],'trace':result})
        (out/'traces.json').write_text(json.dumps({'rows':rows,'excluded':excluded},ensure_ascii=False,indent=2),encoding='utf-8')
        manifest.update(answered=len(rows),excluded=len(excluded),answerable_total=len(candidates),answer_coverage=len(rows)/len(candidates) if candidates else 0,status='collected')
        if not args.collect_only:
            if args.backend!='live':raise ValueError('Judge metrics must use live backend, not fixtures')
            if not rows:raise ValueError('No answered samples to score')
            from datasets import Dataset
            from ragas import evaluate
            from ragas.metrics import faithfulness,answer_relevancy,context_precision,context_recall
            from langchain_openai import ChatOpenAI
            from langchain_core.embeddings import Embeddings
            from sentence_transformers import SentenceTransformer
            from base.config import config
            class LocalEmbeddings(Embeddings):
                def __init__(self):self.model=SentenceTransformer(config.MODELS_DIR+'/bge-m3',device='cpu')
                def embed_documents(self,texts):return self.model.encode(texts,normalize_embeddings=True).tolist()
                def embed_query(self,text):return self.embed_documents([text])[0]
            judge=ChatOpenAI(model=config.LLM_MODEL,api_key=config.DASHSCOPE_API_KEY,base_url=config.DASHSCOPE_BASE_URL,
                temperature=0,timeout=90,max_retries=1)
            ds=Dataset.from_list([{k:r[k] for k in ['question','answer','contexts','ground_truth']} for r in rows])
            result=evaluate(ds,metrics=[faithfulness,answer_relevancy,context_precision,context_recall],
                llm=judge,embeddings=LocalEmbeddings(),raise_exceptions=True)
            df=result.to_pandas()
            df.to_json(out/'per_case.json',orient='records',force_ascii=False,indent=2)
            metrics={}
            for name in ['faithfulness','answer_relevancy','context_precision','context_recall']:
                values=[float(x) for x in df[name] if math.isfinite(float(x))]
                metrics[name]={'mean':sum(values)/len(values) if values else None,'valid_count':len(values),'total':len(rows)}
            manifest.update(status='scored',metrics=metrics,judge_model=config.LLM_MODEL)
            with (out/'summary.csv').open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['metric','mean','valid_count','total']);w.writeheader()
                for key,value in metrics.items():w.writerow({'metric':key,**value})
    except Exception as exc:
        manifest.update(status='failed',error_type=type(exc).__name__)
        # Do not persist raw SDK exceptions that could contain credentials.
    finally:
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False))
    return 1 if manifest['status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())
