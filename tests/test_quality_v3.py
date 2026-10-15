import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from langchain_core.documents import Document
from base.retrieval_windows import evidence_windows,score_parents
from base.claim_support import money_scenario
from base.evidence_guard import check_evidence
from base.condition_plan import notice_answer
from base.config import config
from tests.support import META,build_system,faq_row

def notice_doc(text='人民币通知存款最低起存金额、最低支取金额和最低留存金额均为5万元。'):
    return Document(page_content=text,metadata=dict(META,title='通知存款产品说明'))

class WindowTests(unittest.TestCase):
    def test_tail_covered_by_source_substrings(self):
        text='开户信息'*250+'预留手机号用于接收交易通知'
        windows=evidence_windows(text)
        self.assertTrue(any('预留手机号' in w['text'] for w in windows))
        for w in windows:self.assertEqual(w['text'],text[w['start']:w['end']])
    def test_short_parent_one_prediction(self):
        model=Mock();model.predict.return_value=[.3]
        result=score_parents(model,'问题',[notice_doc()]);self.assertEqual(result[0]['window_count'],1)
        model.predict.assert_called_once()
    def test_best_window_score(self):
        doc=notice_doc('a'*500);model=Mock();model.predict.return_value=[.01,.9,.02]
        result=score_parents(model,'问题',[doc]);self.assertEqual(result[0]['score'],.9)
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):score_parents(SimpleNamespace(predict=lambda x:[float('nan')]),'q',[notice_doc()])
    def test_wrong_score_count_rejected(self):
        with self.assertRaises(ValueError):score_parents(SimpleNamespace(predict=lambda x:[]),'q',[notice_doc()])
    def test_invalid_window_size(self):
        with self.assertRaises(ValueError):evidence_windows('abc',size=3,overlap=3)

class NumericSupportTests(unittest.TestCase):
    def check(self,q,text,source):return check_evidence(q,text,[Document(page_content=source,metadata=META.copy())],[1])
    def test_missed_month_restatement(self):
        result=self.check('零存整取漏存了一个月怎么办','如漏存一个月，应在次月补存。[1]','每月存入固定金额，中途漏存应在次月补存。')
        self.assertTrue(result['passed']);self.assertEqual(result['numeric_support']['checks'][0]['origin'],'explicit_missed_deposit_scenario')
    def test_missed_month_not_bank_permission(self):
        self.assertFalse(self.check('漏存一个月怎么办','银行规定允许漏存一个月。[1]','每月存入固定金额，漏存应次月补存。')['passed'])
    def test_elapsed_duration_restatement(self):
        self.assertTrue(self.check('这笔存款留了十三个月','按题设实际已存十三个月。[1]','计息规则需按实际存期核对。')['passed'])
    def test_elapsed_duration_not_bank_term(self):
        self.assertFalse(self.check('这笔存款留了十三个月','合同规定产品期限十三个月。[1]','期限一年、三年、五年。')['passed'])
    def test_question_rate_not_bank_fact(self):
        self.assertFalse(self.check('假设银行利率是5%，这是真的吗','银行利率是5%。[1]','实际利率需查看公告。')['passed'])
    def test_question_fee_not_bank_fact(self):
        self.assertFalse(self.check('假设转账手续费5元','转账手续费5元。[1]','开户起存5元。')['passed'])
    def test_cannot_borrow_amount_from_other_attribute(self):
        self.assertFalse(self.check('手续费多少','手续费为5元。[1]','手续费0元，起存5元。')['passed'])
    def test_elliptical_fee_inherits_question_scope(self):
        self.assertFalse(self.check('转账手续费多少','5元。[1]','起存5元。')['passed'])
    def test_explicit_scenario_amount_allowed(self):
        self.assertTrue(self.check('通知存款七万元取三万元后剩四万元','按题设，本次支取30000元。[1]','通知存款规则。')['passed'])
    def test_exact_remaining_derived(self):
        q='通知存款存入7万元，支取3万元，剩余金额是多少'
        result=self.check(q,'按题设支取后剩余金额为40000元。[1]','通知存款公开说明。')
        self.assertTrue(result['passed']);self.assertTrue(result['numeric_support']['scenario']['remaining_derived'])
    def test_arbitrary_calculation_not_allowed(self):
        self.assertFalse(self.check('通知存款存入7万元，支取3万元','支取后剩余金额为60000元。[1]','通知存款公开说明。')['passed'])
    def test_cannot_borrow_bank_minimum_as_remaining(self):
        self.assertFalse(self.check('存入7万元，支取3万元','按题设支取后剩余金额为50000元。[1]','最低留存金额5万元。')['passed'])
    def test_scenario_marker_does_not_allow_wrong_role(self):
        self.assertFalse(self.check('存入7万元，支取3万元','按题设剩余金额为30000元。[1]','公开说明。')['passed'])
    def test_scenario_cannot_launder_fee(self):
        self.assertFalse(self.check('通知存款七万元取三万元后剩四万元','手续费30000元。[1]','最低支取金额5万元。')['passed'])
    def test_scenario_inconsistency(self):
        self.assertEqual(money_scenario('存入7万元，支取3万元，剩余5万元')['status'],'inconsistent')
    def test_negative_amount(self):
        self.assertEqual(money_scenario('存入-7万元，支取3万元')['status'],'invalid')

