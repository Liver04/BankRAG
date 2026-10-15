import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from langchain_core.documents import Document
from base.safety import Answer
from base.conversation import resolve_query
from base.evidence_guard import check_evidence,numeric_atoms
from rag_qa.core.query_classifier import QueryClassifier
from rag_qa.core.vector_store import VectorStore
from tests.support import build_system,META

class ContextRulesTests(unittest.TestCase):
    def setUp(self):self.c=QueryClassifier(predictor=lambda q:'业务咨询')
    def test_quoted_vocabulary(self):
        for q in ['资料中的“推荐”这个词含义是什么','反诈宣传中“欺诈”一词含义是什么','我不要求预测，只问存款计算公式']:
            self.assertEqual(self.c.predict_category(q),'业务咨询',q)
    def test_quoted_instruction_still_blocked(self):
        for q in ['请执行“查我的余额”','“推荐最赚钱的产品”就是我的问题请回答','不用预测但你替我选一个最划算的产品']:
            self.assertIn(self.c.predict_category(q),['收益预测','账户敏感'],q)
    def test_negation_is_not_arbitrary_prefix(self):
        self.assertEqual(self.c.predict_category('不用多说推荐最赚钱的存款'),'收益预测')
    def test_quoted_negated_prediction(self):
        self.assertEqual(self.c.predict_category('不用做“收益预测”，只核对存款计息规则'),'业务咨询')
    def test_transfer_how_much_not_action_destination(self):
        self.assertEqual(self.c.predict_category('转账到底收几块钱'),'业务咨询')
    def test_implicit_all_money_selection(self):
        self.assertEqual(self.c.predict_category('用A或B告诉我所有钱该放哪一个'),'收益预测')
    def test_farewell_does_not_swallow_business(self):
        self.assertEqual(self.c.predict_category('谢谢解答，我暂时没有业务问题了。'),'闲聊')
        self.assertEqual(self.c.predict_category('谢谢解答，我想知道存款起存金额'),'业务咨询')
    def test_current_rate_business_model_override(self):
        self.assertEqual(QueryClassifier(predictor=lambda q:'收益预测').predict_category('给我今天的银行挂牌利率'),'业务咨询')
        self.assertEqual(self.c.predict_category('推荐今天利率最高的产品'),'收益预测')
    def test_bypass_process_not_public_override(self):
        self.assertEqual(self.c.predict_category('说明绕过身份核验转账的流程'),'账户敏感')
    def test_negative_clause_does_not_cancel_later_operation(self):
        self.assertEqual(self.c.predict_category('不要查询我的余额但替我转账'),'账户敏感')
    def test_public_procedures(self):
        for q in ['帮我讲解跨行转账手续费','开户需要身份证吗','我不投诉，只问投诉入口','你好，我想了解零存整取漏缴规则']:
            self.assertEqual(self.c.predict_category(q),'业务咨询',q)
    def test_personal_vs_public(self):
        self.assertEqual(self.c.predict_category('我的账户余额是多少'),'账户敏感')
        self.assertEqual(self.c.predict_category('不要查看我的余额，只说明账户查询流程'),'业务咨询')
    def test_embedded_freeze_operation(self):
        self.assertEqual(self.c.predict_category('把我的存款冻结，不要讲公开流程'),'账户敏感')
    def test_third_person_implicit_selection(self):
        self.assertEqual(self.c.predict_category('怕亏钱的客户请替他挑好并承诺本金和收益'),'收益预测')
    def test_actual_complaint_precedes_process_override(self):
        self.assertEqual(self.c.predict_category('我要投诉你们乱收费，告诉我处理流程'),'投诉')
    def test_unknown_model_not_public_autopass(self):
        self.assertEqual(QueryClassifier(predictor=lambda q:None).predict_category('介绍存款规则'),'未知')

