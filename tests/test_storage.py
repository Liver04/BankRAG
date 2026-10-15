import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import numpy as np
from langchain_core.documents import Document
from rag_qa.core.vector_store import VectorStore
from mysql_qa.db.mysql_client import MysqlClient,question_key
from base.safety import redact,current_rate_query
from tests.support import META,build_system,faq_row

class StorageTests(unittest.TestCase):
    def test_normalized_question_key(self):
        self.assertEqual(question_key('开户需要什么？'),question_key('开户需要什么?'))
    def test_snapshot_failure_does_not_publish(self):
        v=VectorStore.__new__(VectorStore);v.base_collection='test';v.alias='test_active'
        v.collection_name='old';v.client=Mock();v.client.describe_alias.return_value={'collection_name':'old'}
        v.client.has_collection.return_value=False;v._create_collection=Mock()
        v.embedding_function=Mock(side_effect=RuntimeError('simulated embedding failure'))
        d=Document(page_content='t',metadata=dict(META,id='1',parent_content='t',collected_at=20260101,timestamp='now'))
        with self.assertRaisesRegex(RuntimeError,'active_unchanged'):v.add_documents([d])
        v.client.alter_alias.assert_not_called();v.client.create_alias.assert_not_called()
        self.assertEqual(v.collection_name,'old')
    def test_snapshot_idempotent(self):
        from base.knowledge import digest
        import json
        d=Document(page_content='t',metadata=dict(META,id='1',parent_content='t',collected_at=20260101,timestamp='now'))
        signature=[('1',{k:x for k,x in d.metadata.items() if k not in ('timestamp','file_path')})]
        revision=digest(json.dumps(signature,sort_keys=True,ensure_ascii=False))
        v=VectorStore.__new__(VectorStore);v.base_collection='test';v.alias='test_active';v.client=Mock()
        v.client.describe_alias.return_value={'collection_name':'test_s_'+revision[:16]}
        self.assertEqual(v.add_documents([d])['status'],'unchanged')
        v.client.upsert.assert_not_called()
    def test_sql_rollback(self):
        c=Mock();cur=Mock();c.cursor.return_value.__enter__=Mock(return_value=cur);c.cursor.return_value.__exit__=Mock(return_value=False)
        cur.execute.side_effect=RuntimeError('failure')
        with patch('mysql_qa.db.mysql_client.pymysql.connect',return_value=c):
            with self.assertRaises(RuntimeError):MysqlClient().replace_faq([], 'v2')
        c.rollback.assert_called_once();c.commit.assert_not_called()
    def test_current_rates_never_faq(self):
        row=faq_row('我想知道当前银行的利率表');row['answer']='旧利率1.5%'
        r=build_system(rows=[row]).query_result(row['question'])
        self.assertEqual(r.decision,'insufficient_evidence');self.assertNotIn('1.5%',r.answer)
    def test_scope_boundary(self):
        self.assertEqual(build_system().query_result('信用卡分期手续费怎么收').decision,'insufficient_evidence')
    def test_redact_log_query(self):
        self.assertNotIn('客户姓名',redact('查询: 客户姓名张三'))
if __name__=='__main__':unittest.main()
