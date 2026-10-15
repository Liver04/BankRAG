"""Post-run local BERT/rule diagnosis; never changes weights or regenerates answers."""
import argparse
from collections import Counter,defaultdict
import hashlib,json,math
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
def hash_file(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def percentile(values,p):
 values=sorted(values)
 return values[max(0,math.ceil(len(values)*p)-1)] if values else None


def main():
 p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True)
 p.add_argument('--pack',type=Path,default=PROJECT/'evaluation/holdout_v1_1');args=p.parse_args()
 manifest=json.loads((args.run_dir/'manifest.json').read_text(encoding='utf-8'))
 if manifest['status']!='collected':raise ValueError('complete_first_run_required')
 from base.config import config
 from rag_qa.core.query_classifier import QueryClassifier
 model_path=Path(config.MODELS_DIR)/'finance_intent_classifier/model.safetensors'
 before=hash_file(model_path)
 if before!=manifest['runtime_before']['runtime_files_sha256']['bert/model.safetensors']:raise ValueError('model_changed')
 classifier=QueryClassifier()
 if classifier.model is None:raise ValueError('classifier_unavailable')
 gold=[t for line in (args.pack/'answer_key.jsonl').read_text(encoding='utf-8').splitlines() for t in json.loads(line)['turns']]
 qs=[t['question'] for t in gold]
 lengths=[len(classifier.tokenizer.encode(q,truncation=False)) for q in qs]
 rows=[]
 for start in range(0,len(qs),16):
  inputs=classifier.tokenizer(qs[start:start+16],truncation=True,padding=True,max_length=128,return_tensors='pt')
  with classifier.torch.no_grad():logits=classifier.model(**{k:v.to(classifier.device) for k,v in inputs.items()}).logits
  probabilities=logits.softmax(dim=-1).cpu().tolist()
  for offset,probs in enumerate(probabilities):
   i=start+offset;t=gold[i];q=qs[i];index=max(range(len(probs)),key=lambda x:probs[x]);bert=classifier.LABELS[index]
   rule=classifier.rule_category(q);match='contextual_rule' if rule else None
   effective=classifier.predict_category(q)
   expected=t['expected_intent_diagnostic']
   rows.append({'turn_id':t['turn_id'],'question':q,'expected_intent_provisional':expected,'bert_only':bert,
      'rule_override':rule,'rule_matched_text':match,'effective_intent':effective,'token_length':lengths[i],
      'truncated':lengths[i]>128,'bert_matches_provisional':bert==expected,'effective_matches_provisional':effective==expected,
      'softmax_max_uncalibrated':max(probs)})
 training=[json.loads(s) for s in (PROJECT/'rag_qa/classify_data/finance_intent_merged.jsonl').read_text(encoding='utf-8').splitlines()]
 train_lengths=[len(classifier.tokenizer.encode(x['query'],truncation=False)) for x in training]
 matrix=defaultdict(Counter)
 for r in rows:matrix[r['expected_intent_provisional']][r['effective_intent']]+=1
 report={'meaning':'Post-hoc local inference vs provisional labels, NOT independent classification benchmark. Softmax is not calibrated confidence.',
    'model_sha256':before,'model_unchanged':hash_file(model_path)==before,'cases':len(rows),
    'bert_only_matches_provisional':sum(r['bert_matches_provisional'] for r in rows),
    'effective_matches_provisional':sum(r['effective_matches_provisional'] for r in rows),
    'rule_override_count':sum(r['rule_override'] is not None for r in rows),
    'incorrect_rule_overrides':sum(r['rule_override'] is not None and not r['effective_matches_provisional'] for r in rows),
    'truncated_questions':sum(r['truncated'] for r in rows),
    'holdout_tokens':{'p50':percentile(lengths,.5),'p95':percentile(lengths,.95),'max':max(lengths)},
    'training_tokens':{'n':len(training),'p50':percentile(train_lengths,.5),'p95':percentile(train_lengths,.95),'max':max(train_lengths)},
    'effective_distribution':dict(Counter(r['effective_intent'] for r in rows)),
    'confusion_vs_provisional':{k:dict(v) for k,v in matrix.items()},'rows':rows}
 out=args.run_dir/'intent_diagnosis.json'
 if out.exists():raise ValueError('refuse_to_overwrite_posthoc_diagnosis')
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('INTENT_DIAGNOSIS',json.dumps({k:report[k] for k in ['cases','bert_only_matches_provisional','effective_matches_provisional','rule_override_count','incorrect_rule_overrides','truncated_questions','model_unchanged']},ensure_ascii=False),flush=True)
 return 0


if __name__=='__main__':raise SystemExit(main())
