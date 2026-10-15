from types import SimpleNamespace
from langchain_core.documents import Document
from rag_qa.core.rag_system import RAGSystem
from rag_qa.core.query_classifier import QueryClassifier
from integrated_qa import IntegratedQASystem
from base.safety import eligible
from mysql_qa.db.mysql_client import question_key

META=dict(doc_id='doc-1',parent_id='block-1',title='存款公开规则',source='product',
    source_url='https://example.invalid/demo',version='v1',review_status='demo_approved',
    effective_date=20260101,expiry_date=20991231,jurisdiction='CN')
class MemoryDB:
    def __init__(self):
        self.rows={};self.sessions={};self.hist={};self.version='v1';self.ok=True
    def create_table(self):pass
    def knowledge_version(self):return self.version
    def fetch_eligible(self):return [r for r in self.rows.values() if eligible(r)]
    def fetch_record(self,key):
        r=self.rows.get(key)
        return r if r and eligible(r) else None
    def create_session(self,owner):
        import uuid
        sid=str(uuid.uuid4());self.sessions[sid]=owner;return sid
    def owns_session(self,sid,owner):return bool(owner) and self.sessions.get(sid)==owner
    def history(self,sid):return self.hist.get(sid,[])[-5:]
    def save_history(self,sid,q,a):self.hist.setdefault(sid,[]).append({'question':q,'answer':a})
    def clear_history(self,sid):self.hist[sid]=[];return True
    def health(self):return self.ok
    def close(self):pass
class MemoryCache:
    def __init__(self):self.data={}
    def get_data(self,k,revision='v2'):return self.data.get((revision,k))
    def set_data(self,k,v,revision='v2',ttl=3600):self.data[(revision,k)]=v
    def health(self):return True
    def close(self):pass
def build_system(answer='整存整取起存金额为50元。[1]',rows=None,docs=None,stream=None):
    db=MemoryDB()
    for row in rows or []:db.rows[question_key(row['question'])]=dict(row,question_hash=question_key(row['question']))
    vector=SimpleNamespace(hybrid_search_with_rerank=lambda *a,**kw:[] if kw.get('source_filter')=='rate_table' else docs if docs is not None else [Document(page_content='整存整取起存金额50元。',metadata=META.copy())],
        client=SimpleNamespace(has_collection=lambda n:True),collection_name='fixture')
    classifier=QueryClassifier(predictor=lambda q:'业务咨询');classifier.model=True
    rag=RAGSystem(vector,lambda p:answer,stream,classifier,SimpleNamespace(select_strategy=lambda q:'直接检索'))
    system=IntegratedQASystem(db,MemoryCache(),rag,initialize=False)
    # Explicit fixture evidence adapter; production always reads hash-bound files.
    system.faq_sources=lambda row:[Document(page_content='起存50元。',metadata=META.copy())]
    return system
def faq_row(q='整存整取最低多少钱'):
    return dict(META,question=q,answer='起存50元。',source='faq',block_id='faq-block',faq_id='faq-1')