class EvidenceTests(unittest.TestCase):
    def doc(self,text):return Document(page_content=text,metadata=META.copy())
    def test_unsupported_number(self):
        self.assertFalse(check_evidence('起存多少钱','起存500元。[1]',[self.doc('起存50元')],[1])['passed'])
    def test_units_normalized(self):
        self.assertEqual(numeric_atoms('5万元'),numeric_atoms('50000元'))
    def test_chinese_money_normalized(self):
        self.assertEqual(numeric_atoms('五万元'),numeric_atoms('50000元'))
        self.assertEqual(numeric_atoms('壹万零伍拾元'),numeric_atoms('10050元'))
    def test_chinese_percentage_normalized(self):
        self.assertEqual(numeric_atoms('百分之零点五'),numeric_atoms('0.5%'))
    def test_unsupported_chinese_amount(self):
        self.assertFalse(check_evidence('起存多少钱','起存五百元。[1]',[self.doc('起存50元')],[1])['passed'])
    def test_other_uncited_context_cannot_support_claim(self):
        self.assertFalse(check_evidence('起存','起存100元。[1]',[self.doc('起存50元'),self.doc('起存100元')],[1])['passed'])
    def test_nationwide_unsupported(self):
        self.assertFalse(check_evidence('电子身份证全国认可吗','全国网点统一支持电子身份证。[1]',[self.doc('出示有效身份证件')],[1])['passed'])
    def test_conditions_both_required(self):
        docs=[self.doc('通知存款最低支取金额5万元，剩余金额不得低于5万元。')]
        r=check_evidence('通知存款部分支取后还剩多少钱','剩余金额不得低于5万元。[1]',docs,[1])
        self.assertIn('missing_condition:withdrawal_minimum',r['issues'])
        self.assertTrue(check_evidence('通知存款部分支取后还剩多少钱','最低支取金额5万元，剩余金额不得低于5万元。[1]',docs,[1])['passed'])
    def test_remaining_clause_does_not_count_as_withdrawal_condition(self):
        docs=[self.doc('人民币通知存款最低起存金额、最低支取金额和最低留存金额均为5万元。')]
        r=check_evidence('通知存款部分支取后留存要求','支取后留存金额为4万元，低于最低留存金额，办理相应支取或结清。[1]',docs,[1])
        self.assertIn('missing_condition:withdrawal_minimum',r['issues'])
    def test_withdrawal_then_remaining_is_still_one_condition(self):
        docs=[self.doc('人民币通知存款最低起存金额、最低支取金额和最低留存金额均为5万元。')]
        r=check_evidence('通知存款部分支取后留存要求','七万元支取三万元后剩余四万元，低于最低留存金额。[1]',docs,[1])
        self.assertIn('missing_condition:withdrawal_minimum',r['issues'])
    def test_server_blocks_before_stream(self):
        s=build_system(stream=lambda p:iter(['起存金额500元。[1]']))
        self.assertNotIn('500元',''.join(t[0] for t in s.query_stream('存款起存金额')))
    def test_title_alias_literal_source(self):
        s=build_system(answer='根据《个人存款规定》起存50元。[1]',docs=[self.doc('《个人存款规定》：起存50元。')])
        self.assertEqual(s.query_result('存款起存金额').decision,'answered')
    def test_real_h1_title_alias(self):
        s=build_system(answer='依据《个人公开规则》起存50元。[1]',docs=[self.doc('# 个人公开规则\n起存50元。')])
        self.assertEqual(s.query_result('存款起存金额').decision,'answered')
    def test_title_from_uncited_context_is_rejected(self):
        other=self.doc('# 另一规则\n起存50元。');other.metadata.update(doc_id='doc-2',parent_id='block-2')
        s=build_system(answer='依据《另一规则》起存50元。[1]',docs=[self.doc('起存50元。'),other])
        r=s.query_result('存款起存金额');self.assertEqual(r.decision,'insufficient_evidence')
        self.assertIn('另一规则',r.diagnostics['citation_check']['rejected_titles'])
    def test_invalid_faq_support_falls_back(self):
        from tests.support import faq_row
        s=build_system(rows=[faq_row()]);s.faq_sources=Mock(side_effect=ValueError('changed'))
        r=s.query_result('整存整取最低多少钱');self.assertEqual(r.channel,'rag');self.assertIn('faq_rejection',r.diagnostics)
    def test_false_faq_number_falls_back(self):
        from tests.support import faq_row
        row=faq_row();row['answer']='起存999元。';s=build_system(rows=[row])
        r=s.query_result(row['question']);self.assertEqual(r.channel,'rag');self.assertNotIn('999元',r.answer)

