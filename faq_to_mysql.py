"""Versioned snapshot import using the same review/validity registry as vector ingestion."""
from pathlib import Path
import argparse
import json
import re
from base.config import config
from base.knowledge import metadata_for,digest
from base.safety import APPROVED
from base.faq_provenance import load_registry,apply_review
from mysql_qa.db.mysql_client import MysqlClient,question_key
from mysql_qa.cache.redis_client import RedisClient

FAQ_DIR=Path(config.DATA_DIR)/'finance'/'faq'
def parse_faq_md(path):
    text=Path(path).read_text(encoding='utf-8-sig')
    return [(m.group(1).strip(),m.group(2).strip()) for m in re.finditer(
        r'^## 问[：:]\s*(.+?)\s*\n\s*答[：:]\s*(.*?)(?=^## 问[：:]|\Z)',text,re.M|re.S)]

def collect_faq(root=None):
    root=Path(root or Path(config.DATA_DIR)/'finance')
    records={}
    registry=load_registry(root)
    for p in sorted((root/'faq').glob('*.md')):
        text=p.read_text(encoding='utf-8-sig')
        m=metadata_for(p,root,text)
        if m['review_status']!=APPROVED:continue
        for question,answer in parse_faq_md(p):
            key=question_key(question)
            reviewed=apply_review(m,root,key,answer,registry)
            row=dict(reviewed,question=question,answer=answer,source='faq',category='',
                updated_at=str(m['collected_at']),faq_id=key,block_id=digest(m['doc_id']+key+reviewed['version'])[:48])
            if key in records and records[key]['answer']!=answer:
                raise ValueError('Conflicting duplicate FAQ; review before import')
            records[key]=row
    return list(records.values())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--root',default=None)
    args=parser.parse_args()
    rows=collect_faq(args.root)
    # timestamp is observational, excluded from content revision.
    revision=digest(json.dumps([{k:v for k,v in r.items() if k not in ('timestamp','file_path')} for r in rows],sort_keys=True,ensure_ascii=False))
    if not rows:raise RuntimeError('No approved FAQ; previous snapshot retained')
    if args.dry_run:
        print(json.dumps({'status':'dry_run','records':len(rows),'revision':revision},ensure_ascii=False));return
    client=MysqlClient();client.create_table()
    n=client.replace_faq(rows,revision)
    try:RedisClient().invalidate();cache='invalidated'
    except Exception:cache='unavailable; DB version still prevents stale cache reuse'
    print(json.dumps({'status':'success','records':n,'revision':revision,'cache':cache},ensure_ascii=False))
if __name__=='__main__':main()
