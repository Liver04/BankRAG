import json,tempfile,unittest
from pathlib import Path
from evaluation import human_calibration as hc

class HumanCalibrationTests(unittest.TestCase):
    def fixture(self,root):
        run=root/'run';pack=root/'pack';run.mkdir();pack.mkdir()
        gold={'turn_id':'T1','question':'规则是什么','source_filter':None,'expected_action':'answer','required_points':[{'point_id':'K1','text':'需出示证件','material':True}],'forbidden_outcomes':[],'evidence':[]}
        hc.writel(pack/'answer_key.jsonl',[{'turns':[gold]}]);hc.writel(pack/'questions.jsonl',[{'case_id':'C1','turns':[{'question':'规则是什么'}]}])
        hc.dump(run/'traces.json',{'rows':[{'case_id':'C1','turn_id':'T1','turn_index':1,'question':'规则是什么','transport':'http','actual_visible_text':'需出示证件[1]','result':{'contexts':[],'citations':[{'number':1}]},'history_after':[]}]})
        hc.dump(run/'manifest.json',{'status':'collected','runtime_stable':True,'trace_sha256':hc.sha(run/'traces.json'),'gold_sha256':hc.sha(pack/'answer_key.jsonl')})
        packet=root/'packet';hc.prepare(run,pack,packet);return packet,run
    def completed(self,packet):
        rows=hc.readl(packet/'review_queue.jsonl')
        for i,r in enumerate(rows[0]['reviewers']):
            r.update(reviewer_id='real-'+str(i),independent_of_development=True,action_score=2,point_scores={'K1':2},citation_score=2,provenance_time_score=2,communication_score=2,claim_evidence_map=[{'claim':'需出示证件','citation_numbers':[1],'support':'supported'}],rationale='test fixture, not real human review',reviewed_at='2026-10-13')
        out=packet/'completed.jsonl';hc.writel(out,rows);return out,rows
    def test_empty_forms_are_pending(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));r=hc.summarize(packet,packet/'review_queue.jsonl')
            self.assertEqual(r['completed_adjudicated_rows'],0);self.assertIsNone(r['reviewer_dimension_exact_agreement']);self.assertIsNone(r['calibration'])
    def test_dual_complete_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));out,_=self.completed(packet);self.assertEqual(hc.summarize(packet,out)['status'],'fully_human_reviewed')
    def test_same_identity_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));out,rows=self.completed(packet);rows[0]['reviewers'][1]['reviewer_id']='real-0';hc.writel(out,rows)
            self.assertEqual(hc.summarize(packet,out)['completed_adjudicated_rows'],0)
    def test_disagreement_needs_arbitration(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));out,rows=self.completed(packet);rows[0]['reviewers'][1]['point_scores']['K1']=0;hc.writel(out,rows)
            self.assertEqual(hc.summarize(packet,out)['completed_adjudicated_rows'],0)
    def test_changed_answer_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));out,rows=self.completed(packet);rows[0]['actual_visible_answer']='改成正确答案';hc.writel(out,rows)
            with self.assertRaisesRegex(ValueError,'review_payload_changed'):hc.summarize(packet,out)
    def test_nonindependent_reviewer_rejected(self):
        r={'reviewer_id':'a','independent_of_development':False}
        self.assertIsNone(hc.validate_review(r,[],False))
    def test_no_samples_has_no_kappa_or_interval(self):
        self.assertIsNone(hc.binary_kappa([]));self.assertIsNone(hc.wilson(0,0))
    def test_cannot_calibrate_easy_partial_selection(self):
        pairs=[(True,True),(False,False)]
        self.assertFalse(hc.calibration_ready(['A','B','C'],{'A':True,'B':False},pairs,2,1))
        self.assertTrue(hc.calibration_ready(['A','B'],{'A':True,'B':False},pairs,2,1))
    def test_zero_observed_failures_not_zero_uncertainty(self):
        self.assertGreater(hc.wilson(0,30)[1],0)
        self.assertEqual(hc.binary_kappa([(True,True),(False,False)]),1)
    def test_partial_material_fails(self):
        r={'action_score':2,'point_scores':{'K1':1},'citation_score':2,'provenance_time_score':2,'communication_score':2,'hard_failures':[]}
        self.assertFalse(hc.review_pass(r,['K1']))
    def test_judge_different_run_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            packet,run=self.fixture(Path(td));hc.dump(run/'scoring_manifest.json',{'trace_sha256':'different','gold_sha256':'different'})
            with self.assertRaisesRegex(ValueError,'judge_run_mismatch'):hc.summarize(packet,packet/'review_queue.jsonl',run)
    def test_hash_changed_queue_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            packet,_=self.fixture(Path(td));out,rows=self.completed(packet);hc.writel(packet/'review_queue.jsonl',rows)
            with self.assertRaisesRegex(ValueError,'original_queue_changed'):hc.summarize(packet,out)
