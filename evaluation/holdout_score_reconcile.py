"""Repair scoring-schema handling from the SAME saved judge output; no model calls.

Original scores/raw outputs remain immutable. No gold, A/F/C/T/U value or answer changes.
"""
import argparse
import copy
import json
from pathlib import Path
from evaluation.holdout_score import ERRORS,adjudicate,summary,sha,dump,readl,validate_judgment

PROJECT=Path(__file__).resolve().parents[1]


def validate_saved(raw,gold,result):
    j=copy.deepcopy(raw)
    labels=j.get('error_labels')
    if not isinstance(labels,list) or not all(isinstance(s,str) and 0<len(s)<100 for s in labels):
        raise ValueError('invalid_error_labels_type')
    unmapped=[s for s in labels if s not in ERRORS]
    j['error_labels']=[s for s in labels if s in ERRORS]
    # Validate the unchanged scores rigorously. N/A is about the ACTUAL response,
    # not whether the question originally SHOULD have received an answer.
    validation_copy=copy.deepcopy(j)
    recover_na=gold['expected_action']=='answer' and result.get('decision')!='answered'
    if recover_na:
        # Sentinel values only for the old schema validator. Adjudication below
        # uses the ORIGINAL null dimensions, original gold and original scores.
        for k in ('citation_score','provenance_time_score'):
            if validation_copy.get(k) is None:validation_copy[k]=0
    validate_judgment(validation_copy,gold,result)
    return j,unmapped,recover_na


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--pack',type=Path,default=PROJECT/'evaluation/holdout_v1_1');a=p.parse_args();run=a.run_dir
    manifest=json.loads((run/'scoring_manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] not in ('scored','partially_scored'):raise ValueError('first_judge_run_not_finished')
    trace=json.loads((run/'traces.json').read_text(encoding='utf-8'));rows=trace['rows']
    gold={t['turn_id']:t for c in readl(a.pack/'answer_key.jsonl') for t in c['turns']}
    if trace['gold_sha256']!=sha(a.pack/'answer_key.jsonl'):raise ValueError('gold_changed')
    prior=readl(run/'model_assisted_scores.jsonl')
    if len(prior)!=len(rows):raise ValueError('incomplete_judge_attempts')
    indexed={(r['turn_id'],r['transport']):r for r in rows}
    output=run/'model_assisted_reconciled_scores.jsonl'
    if output.exists():raise ValueError('refuse_to_overwrite_reconciliation')
    records=[];changes=[]
    for s in prior:
        if not s['judge_error']:
            records.append(s);continue
        key=(s['turn_id'],s['transport']);row=indexed[key];g=gold[s['turn_id']]
        try:
            raw=json.loads(s['raw_judge_output'])
            j,unmapped,non_answer_na=validate_saved(raw,g,row.get('result') or {})
            recovered=adjudicate(row,g,j)
            recovered['schema_recovery']={'from_error':s['judge_error'],'non_answer_na':non_answer_na,
                'unmapped_tags_preserved':unmapped,'original_numeric_dimensions_unchanged':True,
                'original_raw_judge_output':s['raw_judge_output']}
            if g['expected_action']=='answer' and (row.get('result') or {}).get('decision')!='answered':
                assert not recovered['provisional_pass'],'A safe non-answer cannot pass an answerable case'
            records.append(recovered)
            changes.append({'turn_id':s['turn_id'],'transport':s['transport'],'non_answer_na':non_answer_na,
                            'unmapped_tags_preserved':unmapped,'pass_after':recovered['provisional_pass']})
        except Exception as exc:
            records.append(dict(s,reconciliation_error=type(exc).__name__))
    output.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    result=summary(records,rows);dump(run/'model_assisted_reconciled_summary.json',result)
    audit={'meaning':'Schema reconciliation only. No additional model calls, regeneration, retrieval, gold edits or numeric-score changes.',
        'original_scores_sha256':sha(run/'model_assisted_scores.jsonl'),'original_judge_errors':sum(s['judge_error'] is not None for s in prior),
        'recovered':len(changes),'remaining_judge_errors':result['judge_errors'],'reconciler_sha256':sha(__file__),'changes':changes}
    dump(run/'schema_reconciliation.json',audit)
    print('SCHEMA_RECONCILIATION',json.dumps({k:audit[k] for k in ['original_judge_errors','recovered','remaining_judge_errors']},ensure_ascii=False))
    print('RECONCILED_ASSISTED_SCORE',json.dumps({k:result[k] for k in ['total_rows','scored','judge_errors','provisional_passed','human_scored']},ensure_ascii=False))
    return 0 if not result['judge_errors'] else 2


if __name__=='__main__':raise SystemExit(main())