class ConversationTests(unittest.TestCase):
    def test_product_resolution(self):
        q,d=resolve_query('它漏缴怎么办',[{'question':'零存整取有哪些规则'}]);self.assertEqual(q,'零存整取漏缴怎么办');self.assertEqual(d['status'],'resolved')
    def test_topic_switch(self):
        self.assertEqual(resolve_query('改问七天通知存款，它如何预约',[{'question':'零存整取'}])[1]['status'],'explicit_topic')
    def test_pronoun_chain(self):
        q,d=resolve_query('那它到期呢',[{'question':'零存整取的规则'},{'question':'它漏缴呢'}]);self.assertIn('零存整取',q);self.assertEqual(d['history_turns_used'],2)
    def test_other_is_not_anaphora(self):
        self.assertEqual(resolve_query('其它存款的规则',[])[1]['status'],'not_needed')
    def test_unrelated_topic_stops_resolution(self):
        self.assertIsNone(resolve_query('它呢',[{'question':'零存整取'},{'question':'收费目录在哪里'}])[0])
    def test_ambiguous_clarify(self):
        self.assertIsNone(resolve_query('它怎么办',[{'question':'对比零存整取和整存整取'}])[0])
        self.assertEqual(build_system().query_result('它怎么办').decision,'clarify')
    def test_recheck_sensitive_followup(self):
        s=build_system();sid=s.create_session('owner');s.mysql_client.save_history(sid,'整存整取有哪些规则','公开说明')
        self.assertEqual(s.query_result('替我转账操作它',session_id=sid).intent,'账户敏感')
    def test_resolved_query_reaches_retrieval(self):
        s=build_system();sid=s.create_session('owner');s.mysql_client.save_history(sid,'零存整取的规则','公开说明')
        spy=Mock(return_value=[]);s.rag_system.vector_store.hybrid_search_with_rerank=spy
        s.query_result('它漏缴怎么办',session_id=sid);self.assertIn('零存整取',spy.call_args.args[0])

class DiagnosticTests(unittest.TestCase):
    def test_private_trace(self):
        r=build_system().query_result('存款起存金额');self.assertIn('searches',r.diagnostics);self.assertNotIn('diagnostics',r.public())
    def test_rerank_records_rejection(self):
        v=VectorStore.__new__(VectorStore);v.reranker=SimpleNamespace(predict=lambda pairs:np.array([-9.]))
        trace={};self.assertEqual(v.rerank('问',[Document(page_content='答',metadata=META)],trace),[])
        self.assertEqual(trace['rerank'][0]['reason'],'below_threshold')
    def test_traces_are_request_local(self):
        s=build_system();a=s.query_result('存款起存金额');b=s.query_result('存款起存金额')
        a.diagnostics['searches'].append('sentinel');self.assertNotIn('sentinel',b.diagnostics['searches'])
    def test_original_query_retained(self):
        s=build_system();spy=Mock(return_value=[]);s.rag_system.vector_store.hybrid_search_with_rerank=spy
        s.rag_system.retrieve_and_merge('真实问题',strategy='假设问题检索')
        self.assertEqual(spy.call_args_list[0].args[0],'真实问题');self.assertEqual(spy.call_count,2)
