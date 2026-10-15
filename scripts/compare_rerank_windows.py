"""Offline same-candidate replay, no generation, tuning, or reserve access."""
import argparse,json,sys,hashlib
from pathlib import Path
import torch
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from base.retrieval_windows import score_parents,WINDOW_CHARS,WINDOW_OVERLAP
from rag_qa.core.document_processor import process_documents
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();torch.set_num_threads(8)
    model=CrossEncoder(str(a.root/'rag_qa/models/bge-reranker-large'),device='cpu')
    chunks=process_documents(str(a.root/'rag_qa/data/finance'));parents={}
    for c in chunks:parents[(c.metadata['doc_id'],c.metadata['parent_id'])]=Document(page_content=c.metadata['parent_content'],metadata=c.metadata)
    traces=json.loads((a.root/'evaluation/results/context_v2_1_regression/traces.json').read_text(encoding='utf-8'))['rows']
    gold={t['turn_id']:t for c in map(json.loads,(a.root/'evaluation/holdout_v1_1/answer_key.jsonl').read_text(encoding='utf-8').splitlines()) for t in c['turns']}
    rows=[]
    for r in traces:
        if r['transport']!='http':continue
        searches=r['result'].get('diagnostics',{}).get('searches',[])
        if not searches or not searches[0].get('rerank'):continue
        candidates=searches[0]['rerank'];docs=[parents[(x['doc_id'],x['block_id'])] for x in candidates]
        before=score_parents(model,r['question'],docs,'parent');after=score_parents(model,r['question'],docs,'window_max')
        target={e['doc_id'] for e in gold[r['turn_id']]['evidence'] if e.get('role')=='support' and e.get('eligible_at_as_of')}
        detail=[]
        for d,b,n in zip(docs,before,after):
            detail.append({'doc_id':d.metadata['doc_id'],'block_id':d.metadata['parent_id'],'is_gold_support_doc':d.metadata['doc_id'] in target,'parent_score':b['score'],'window_score':n['score'],'window_count':n['window_count'],'winning_window':n['winning_window'],
                'parent_pair_tokens':len(model.tokenizer.encode(r['question'],d.page_content,truncation=False)), 'model_max_length':model.max_length})
        rows.append({'turn_id':r['turn_id'],'expected_action_provisional':gold[r['turn_id']]['expected_action'],'candidates':detail})
        if len(rows)%10==0:print('RERANK_REPLAY',len(rows),flush=True)
    def stats(mode):
        key=mode+'_score';answer=[r for r in rows if r['expected_action_provisional']=='answer'];abstain=[r for r in rows if r['expected_action_provisional']=='abstain']
        return {'answer_cases_with_candidates':len(answer),'answer_cases_retaining_gold_support_doc':sum(any(c['is_gold_support_doc'] and c[key]>=.15 for c in r['candidates']) for r in answer),
            'abstain_cases_with_candidates':len(abstain),'abstain_cases_retaining_any_candidate':sum(any(c[key]>=.15 for c in r['candidates']) for r in abstain)}
    result={'meaning':'Same original-query candidates, source-document retention proxies against provisional gold; abstain candidate retention is NOT automatically false-positive evidence. No independent semantic precision claim.',
        'threshold_unchanged':.15,'window_chars':WINDOW_CHARS,'window_overlap':WINDOW_OVERLAP,'models':'local unchanged bge-reranker-large','parent':stats('parent'),'window':stats('window'),'rows':rows}
    if a.out.exists():raise ValueError('refuse overwrite replay')
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
