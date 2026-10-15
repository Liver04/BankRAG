import json
from pathlib import Path
import tempfile
import unittest
from base.faq_provenance import load_registry,apply_review,official_url
from base.knowledge import metadata_for,digest
from base.safety import eligible
from faq_to_mysql import collect_faq
from mysql_qa.db.mysql_client import question_key


class FaqProvenanceTests(unittest.TestCase):
    def fixture(self,root):
        p=root/'faq'/'demo.md';p.parent.mkdir()
        text='整理日期：2026-10-13\n\n## 问：测试公开流程？\n\n答：需持有效证件。\n'
        p.write_text(text,encoding='utf-8')
        source=root/'product'/'source.md';source.parent.mkdir();source.write_text('公开规则：需持有效证件。',encoding='utf-8')
        (root/'knowledge_catalog.json').write_text(json.dumps({'faq_row_registry_required':True,'documents':{
            'faq/demo.md':{'content_sha256':digest(text),'review_status':'demo_approved'}}}),encoding='utf-8')
        rule={'question':'测试公开流程？','answer_sha256':digest('需持有效证件。'),'review_status':'demo_approved',
            'jurisdiction':'CN','expiry_date':20270111,'reviewed_at':20261013,
            'sources':[{'document_path':'product/source.md','content_sha256':digest(source.read_text(encoding='utf-8')),
                        'url':'https://www.bankofchina.com/example'}]}
        data={'schema_version':1,'documents':{'faq/demo.md':{'content_sha256':digest(text),'questions':{question_key(rule['question']):rule}}}}
        (root/'faq_review_registry.json').write_text(json.dumps(data),encoding='utf-8')
        return p,source,data,rule

    def test_registry_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root);(root/'faq_review_registry.json').unlink()
            with self.assertRaisesRegex(ValueError,'required_faq_row_registry_missing'):load_registry(root)

    def test_changed_answer_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,_,data,_=self.fixture(root)
            m=metadata_for(p,root,p.read_text(encoding='utf-8'))
            row=apply_review(m,root,question_key('测试公开流程？'),'被修改的答案',dict(data,required=True))
            self.assertEqual(row['review_status'],'pending')

    def test_changed_source_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,source,data,_=self.fixture(root)
            source.write_text('规则已更新',encoding='utf-8')
            row=apply_review(metadata_for(p,root,p.read_text(encoding='utf-8')),root,
                question_key('测试公开流程？'),'需持有效证件。',dict(data,required=True))
            self.assertEqual(row['review_status'],'pending')

    def test_au_row_not_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,_,data,rule=self.fixture(root);rule['jurisdiction']='AU'
            row=apply_review(metadata_for(p,root,p.read_text(encoding='utf-8')),root,
                question_key('测试公开流程？'),'需持有效证件。',dict(data,required=True))
            self.assertEqual(row['jurisdiction'],'AU');self.assertFalse(eligible(row,20261013))

    def test_no_row_cannot_inherit_approval(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,_,data,_=self.fixture(root)
            row=apply_review(metadata_for(p,root,p.read_text(encoding='utf-8')),root,'not-reviewed',
                             '需持有效证件。',dict(data,required=True))
            self.assertEqual(row['review_status'],'pending')

    def test_url_authority(self):
        self.assertTrue(official_url('https://www.bankofchina.com/valid'))
        for url in ['https://bankofchina.com.evil.invalid/a','http://www.bankofchina.com/a','https://evil.invalid/a']:
            self.assertFalse(official_url(url))

    def test_actual_faq_scope_and_counts(self):
        rows=collect_faq();self.assertEqual(len(rows),76)
        self.assertEqual(sum(r['review_status']=='pending' for r in rows),30)
        self.assertEqual(sum(r['jurisdiction']=='AU' for r in rows),3)
        self.assertEqual(sum(eligible(r,20261013) for r in rows),43)
        for r in rows:
            self.assertIn('coding_agent_source_crosscheck_not_human',r['provenance_json'])
        row=next(r for r in rows if r['question']=='哪些存款受存款保险保障？')
        self.assertNotIn('大额存单（视具体产品而定）不在',row['answer'])

    def test_faq_never_vectorized(self):
        from rag_qa.core.document_processor import process_documents
        docs=process_documents('rag_qa/data/finance')
        self.assertTrue(docs)
        self.assertTrue(all(d.metadata['source']!='faq' for d in docs))


if __name__=='__main__':unittest.main()
