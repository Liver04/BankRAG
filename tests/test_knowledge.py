import unittest,tempfile,json
from pathlib import Path
from unittest.mock import Mock
from langchain_core.documents import Document
from base.knowledge import metadata_for,digest,retire_superseded
from rag_qa.core.vector_store import VectorStore
from tests.support import META
class KnowledgeTests(unittest.TestCase):
    def test_effective_vs_collected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'rate_table'/'利率表__20261011.md';p.parent.mkdir()
            text='生效日期：2026-01-16\n整理日期：2026-10-11';p.write_text(text,encoding='utf-8')
            (root/'knowledge_catalog.json').write_text(json.dumps({'documents':{p.relative_to(root).as_posix():{'review_status':'demo_approved','content_sha256':digest(text)}}}),encoding='utf-8')
            m=metadata_for(p,root,text)
            self.assertEqual(m['effective_date'],20260116);self.assertEqual(m['collected_at'],20261011)
            self.assertEqual(m['expiry_date'],20261110)
    def test_unknown_document_pending(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'faq'/'unknown.md';p.parent.mkdir()
            self.assertEqual(metadata_for(p,root,'unknown')['review_status'],'pending')
    def test_stale_rejected(self):
        root=Path('rag_qa/data/finance');p=root/'faq'/'存款常见问题__20260923.md'
        self.assertEqual(metadata_for(p,root,p.read_text(encoding='utf-8'))['review_status'],'rejected')
    def test_retire_previous(self):
        a=Document(page_content='a',metadata=dict(doc_id='1',effective_date=20260101,expiry_date=0))
        b=Document(page_content='b',metadata=dict(doc_id='1',effective_date=20260201,expiry_date=0))
        retire_superseded([a,b]);self.assertEqual(a.metadata['expiry_date'],20260131)
    def test_single_candidate_threshold(self):
        v=VectorStore.__new__(VectorStore);v.reranker=Mock();v.reranker.predict.return_value=[.01]
        self.assertEqual(v.rerank('q',[Document(page_content='irrelevant',metadata=META)]),[])
        v.reranker.predict.assert_called_once()
    def test_equal_scores(self):
        v=VectorStore.__new__(VectorStore);v.reranker=Mock();v.reranker.predict.return_value=[.5,.5]
        ds=[Document(page_content='a',metadata=META),Document(page_content='b',metadata=META)]
        self.assertEqual(len(v.rerank('q',ds)),2)
    def test_filter_whitelist(self):
        v=VectorStore.__new__(VectorStore)
        with self.assertRaises(ValueError):v._build_filter_expr('faq" or true or source=="')
        self.assertIn('review_status',v._build_filter_expr('faq'))
    def test_stable_chunks(self):
        from rag_qa.core.document_processor import process_documents
        a=process_documents('rag_qa/data/finance');b=process_documents('rag_qa/data/finance')
        self.assertEqual([x.metadata['id'] for x in a],[x.metadata['id'] for x in b])
        self.assertTrue(a);self.assertFalse(any('存款常见问题'==x.metadata['title'] for x in a))
if __name__=='__main__':unittest.main()
