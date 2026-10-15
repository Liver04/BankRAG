import unittest
from fastapi.testclient import TestClient
from app import create_app
from base.config import config
from tests.support import build_system
from evaluation.holdout_runner import run_routes,protocol_checks


class HoldoutRunnerTests(unittest.TestCase):
    def test_real_history_and_separate_transport_sessions(self):
        cases=[{'case_id':'X1','category':'unit','turns':[
            {'turn_id':'X1/T1','question':'测试公开存款规则甲','source_filter':None},
            {'turn_id':'X1/T2','question':'测试公开存款规则乙','source_filter':None}]},
            {'case_id':'X2','category':'unit','turns':[
            {'turn_id':'X2/T1','question':'测试公开存款规则丙','source_filter':None}]}]
        system=build_system();written=[]
        with TestClient(create_app(system,allow_trace=True)) as client:
            rows=run_routes(client,cases,['http','websocket'],config.DISCLAIMER,written.append,workers=1)
        self.assertEqual(len(rows),6);self.assertEqual(len(written),6)
        x=[r for r in rows if r['case_id']=='X1']
        self.assertEqual(len({r['session_id'] for r in x}),2)
        for transport in ['http','websocket']:
            rr=[r for r in x if r['transport']==transport]
            self.assertEqual([len(r['history_after']) for r in rr],[1,2])
            self.assertEqual(rr[1]['history_after'][0]['answer'],rr[0]['result']['answer'])
            self.assertTrue(all(r['protocol']['history_round_count_correct'] for r in rr))
        for r in rows:
            self.assertTrue(r['protocol']['final_disclaimer_once'])
            self.assertTrue(r['protocol']['citation_bindings_valid'])
            if r['transport']=='websocket':
                self.assertTrue(r['protocol']['early_disclaimer'])
                self.assertTrue(r['protocol']['visible_body_matches_final'])

    def test_http_failure_retained(self):
        cases=[{'case_id':'Y','category':'unit','turns':[
            {'turn_id':'Y/T1','question':'测试拒绝非法来源','source_filter':'invalid'}]}]
        system=build_system();written=[]
        with TestClient(create_app(system,allow_trace=True)) as client:
            rows=run_routes(client,cases,['http'],config.DISCLAIMER,written.append)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['http_status'],422)
        self.assertFalse(rows[0]['protocol']['transport_completed'])
        self.assertTrue(rows[0]['protocol']['final_disclaimer_once'])

    def test_ws_error_retained(self):
        cases=[{'case_id':'Y','category':'unit','turns':[
            {'turn_id':'Y/T1','question':'测试拒绝非法来源','source_filter':'invalid'}]}]
        with TestClient(create_app(build_system(),allow_trace=True)) as client:
            rows=run_routes(client,cases,['websocket'],config.DISCLAIMER,lambda r:None)
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['transport_error'])
        self.assertEqual(rows[0]['frames'][-1]['type'],'error')
        self.assertFalse(rows[0]['protocol']['transport_completed'])

    def test_version_is_part_of_citation_binding(self):
        r={'transport':'http','http_status':200,'transport_error':None,'history_status':200,'history_after':[{}],
           'result':{'answer':config.DISCLAIMER,'decision':'answered',
            'citations':[{'doc_id':'d','block_id':'b','version':'wrong'}],
            'contexts':[{'doc_id':'d','parent_id':'b','version':'v'}]}}
        self.assertFalse(protocol_checks(r,config.DISCLAIMER)['citation_bindings_valid'])


if __name__=='__main__':unittest.main()
