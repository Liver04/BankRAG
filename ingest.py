"""Publish a complete reviewed snapshot; errors leave the old alias intact and exit nonzero."""
import argparse,json
from pathlib import Path
from base.config import config
from base.knowledge import digest
from base.safety import eligible
from rag_qa.core.document_processor import process_documents

RETRIEVAL_CASES=[
    ('整存整取最低起存金额','product/整存整取定期存款产品说明',['50']),
    ('存款保险最高偿付限额','regulation/存款保险条例',['50']),
    ('临时挂失有效期','business_rule/存款挂失服务',['挂失']),
    ('零存整取漏存怎么办','product/零存整取存款产品说明',['补存']),
    ('通知存款最低起存金额','product/通知存款产品说明',['通知'])]
def validate(store):
    rows=[]
    for question,logical,facts in RETRIEVAL_CASES:
        expected=digest(logical)[:32]
        docs=store.hybrid_search_with_rerank(question)
        ok=any(d.metadata.get('doc_id')==expected and all(f in d.page_content for f in facts) for d in docs)
        rows.append({'question':question,'expected_doc_id':expected,'required_terms':facts,'passed':ok,
            'retrieved':[{'doc_id':d.metadata.get('doc_id'),'block_id':d.metadata.get('parent_id'),'text':d.page_content} for d in docs]})
    report={'dataset_version':'retrieval_evidence_v2','passed':sum(x['passed'] for x in rows),'total':len(rows),
        'meaning':'expected document plus evidence-term hit; not full claim-level recall','cases':rows}
    p=Path('evaluation/results/retrieval_v2.json');p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['dataset_version','passed','total']}))
    return report['passed']/report['total']
def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group()
    g.add_argument('--ingest-only',action='store_true');g.add_argument('--validate-only',action='store_true')
    p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    docs=process_documents(str(Path(config.DATA_DIR)/'finance'))
    if a.dry_run:
        print(json.dumps({'status':'dry_run','chunks':len(docs),'currently_eligible':sum(eligible(d.metadata) for d in docs)}));return 0
    from rag_qa.core.vector_store import VectorStore
    store=VectorStore()
    if not a.validate_only:
        result=store.add_documents(docs);print(json.dumps(result))
    if not a.ingest_only:return 0 if validate(store)>=.8 else 2
    return 0
if __name__=='__main__':raise SystemExit(main())
