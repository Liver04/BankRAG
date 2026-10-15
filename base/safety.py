"""Shared input/output contract. Demo approval is NOT a legal or manual approval."""
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
import re
from base.config import config

SOURCES = frozenset({'product', 'rate_table', 'regulation', 'business_rule', 'faq'})
APPROVED = 'demo_approved'

def today_int():
    return int(date.today().strftime('%Y%m%d'))

def parse_date(value):
    if value in (None, '', 0, '0'):
        return 0
    s = re.sub(r'[-/.]', '', str(value).strip())
    return int(datetime.strptime(s, '%Y%m%d').strftime('%Y%m%d'))

def validate_source(value):
    if value is not None and value not in SOURCES:
        raise ValueError('source_filter 不在允许的文档类型中')
    return value

def eligible(meta, today=None):
    now = today or today_int()
    try:
        start, end = parse_date(meta.get('effective_date')), parse_date(meta.get('expiry_date'))
        return (meta.get('review_status') == APPROVED and meta.get('jurisdiction', 'CN') == 'CN'
                and start <= now and (end == 0 or now <= end))
    except (TypeError, ValueError):
        return False

def finalize(text):
    # One authoritative copy, including refusal, greeting, errors and FAQ paths.
    text = str(text or '').replace(config.DISCLAIMER, '').strip()
    return text + '\n\n' + config.DISCLAIMER

def redact(text):
    text = re.sub(r'sk-[A-Za-z0-9_.-]+', '[KEY]', str(text))
    text = re.sub(r'(?<!\d)(?:\d{15,19}[0-9Xx]?|1[3-9]\d{9})(?!\d)', '[PII]', text)
    # Avoid storing free-text customer queries/answers in application logs.
    text = re.sub(r"(查询|问题|query)[:：=]\s*.*", r'\1:[REDACTED]', text, flags=re.I)
    return text

@dataclass
class Answer:
    answer: str
    channel: str
    intent: str
    decision: str
    citations: list = field(default_factory=list)
    contexts: list = field(default_factory=list)
    error_code: str = ''
    diagnostics: dict = field(default_factory=dict)

    def public(self):
        d = asdict(self)
        d.pop('contexts', None)
        d.pop('diagnostics', None)
        return d

def citation(doc, number):
    m = doc.metadata
    if not m.get('doc_id') or not m.get('parent_id'):
        raise ValueError('缺少文档或块标识；请重新入库')
    return {'number': number, 'doc_id': m['doc_id'], 'block_id': m['parent_id'],
            'title': m.get('title', ''), 'source_url': m.get('source_url', ''),
            'version': m.get('version', ''), 'review_status': m.get('review_status', 'pending'),
            'effective_date': m.get('effective_date', 0), 'expiry_date': m.get('expiry_date', 0)}

def render_citations(items):
    return '\n'.join(f"[{c['number']}]《{c['title']}》 doc={c['doc_id']} block={c['block_id']} "
                     f"审核状态={c['review_status']} 有效期={c['effective_date']}~{c['expiry_date'] or '未设法定失效日'} "
                     f"来源={c['source_url'] or '本地演示文档'}" for c in items)


def current_rate_query(query):
    text=str(query or '')
    direct=bool(re.search(r'利率表|(?:当前|最新|今天|现在|实时).*利率|利率.*(?:多少|当前|最新|今天)',text))
    has_rate=bool(re.search(r'利率|报价',text))
    has_present=bool(re.search(r'当前|现在|现行|今天|实时|当下',text))
    table_scope=bool(re.search(r'表|报价|代表|适用|生效|是否|能否|可以|能够',text))
    return direct or (has_rate and has_present and table_scope)


def safe_answer_text(text):
    return re.search(r'(?:我建议|推荐您|建议购买|保证收益|一定赚钱|稳赚)', str(text)) is None
