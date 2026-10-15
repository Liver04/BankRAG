"""Normalized exact lookup then conservative lexical coverage; not a probability."""
from threading import RLock
from rank_bm25 import BM25Okapi
from base.safety import eligible,today_int,validate_source
from mysql_qa.db.mysql_client import question_key
from mysql_qa.utils.preprocess import preprocess_text
class Bm25Search:
    def __init__(self,redis_client,mysql_client):
        self.redis_client,self.mysql_client=redis_client,mysql_client
        self.revision=None
        self.rows,self.tokens,self.bm25=[],[],None
        self.lock=RLock()
    def search_record(self,query,threshold=.85,source_filter=None):
        validate_source(source_filter)
        if source_filter not in (None,'faq'):return None
        version=self.mysql_client.knowledge_version()
        # Small reviewed public-language normalization; never skips row validity checks.
        aliases={'开户需要身份证吗':'开立个人账户需要出示什么证件？',
                 '开户要什么证件':'开立个人账户需要出示什么证件？',
                 '开户需要什么证件':'开立个人账户需要出示什么证件？'}
        normalized=query.strip().rstrip('？?。').replace(' ','')
        lookup=aliases.get(normalized,query)
        # Controlled recall for public self-service recovery steps. It only
        # selects the reviewed FAQ row; normal eligibility/provenance checks run later.
        if ('网银' in normalized and any(x in normalized for x in ('登录口令','登录密码','用户名'))
                and any(x in normalized for x in ('忘','找回','重置'))):
            lookup='忘记网银用户名或登录密码怎么办？'
        key=question_key(lookup)
        cached=self.redis_client.get_data(key,revision=version)
        if cached:
            r=self.mysql_client.fetch_record(cached['question_hash'])
            if r:return r
        exact=self.mysql_client.fetch_record(key)
        if exact:
            self.redis_client.set_data(key,{'question_hash':key},revision=version)
            return exact
        with self.lock:
            revision=(version,today_int())
            if revision!=self.revision:
                self.rows=self.mysql_client.fetch_eligible()
                self.tokens=[preprocess_text(r['question']) for r in self.rows]
                self.bm25=BM25Okapi(self.tokens) if self.tokens and any(self.tokens) else None
                self.revision=revision
            if not self.bm25:return None
            qt=preprocess_text(query)
            if not qt:return None
            scores=self.bm25.get_scores(qt)
            indices=sorted(range(len(scores)),key=lambda i:float(scores[i]),reverse=True)[:3]
            for i in indices:
                a,b=set(qt),set(self.tokens[i])
                if len(a&b)/max(len(a|b),1)>=threshold:
                    r=self.mysql_client.fetch_record(self.rows[i]['question_hash'])
                    if r and eligible(r):return r
        return None
    def search(self,query,threshold=.85):
        r=self.search_record(query,threshold)
        return (r['answer'],False) if r else (None,True)
