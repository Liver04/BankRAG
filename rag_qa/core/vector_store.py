"""Hybrid retrieval and atomic versioned snapshots. No legacy unreviewed fallback."""
import hashlib
import json
import re
from langchain_core.documents import Document
from pymilvus import MilvusClient,DataType,AnnSearchRequest,WeightedRanker
from base.config import config
from base.safety import today_int,validate_source,APPROVED
from base.knowledge import digest
from base.retrieval_windows import score_parents
SOURCE_BIAS={'faq':-.6}
_today_int=today_int

class VectorStore:
    def __init__(self,collection_name=config.MILVUS_COLLECTION_NAME,host=config.MILVUS_HOST,
                 port=config.MILVUS_PORT,database=config.MILVUS_DATABASE_NAME):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',collection_name):raise ValueError('invalid collection')
        self.base_collection=collection_name
        self.alias=collection_name+'_active'
        self.client=MilvusClient(uri=f'http://{host}:{port}',db_name=database,timeout=15)
        try:self.client.describe_alias(self.alias);self.collection_name=self.alias
        except Exception:
            self.collection_name=collection_name+'_v2_bootstrap'
            self._create_collection(self.collection_name)
        self.client.load_collection(self.collection_name)
        import torch
        try:
            from milvus_model.hybrid import BGEM3EmbeddingFunction
        except ImportError:
            from pymilvus.model.hybrid import BGEM3EmbeddingFunction
        from sentence_transformers import CrossEncoder
        self.embedding_function=BGEM3EmbeddingFunction(model_name_or_path=f'{config.MODELS_DIR}/bge-m3',
            use_fp16=False,device='cuda' if torch.cuda.is_available() else 'cpu')
        self.reranker=CrossEncoder(f'{config.MODELS_DIR}/bge-reranker-large',
            device='cuda' if torch.cuda.is_available() else 'cpu')

    def _create_collection(self,name):
        if self.client.has_collection(name):return
        s=self.client.create_schema(auto_id=False,enable_dynamic_field=True)
        for field,size in [('id',100),('parent_id',100),('doc_id',64),('source',50),('title',512),
                           ('version',64),('review_status',32),('jurisdiction',8),('timestamp',50)]:
            s.add_field(field_name=field,datatype=DataType.VARCHAR,max_length=size,is_primary=(field=='id'))
        for field in ['text','parent_content','source_url']:
            s.add_field(field_name=field,datatype=DataType.VARCHAR,max_length=65535)
        for field in ['effective_date','expiry_date','collected_at']:s.add_field(field_name=field,datatype=DataType.INT64)
        s.add_field(field_name='dense_vector',datatype=DataType.FLOAT_VECTOR,dim=1024)
        s.add_field(field_name='sparse_vector',datatype=DataType.SPARSE_FLOAT_VECTOR)
        idx=self.client.prepare_index_params()
        idx.add_index(field_name='dense_vector',index_type='AUTOINDEX',metric_type='IP')
        idx.add_index(field_name='sparse_vector',index_type='SPARSE_INVERTED_INDEX',metric_type='IP')
        self.client.create_collection(collection_name=name,schema=s,index_params=idx)

    def add_documents(self,documents,batch_size=32):
        if not documents:raise ValueError('empty snapshot; active knowledge retained')
        if len({d.metadata['id'] for d in documents})!=len(documents):raise ValueError('duplicate chunk IDs')
        signature=[(d.metadata['id'],{k:v for k,v in d.metadata.items() if k not in ('timestamp','file_path')}) for d in documents]
        revision=digest(json.dumps(signature,sort_keys=True,ensure_ascii=False))
        target=self.base_collection+'_s_'+revision[:16]
        try:previous=self.client.describe_alias(self.alias)['collection_name']
        except Exception:previous=None
        if previous==target:return {'status':'unchanged','count':len(documents),'revision':revision}
        # Failed, unpublished snapshots can be safely rebuilt; never drop the active collection.
        if self.client.has_collection(target):self.client.drop_collection(target)
        self._create_collection(target)
        inserted=0
        try:
            for start in range(0,len(documents),batch_size):
                batch=documents[start:start+batch_size]
                cached={}
                if previous:
                    try:
                        cached={r['id']:r for r in self.client.query(collection_name=previous,
                            filter='id in '+json.dumps([d.metadata['id'] for d in batch]),
                            output_fields=['id','dense_vector','sparse_vector'])}
                    except Exception:cached={}
                missing=[d for d in batch if d.metadata['id'] not in cached]
                embeddings=self.embedding_function([d.page_content for d in missing]) if missing else None
                offsets={d.metadata['id']:i for i,d in enumerate(missing)}
                rows=[]
                for i,d in enumerate(batch):
                    m=d.metadata
                    if m['id'] in cached:
                        dense=cached[m['id']]['dense_vector']
                        sparse_vector={int(j):float(v) for j,v in cached[m['id']]['sparse_vector'].items()}
                    else:
                        offset=offsets[m['id']]
                        sparse=embeddings['sparse'][offset]
                        dense=embeddings['dense'][offset].tolist()
                        sparse_vector={int(j):float(v) for j,v in zip(sparse.col,sparse.data)}
                    rows.append(dict(id=m['id'],text=d.page_content,dense_vector=dense,
                        sparse_vector=sparse_vector,
                        parent_id=m['parent_id'],parent_content=m['parent_content'],doc_id=m['doc_id'],source=m['source'],
                        title=m['title'],source_url=m['source_url'],version=m['version'],review_status=m['review_status'],
                        jurisdiction=m['jurisdiction'],effective_date=m['effective_date'],expiry_date=m['expiry_date'],
                        collected_at=m['collected_at'],timestamp=m['timestamp']))
                self.client.upsert(collection_name=target,data=rows)
                inserted+=len(rows)
            self.client.flush(target)
            self.client.load_collection(target)
            if self.client.get_collection_stats(target)['row_count']!=len(documents):raise RuntimeError('snapshot_count_mismatch')
            if previous:self.client.alter_alias(collection_name=target,alias=self.alias)
            else:self.client.create_alias(collection_name=target,alias=self.alias)
        except Exception as e:
            # The old alias still serves a complete snapshot. An unfinished target is never published.
            raise RuntimeError(f'snapshot_failed:{inserted}/{len(documents)};active_unchanged') from e
        self.collection_name=self.alias
        # Keep one rollback snapshot; remove earlier snapshots owned by this component.
        cleanup_errors=[]
        for name in self.client.list_collections():
            if name.startswith(self.base_collection+'_s_') and name not in {target,previous}:
                try:self.client.drop_collection(name)
                except Exception:cleanup_errors.append(name)
        return {'status':'success','count':inserted,'revision':revision,'previous':previous,'collection':target,'cleanup_pending':cleanup_errors}

    def _build_filter_expr(self,source_filter=None):
        validate_source(source_filter)
        now=_today_int()
        parts=[f'review_status == "{APPROVED}"','jurisdiction == "CN"',
            f'effective_date <= {now}',f'(expiry_date == 0 or expiry_date >= {now})']
        if source_filter:parts.insert(0,'source == '+json.dumps(source_filter))
        return '('+') and ('.join(parts)+')'

    def hybrid_search_with_rerank(self,query,k=config.RETRIEVAL_K,source_filter=None,trace=None):
        expr=self._build_filter_expr(source_filter)
        if trace is not None:trace.update(filter_expression=expr,collection=self.collection_name,candidates=[],rerank=[],status='searching')
        emb=self.embedding_function([str(query)])
        sparse=emb['sparse'][0]
        reqs=[AnnSearchRequest(data=[emb['dense'][0]],anns_field='dense_vector',
                param={'metric_type':'IP','params':{}},limit=k,expr=expr),
            AnnSearchRequest(data=[{int(j):float(v) for j,v in zip(sparse.col,sparse.data)}],anns_field='sparse_vector',
                param={'metric_type':'IP','params':{}},limit=k,expr=expr)]
        hits=self.client.hybrid_search(collection_name=self.collection_name,reqs=reqs,
            ranker=WeightedRanker(.7,1.),limit=k,output_fields=['text','parent_content','parent_id','doc_id',
                'source','title','source_url','version','review_status','jurisdiction','effective_date','expiry_date','collected_at'])[0]
        if trace is not None:
            trace['candidates']=[{'doc_id':h['entity'].get('doc_id'),'block_id':h['entity'].get('parent_id'),
                'hybrid_score':float(h.get('distance',h.get('score',0)))} for h in hits]
        docs=self._get_unique_parent_docs([self._doc_from_hit(h['entity']) for h in hits])
        result=self.rerank(query,docs,trace)
        if trace is not None:trace.update(status='complete',selected_count=len(result))
        return result

    def rerank(self,query,docs,trace=None):
        if not docs:return []
        scored=score_parents(self.reranker,query,docs)
        scores=[r['score'] for r in scored]
        if trace is not None:
            trace['rerank']=[{'doc_id':d.metadata.get('doc_id'),'block_id':d.metadata.get('parent_id'),
                'raw_score':float(score),'adjusted_score':float(score)+SOURCE_BIAS.get(d.metadata.get('source'),0),
                'threshold':config.RERANK_THRESHOLD,'score_mode':'source_window_max','window_count':info['window_count'],
                'winning_window':info['winning_window'],'reason':'eligible' if float(score)>=config.RERANK_THRESHOLD else 'below_threshold'} for score,d,info in zip(scores,docs,scored)]
        ranked=[(float(score)+SOURCE_BIAS.get(d.metadata.get('source'),0),d) for score,d in zip(scores,docs)
            if float(score)>=config.RERANK_THRESHOLD]
        result=[d for _,d in sorted(ranked,key=lambda x:x[0],reverse=True)][:config.CANDIDATE_M]
        if trace is not None:
            keys={(d.metadata.get('doc_id'),d.metadata.get('parent_id')) for d in result}
            for row in trace['rerank']:
                if row['reason']=='eligible':row['reason']='selected' if (row['doc_id'],row['block_id']) in keys else 'outside_top_m'
        return result

    def _doc_from_hit(self,hit):
        return Document(page_content=hit['text'],metadata={k:v for k,v in hit.items() if k!='text'})
    def _get_unique_parent_docs(self,chunks):
        found={}
        for d in chunks:
            key=(d.metadata.get('doc_id'),d.metadata.get('parent_id'))
            found.setdefault(key,Document(page_content=d.metadata.get('parent_content',d.page_content),metadata=d.metadata))
        return list(found.values())
