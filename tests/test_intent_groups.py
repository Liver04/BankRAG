import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class IntentGroupTests(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'rag_qa/classify_data/context_v2_1/data.jsonl'
        self.rows=[json.loads(s) for s in self.path.read_text(encoding='utf-8').splitlines()]
    def test_hash_matches_manifest(self):
        m=json.loads((self.path.parent/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(m['data_sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_semantic_families_disjoint(self):
        train={r['semantic_family'] for r in self.rows if r['split']=='train'};val={r['semantic_family'] for r in self.rows if r['split']=='validation'}
        self.assertFalse(train&val);self.assertEqual(len(train|val),55)
    def test_same_family_all_variants_together(self):
        for name in {r['semantic_family'] for r in self.rows}:
            self.assertEqual(len({r['split'] for r in self.rows if r['semantic_family']==name}),1)
    def test_exact_old_questions_excluded(self):
        norm=lambda s:''.join(c for c in s if c.isalnum())
        qs={norm(t['question']) for c in map(json.loads,(ROOT/'evaluation/holdout_v1_1/questions.jsonl').read_text(encoding='utf-8').splitlines()) for t in c['turns']}
        self.assertFalse(qs & {norm(r['query']) for r in self.rows})
    def test_each_label_in_each_partition(self):
        for split in ('train','validation'):self.assertEqual(len({r['label'] for r in self.rows if r['split']==split}),5)
