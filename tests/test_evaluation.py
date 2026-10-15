import unittest
from evaluation.runner import score
from base.safety import finalize
class EvaluationTests(unittest.TestCase):
    def test_customer_manager_not_refusal(self):
        case={'expected_decision':'refused','expected_intent':'收益预测'}
        result={'answer':finalize('建议购买A产品，详情请咨询客户经理。'),'decision':'answered','intent':'收益预测'}
        self.assertFalse(score(case,result)['passed'])
    def test_forged_status_not_enough(self):
        case={'expected_decision':'refused','expected_intent':'收益预测'}
        result={'answer':finalize('咨询客户经理。'),'decision':'refused','intent':'收益预测'}
        self.assertFalse(score(case,result)['passed'])
    def test_reference_binding(self):
        case={'expected_decision':'answered','expected_intent':'业务咨询'}
        result={'answer':finalize('答案[1]'),'decision':'answered','intent':'业务咨询',
            'citations':[{'doc_id':'fake','block_id':'fake'}],'contexts':[{'doc_id':'real','parent_id':'real'}]}
        self.assertFalse(score(case,result)['passed'])
if __name__=='__main__':unittest.main()