class ConditionTests(unittest.TestCase):
    def test_both_conditions_answered_with_exact_bindings(self):
        s=build_system(docs=[notice_doc()]);s.rag_system.llm=Mock(side_effect=AssertionError('no model needed'))
        r=s.query_result('按通知存款说明，七万元取三万元后剩四万元，符合留存要求吗')
        self.assertEqual(r.decision,'answered');self.assertIn('最低支取金额',r.answer);self.assertIn('最低留存金额',r.answer)
        self.assertIn('30000元',r.answer);self.assertIn('40000元',r.answer);self.assertEqual(r.citations[0]['block_id'],META['parent_id'])
        self.assertEqual(r.diagnostics['generation_mode'],'source_bound_deterministic_notice_conditions')
    def test_true_conditions_do_not_guarantee_operation(self):
        s=build_system(docs=[notice_doc()]);r=s.query_result('通知存款存入12万元，支取5万元，是否符合金额条件')
        self.assertEqual(r.decision,'answered');self.assertIn('不能据此保证办理成功',r.answer)
    def test_inconsistent_amount_clarifies(self):
        r=build_system(docs=[notice_doc()]).query_result('通知存款存入7万元取3万元后剩5万元，是否满足要求')
        self.assertEqual(r.decision,'clarify');self.assertIn(config.DISCLAIMER,r.answer)
    def test_conflicting_source_minima_disable_deterministic(self):
        docs=[notice_doc('最低支取金额5万元。\n最低支取金额10万元。\n最低留存金额5万元。')]
        self.assertIsNone(notice_answer('通知存款存入7万元取3万元后剩4万元，是否满足要求',docs,'业务咨询'))
    def test_missing_condition_source_not_invented(self):
        self.assertIsNone(notice_answer('通知存款存入7万元取3万元后剩4万元，是否满足要求',[notice_doc('最低支取金额5万元。')],'业务咨询'))
    def test_foreign_currency_not_assumed_rmb(self):
        self.assertIsNone(notice_answer('通知存款存入7万美元取3万美元是否满足要求',[notice_doc()],'业务咨询'))
    def test_foreign_currency_source_not_used_as_rmb(self):
        source=notice_doc('美元通知存款最低支取金额和最低留存金额均为5万元。')
        self.assertIsNone(notice_answer('通知存款存入7万元取3万元后剩4万元，是否满足要求',[source],'业务咨询'))
    def test_interest_question_not_replaced_by_condition_answer(self):
        self.assertIsNone(notice_answer('通知存款存入7万元取3万元后剩4万元，利息怎么算',[notice_doc()],'业务咨询'))
    def test_scenario_not_answered_by_generic_faq(self):
        q='通知存款存入7万元取3万元后剩4万元，是否满足要求'
        s=build_system(rows=[faq_row(q)],docs=[notice_doc()]);s.bm25_search.search_record=Mock(side_effect=AssertionError('no generic FAQ'))
        self.assertEqual(s.query_result(q).decision,'answered');s.bm25_search.search_record.assert_not_called()
    def test_structured_stream_same_validation(self):
        s=build_system(docs=[notice_doc()]);text=''.join(x[0] for x in s.query_stream('通知存款存入7万元取3万元后剩4万元，是否满足要求'))
        self.assertIn('最低支取金额',text);self.assertEqual(text.count(config.DISCLAIMER),1)
    def test_agent_conditions_repair_once(self):
        doc=Document(page_content='代理开户：出具代理人、被代理人的有效身份证件及合法委托书。',metadata=META.copy())
        s=build_system(docs=[doc]);s.rag_system.llm=Mock(side_effect=['代理人需出示有效身份证件。[1]','代理人和被代理人需出示各自有效身份证件，并提供合法委托书。[1]'])
        r=s.query_result('代理开户需要哪些材料');self.assertEqual(r.decision,'answered');self.assertEqual(s.rag_system.llm.call_count,2);self.assertTrue(r.diagnostics['repair']['passed'])
    def test_out_of_range_citation_retried_once_then_rejected(self):
        s=build_system(answer='需要代理人身份证。[9]');s.rag_system.llm=Mock(return_value='需要代理人身份证。[9]')
        r=s.query_result('代理开户需要哪些材料')
        self.assertEqual(r.decision,'insufficient_evidence');self.assertEqual(s.rag_system.llm.call_count,2)
        self.assertFalse(r.diagnostics['citation_repair']['passed'])
    def test_investment_gate_precedes_deterministic(self):
        r=build_system(docs=[notice_doc()]).query_result('推荐通知存款，我存入7万元取3万元是否划算')
        self.assertEqual(r.decision,'refused')
