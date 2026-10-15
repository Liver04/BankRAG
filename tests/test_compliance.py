import unittest
from unittest.mock import Mock
from base.config import config
from base.safety import finalize
from tests.support import build_system,faq_row
from rag_qa.core.query_classifier import QueryClassifier

class ComplianceTests(unittest.TestCase):
    def test_faq_cannot_bypass(self):
        s=build_system(rows=[faq_row('推荐收益最高的存款')])
        s.bm25_search.search_record=Mock(side_effect=AssertionError('FAQ must not execute'))
        r=s.query_result('推荐收益最高的存款')
        self.assertEqual(r.decision,'refused');s.bm25_search.search_record.assert_not_called()
        self.assertIn(config.DISCLAIMER,r.answer)
    def test_faq_metadata_and_disclaimer(self):
        r=build_system(rows=[faq_row()]).query_result('整存整取最低多少钱')
        self.assertEqual(r.channel,'faq');self.assertEqual(r.citations[0]['block_id'],'faq-block')
        self.assertIn('demo_approved',r.answer);self.assertEqual(r.answer.count(config.DISCLAIMER),1)
    def test_public_alias_validated(self):
        row=faq_row('开立个人账户需要出示什么证件？')
        self.assertEqual(build_system(rows=[row]).query_result('开户需要身份证吗').channel,'faq')
        row['expiry_date']=20200101
        self.assertEqual(build_system(rows=[row]).query_result('开户需要身份证吗').channel,'rag')
    def test_unsafe_faq_output(self):
        row=faq_row();row['answer']='建议购买某产品，保证收益。'
        r=build_system(rows=[row]).query_result(row['question'])
        self.assertEqual(r.decision,'insufficient_evidence')
        self.assertNotIn('保证收益',r.answer)
    def test_expired_faq(self):
        row=faq_row();row['expiry_date']=20200101
        self.assertEqual(build_system(rows=[row]).query_result(row['question']).channel,'rag')
    def test_pending_faq(self):
        row=faq_row();row['review_status']='pending'
        self.assertEqual(build_system(rows=[row]).query_result(row['question']).channel,'rag')
    def test_source_restricts_faq(self):
        s=build_system(rows=[faq_row()])
        self.assertEqual(s.query_result('整存整取最低多少钱',source_filter='product').channel,'rag')
    def test_citations_reject(self):
        for text in ['无引用','错误[0]','错误[9]','《虚构标题》[1]']:
            r=build_system(answer=text).query_result('存款起存金额')
            self.assertEqual(r.decision,'insufficient_evidence')
            self.assertNotIn(text,r.answer);self.assertIn(config.DISCLAIMER,r.answer)
    def test_stream_exception(self):
        def broken(p):
            yield '不能泄露的部分答案'
            raise RuntimeError('secret')
        s=build_system(stream=broken)
        chunks=list(s.query_stream('存款起存金额'))
        output=''.join(c[0] for c in chunks)
        self.assertIn(config.DISCLAIMER,chunks[0][0]);self.assertNotIn('不能泄露',output)
        self.assertTrue(chunks[-1][2])
    def test_greeting_does_not_swallow(self):
        r=build_system().query_result('你好，我想知道存款起存金额')
        self.assertEqual(r.decision,'answered')
        self.assertEqual(build_system().query_result('你好，我要投诉').intent,'投诉')
    def test_public_questions(self):
        c=QueryClassifier(predictor=lambda q:'业务咨询')
        for q in ['跨行转账手续费是多少','开户需要身份证吗','反诈骗知识有哪些']:
            self.assertEqual(c.predict_category(q),'业务咨询')
    def test_never_downgrade_sensitive(self):
        c=QueryClassifier(predictor=lambda q:'账户敏感')
        self.assertEqual(c.predict_category('把我的存款明细发给我'),'账户敏感')
    def test_missing_model_fails_closed(self):
        c=QueryClassifier(predictor=lambda q:None)
        self.assertEqual(c.predict_category('描述一下这项服务'),'未知')
    def test_all_decisions_have_disclaimer(self):
        for q in ['你好','我要投诉','我的账户余额','推荐个产品','存款起存金额']:
            self.assertIn(config.DISCLAIMER,build_system().query_result(q).answer)
    def test_cache_hit_revalidated(self):
        s=build_system(rows=[faq_row()]);q='整存整取最低多少钱'
        self.assertEqual(s.query_result(q).channel,'faq')
        next(iter(s.mysql_client.rows.values()))['expiry_date']=20200101
        self.assertEqual(s.query_result(q).channel,'rag')
    def test_knowledge_version(self):
        s=build_system(rows=[faq_row()]);q='整存整取最低多少钱'
        s.query_result(q);s.mysql_client.version='v2';s.query_result(q)
        self.assertTrue(any(k[0]=='v2' for k in s.redis_client.data))
if __name__=='__main__':unittest.main()
