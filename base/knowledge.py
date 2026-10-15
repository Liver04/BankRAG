"""Document provenance, demo review registry and explicit freshness policy."""
from pathlib import Path
from datetime import datetime,timedelta
import hashlib
import json
import re
from base.safety import parse_date,APPROVED
TTL={'rate_table':30,'product':90,'business_rule':90,'faq':90}
DATE=r'(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{8})'

def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def marked_date(text,label):
    m=re.search('(?:'+label+r')\s*[:：]\s*'+DATE,text)
    return parse_date(m.group(1)) if m else 0

def metadata_for(path,root,text):
    path,root=Path(path),Path(root)
    rel=path.relative_to(root).as_posix()
    cat=root/'knowledge_catalog.json'
    registry=json.loads(cat.read_text(encoding='utf-8')) if cat.exists() else {'documents':{}}
    rule=registry.get('documents',{}).get(rel,{})
    version=digest(text)[:16]
    status=rule.get('review_status','pending')
    if rule.get('content_sha256')!=digest(text):status='pending'
    if re.search(r'含大量过时信息|答案中含大量过时|不得作为真实参考|不得用于生产环境',text):status='rejected'
    source=path.parent.name
    stem=re.sub(r'__\d{8}$','',path.stem)
    file_date=re.search(r'__(\d{8})$',path.stem)
    collected=marked_date(text,'整理日期|采集日期|数据截至')
    effective=marked_date(text,'生效日期|施行日期|实施日期|执行日期')
    # A filename containing an organizing date is never treated as the effective date.
    if not effective and not marked_date(text,'整理日期|采集日期') and file_date:
        effective=parse_date(file_date.group(1))
    effective=parse_date(rule.get('effective_date',effective))
    expiry=marked_date(text,'失效日期|有效截止日期')
    if 'expiry_date' in rule:expiry=parse_date(rule['expiry_date'])
    elif source in TTL:
        checked=parse_date(rule.get('reviewed_at',0)) or collected or effective
        expiry=int((datetime.strptime(str(checked),'%Y%m%d')+timedelta(days=TTL[source])).strftime('%Y%m%d')) if checked else 0
        if not checked:status='pending'
    if expiry and effective and expiry<effective and source!='rate_table':raise ValueError('invalid validity interval')
    url=re.search(r'https?://[^\s)）>]+',text)
    return dict(source=source,title=stem,doc_id=digest(source+'/'+stem)[:32],version=version,
        source_url=url.group(0) if url else '',effective_date=effective,expiry_date=expiry,
        collected_at=collected,review_status=status,jurisdiction=rule.get('jurisdiction','CN'),
        file_path=str(path),timestamp=datetime.now().isoformat(),extension=path.suffix)

def retire_superseded(documents):
    groups={}
    for d in documents:groups.setdefault(d.metadata['doc_id'],[]).append(d)
    for docs in groups.values():
        docs.sort(key=lambda d:d.metadata['effective_date'])
        for old,new in zip(docs,docs[1:]):
            if new.metadata['effective_date']>old.metadata['effective_date']:
                last=int((datetime.strptime(str(new.metadata['effective_date']),'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d'))
                old.metadata['expiry_date']=min(old.metadata['expiry_date'] or last,last)
    return documents
