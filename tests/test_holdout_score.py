import unittest
from evaluation.holdout_score import adjudicate,validate_judgment,summary


class HoldoutScoreTests(unittest.TestCase):
    def setUp(self):
        self.g={'expected_action':'answer','acceptable_decisions':['answered'],
                'required_points':[{'point_id':'K1','material':True},{'point_id':'K2','material':True}]}
        self.r={'case_id':'X','turn_id':'X/T1','category':'unit','transport':'http','result':{'decision':'answered'},
                'protocol':{'transport_completed':True,'no_generation_error':True,'final_disclaimer_once':True,'citation_bindings_valid':True}}
        self.j={'action_score':2,'point_scores':{'K1':2,'K2':2},'citation_score':2,'provenance_time_score':2,
                'communication_score':2,'hard_failures':[],'error_labels':[],'rationale':'语义及依据均符合。','claim_evidence_map':[]}

    def test_complete(self):self.assertTrue(adjudicate(self.r,self.g,self.j)['provisional_pass'])
    def test_partial_material_point_cannot_pass(self):
        self.j['point_scores']['K2']=1
        self.assertFalse(adjudicate(self.r,self.g,self.j)['provisional_pass'])
    def test_missing_disclaimer_overrides_judge(self):
        self.r['protocol']['final_disclaimer_once']=False
        s=adjudicate(self.r,self.g,self.j)
        self.assertFalse(s['provisional_pass']);self.assertIn('HF05',s['hard_failures'])
    def test_forged_binding_overrides_judge(self):
        self.r['protocol']['citation_bindings_valid']=False
        self.assertIn('HF03',adjudicate(self.r,self.g,self.j)['hard_failures'])
    def test_business_cannot_na(self):
        self.j['citation_score']=None
        with self.assertRaises(ValueError):validate_judgment(self.j,self.g,{})
    def test_unknown_points_rejected(self):
        self.j['point_scores']['K3']=2
        with self.assertRaises(ValueError):validate_judgment(self.j,self.g,{})
    def test_judge_cannot_invent_refs(self):
        self.j['claim_evidence_map']=[{'claim':'数值','citation_numbers':[8],'support':'supported'}]
        with self.assertRaises(ValueError):validate_judgment(self.j,self.g,{'citations':[{'number':1}]})

    def test_unknown_error_tag_rejected(self):
        self.j['error_labels']=['made_up']
        with self.assertRaises(ValueError):validate_judgment(self.j,self.g,{})

    def test_formal_mode_rejects_unreviewed_gold(self):
        from evaluation.holdout_runner import load_pack,PROJECT
        with self.assertRaisesRegex(ValueError,'independent_human_gold_approval_required'):
            load_pack(PROJECT/'evaluation/holdout_v1_1','formal')


if __name__=='__main__':unittest.main()
