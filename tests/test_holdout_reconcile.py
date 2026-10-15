import unittest
from evaluation.holdout_score_reconcile import validate_saved
from evaluation.holdout_score import adjudicate
from tests import test_holdout_score as score_tests


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        f=score_tests.HoldoutScoreTests();f.setUp();self.g=f.g;self.r=f.r;self.j=f.j

    def test_refusal_na_keeps_original_scores_and_fails(self):
        self.r['result']['decision']='refused';self.j.update(action_score=0,citation_score=None,provenance_time_score=None)
        self.j['point_scores']={'K1':0,'K2':0}
        j,tags,recovered=validate_saved(self.j,self.g,self.r['result'])
        self.assertTrue(recovered);self.assertIsNone(j['citation_score']);self.assertIsNone(self.j['citation_score'])
        self.assertFalse(adjudicate(self.r,self.g,j)['provisional_pass'])

    def test_actual_answer_cannot_na(self):
        self.j['citation_score']=None
        with self.assertRaises(ValueError):validate_saved(self.j,self.g,self.r['result'])

    def test_unmapped_tag_preserved_not_numeric_change(self):
        self.j['error_labels']=['INSUFFICIENT_EVIDENCE']
        j,tags,_=validate_saved(self.j,self.g,self.r['result'])
        self.assertEqual(tags,['INSUFFICIENT_EVIDENCE'])
        self.assertEqual(j['point_scores'],self.j['point_scores']);self.assertEqual(j['action_score'],self.j['action_score'])
        self.assertEqual(self.j['error_labels'],['INSUFFICIENT_EVIDENCE'])

    def test_invalid_scores_still_rejected(self):
        self.j['action_score']=3
        with self.assertRaises(ValueError):validate_saved(self.j,self.g,self.r['result'])


if __name__=='__main__':unittest.main()
