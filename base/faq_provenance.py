"""Per-answer provenance. Missing or changed evidence fails closed to pending.

demo_approved is a local demonstration allowlist, never a human/legal certificate.
"""
import json
from pathlib import Path
from urllib.parse import urlparse
from base.knowledge import digest
from base.safety import parse_date


def load_registry(root):
    root = Path(root)
    catalog = json.loads((root/'knowledge_catalog.json').read_text(encoding='utf-8'))
    required = bool(catalog.get('faq_row_registry_required', False))
    path = root/'faq_review_registry.json'
    if not path.exists():
        if required:
            raise ValueError('required_faq_row_registry_missing')
        return {'required': False, 'documents': {}}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('documents'), dict):
        raise ValueError('invalid_faq_row_registry')
    return dict(data, required=required)


def official_url(url):
    parsed = urlparse(url)
    host = parsed.hostname or ''
    domains = ('bankofchina.com', 'boc.cn', 'pbc.gov.cn', 'gov.cn')
    return parsed.scheme == 'https' and any(host == d or host.endswith('.'+d) for d in domains)

def load_faq_sources(row,root):
    """Recheck real support files at serving time, including their expiry."""
    from base.knowledge import metadata_for
    from base.safety import eligible
    from langchain_core.documents import Document
    root=Path(root).resolve()
    data=json.loads(row.get('provenance_json') or '{}')
    if not data.get('binding_valid') or not data.get('sources'):raise ValueError('faq_missing_provenance')
    docs=[]
    for source in data['sources']:
        path=(root/source['document_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('faq_invalid_support_path')
        text=path.read_text(encoding='utf-8')
        if digest(text)!=source.get('content_sha256'):raise ValueError('faq_support_changed')
        meta=metadata_for(path,root,text)
        if not eligible(meta) or not official_url(source.get('url','')):raise ValueError('faq_support_ineligible')
        meta['parent_id']=digest('whole_source|'+meta['doc_id']+'|'+meta['version'])[:48]
        docs.append(Document(page_content=text,metadata=meta))
    return docs


def apply_review(meta, root, question_hash, answer, registry):
    """Keep pending/AU rows in the snapshot so a previous eligible row is revoked."""
    root = Path(root).resolve()
    m = dict(meta)
    relative = Path(m['file_path']).resolve().relative_to(root).as_posix()
    entry = registry.get('documents', {}).get(relative, {})
    rule = entry.get('questions', {}).get(question_hash)
    if not registry.get('required') and rule is None:
        return m
    valid = bool(rule and entry.get('content_sha256') == digest(Path(m['file_path']).read_text(encoding='utf-8'))
                 and rule.get('answer_sha256') == digest(answer))
    sources = []
    if rule:
        for evidence in rule.get('sources', []):
            path = (root/evidence['document_path']).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                valid = False
                continue
            if digest(path.read_text(encoding='utf-8')) != evidence.get('content_sha256'):
                valid = False
            if not official_url(evidence.get('url', '')):
                valid = False
            sources.append(evidence)
    if not sources:
        valid = False
    # Never let a row rule override a rejected/unreviewed file into approved.
    file_approved = m.get('review_status') == 'demo_approved'
    m['review_status'] = rule.get('review_status', 'pending') if valid and file_approved else 'pending'
    if rule:
        m['jurisdiction'] = rule.get('jurisdiction', m['jurisdiction'])
        m['effective_date'] = max(parse_date(m['effective_date']), parse_date(rule.get('effective_date', 0)))
        ends = [parse_date(x) for x in (m.get('expiry_date'), rule.get('expiry_date')) if x]
        m['expiry_date'] = min(ends) if ends else 0
    if m['review_status'] == 'demo_approved' and not m['expiry_date']:
        m['review_status'] = 'pending'
    m['source_url'] = sources[0]['url'] if sources else ''
    provenance = {'review_kind': 'coding_agent_source_crosscheck_not_human',
                  'reviewed_at': rule.get('reviewed_at') if rule else None,
                  'reason': rule.get('reason') if rule else 'row_not_reviewed',
                  'sources': sources, 'binding_valid': valid}
    m['provenance_json'] = json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    m['version'] = digest(meta['version']+digest(answer)+m['provenance_json']+m['review_status']+m['jurisdiction'])[:16]
    return m
