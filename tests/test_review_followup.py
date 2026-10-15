import unittest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from app import create_app
from base.config import config
from base.evidence_guard import check_evidence
from rag_qa.core.query_classifier import QueryClassifier
from tests.support import build_system, META
from langchain_core.documents import Document
from mysql_qa.retrieval.bm25_search import Bm25Search
from mysql_qa.db.mysql_client import question_key

class FollowupGuardTests(unittest.TestCase):
    def test_insufficient_answer_is_not_labeled_answered(self):
        s=build_system()
        s.rag_system.retrieve_and_merge=lambda *a,**k:[Document(page_content='原文没有金额。',metadata=META.copy())]
        s.rag_system.llm=lambda _:'现有资料未提供具体金额。[1]'
        r=s.query_result('金额是多少？')
        self.assertEqual(r.decision,'insufficient_evidence')
        self.assertEqual(r.citations,[])
        self.assertIn('信息不足',r.answer)

    def test_out_of_range_citation_gets_one_constrained_retry(self):
        s=build_system()
        s.rag_system.retrieve_and_merge=lambda *a,**k:[Document(page_content='整存整取最低起存金额为50元。',metadata=META.copy())]
        answers=iter(['最低起存金额为50元。[9]','最低起存金额为50元。[1]'])
        s.rag_system.llm=lambda _ : next(answers)
        r=s.query_result('整存整取最低起存金额是多少？')
        self.assertEqual(r.decision,'answered')
        self.assertEqual(r.citations[0]['block_id'],META['parent_id'])
        self.assertTrue(r.diagnostics['citation_repair']['passed'])

    def test_failed_citation_repair_abstains_after_one_retry(self):
        s=build_system()
        s.rag_system.retrieve_and_merge=lambda *a,**k:[Document(page_content='整存整取最低起存金额为50元。',metadata=META.copy())]
        answers=iter(['最低起存金额为50元。[9]','最低起存金额为50元。[9]'])
        s.rag_system.llm=lambda _ : next(answers)
        r=s.query_result('整存整取最低起存金额是多少？')
        self.assertEqual(r.decision,'insufficient_evidence')
        self.assertEqual(r.error_code,'citation_repair_failed')
        self.assertEqual(r.diagnostics['citation_repair']['attempts'],1)

    def test_forgotten_online_banking_login_uses_reviewed_faq_alias(self):
        query='网银登录密码忘了，官方资料里怎样找回？我不需要代办，也不会提供密码。'
        canonical='忘记网银用户名或登录密码怎么办？'
        expected=question_key(canonical)
        row={'question_hash':expected,'question':canonical,'answer':'按官网列明的自助或网点渠道找回。'}
        class FakeRedis:
            def get_data(self,*a,**k):return None
            def set_data(self,*a,**k):pass
        class FakeMysql:
            def knowledge_version(self):return 'v1'
            def fetch_record(self,key):return row if key==expected else None
        result=Bm25Search(FakeRedis(),FakeMysql()).search_record(query)
        self.assertEqual(result['question'],canonical)

    def test_phase_timings_are_reported_and_nonnegative(self):
        s=build_system()
        r=s.query_result('整存整取起存金额是多少？')
        self.assertEqual(r.decision,'answered')
        route=r.diagnostics['route_phase_timings']
        rag=r.diagnostics['rag_phase_timings']
        self.assertIn('orchestration_total_seconds',route)
        self.assertIn('retrieval_and_rerank_seconds',rag)
        self.assertIn('generation_seconds',rag)
        self.assertIn('validation_seconds',rag)
        self.assertTrue(all(isinstance(v,(int,float)) and v>=0 for v in route.values()))
        self.assertTrue(all(isinstance(v,(int,float)) and v>=0 for v in rag.values()))

    def test_stale_rate_table_question_overrides_advice_label(self):
        query='那张截至2025年5月的中行人民币表能直接代表现在的报价吗？给我肯定答案。'
        c=QueryClassifier(predictor=lambda _: '收益预测')
        self.assertEqual(c.predict_category(query),'业务咨询')

    def test_deposit_insurance_question_is_public_business(self):
        query='同一家投保银行两个被保险存款账户，按存款保险摘录是每户各算额度还是本息合并？超限怎么办？'
        c=QueryClassifier(predictor=lambda _: '未知')
        self.assertEqual(c.predict_category(query),'业务咨询')

    def test_missing_transfer_dimensions_asks_for_them(self):
        q='转账到底收几块钱？银行、渠道和金额我都没确定，先给个唯一金额。'
        s=build_system();s.rag_system.query_classifier=QueryClassifier(predictor=lambda _: '收益预测')
        s.bm25_search.search_record=Mock(side_effect=AssertionError('must clarify before FAQ'))
        r=s.query_result(q)
        self.assertEqual(r.decision,'clarify')
        self.assertIn('转出银行、办理渠道和转账金额',r.answer)
        s.bm25_search.search_record.assert_not_called()

    def test_missing_branch_location_asks_without_claiming_realtime_lookup(self):
        q='周日我家楼下中行网点几点开门？没有网点名字，你就按最近的来回答。'
        r=build_system().query_result(q)
        self.assertEqual(r.decision,'clarify')
        self.assertIn('所在城市、区县',r.answer)
        self.assertIn('不读取实时位置',r.answer)

    def test_cited_phrase_cannot_be_claimed_absent(self):
        source=Document(page_content='教育储蓄不得部分提前支取。',metadata=META.copy())
        r=check_evidence('教育储蓄规则是什么','资料未出现“部分提前支取”字样。[1]',[source],[1])
        self.assertFalse(r['passed'])
        self.assertIn('source_text_misread',r['issues'])

    def test_legal_scope_cannot_be_inferred_from_specialness(self):
        source=Document(page_content='教育储蓄具有专项用途。定期储蓄存款按本条例规定处理。',metadata=META.copy())
        answer='教育储蓄虽有特殊性，因此不能直接套用《储蓄管理条例》。[1]'
        r=check_evidence('教育储蓄能否部分提前支取？',answer,[source],[1])
        self.assertFalse(r['passed'])
        self.assertIn('unsupported_legal_scope_inference',r['issues'])

    def test_named_authority_needs_support_in_cited_source(self):
        source=Document(page_content='中国银行活期存款产品说明。',metadata=META.copy())
        r=check_evidence('利率如何调整？','利率调整以人民银行公告为准。[1]',[source],[1])
        self.assertFalse(r['passed'])
        self.assertIn('unsupported_named_authority',r['issues'])

    def test_websocket_disclaimer_precedes_successful_body(self):
        s=build_system()
        with TestClient(create_app(s,allow_trace=True)) as client:
            sid=client.post('/api/create_session').json()['session_id']
            with client.websocket_connect('/api/stream') as ws:
                ws.send_json({'query':'起存金额是多少','session_id':sid})
                frames=[]
                while True:
                    frame=ws.receive_json();frames.append(frame)
                    if frame['type']=='end':break
        tokens=[f['token'] for f in frames if f['type']=='token']
        self.assertIn(config.DISCLAIMER,tokens[0])
        self.assertEqual(''.join(tokens).count(config.DISCLAIMER),1)
        self.assertEqual(frames[-1]['decision'],'answered')

    def test_websocket_exception_after_preamble_keeps_disclaimer(self):
        s=build_system();s.query_result=Mock(side_effect=RuntimeError('test failure'))
        with TestClient(create_app(s,allow_trace=True)) as client:
            sid=client.post('/api/create_session').json()['session_id']
            with client.websocket_connect('/api/stream') as ws:
                ws.send_json({'query':'存款起存金额','session_id':sid})
                start=ws.receive_json();preamble=ws.receive_json();error=ws.receive_json()
        self.assertEqual(start['type'],'start')
        self.assertEqual(preamble['type'],'token')
        self.assertIn(config.DISCLAIMER,preamble['token'])
        self.assertEqual(error['type'],'error')
        self.assertIn(config.DISCLAIMER,error['error'])

if __name__=='__main__':unittest.main()
