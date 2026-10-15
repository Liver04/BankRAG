"""Prepare blinded reviewer packets and import real independent scores.

Empty forms stay pending. No LLM calls, automatic score completion, or identity
verification claim. Reviewer attestations must be supplied by real people.
"""
import argparse,hashlib,json,random
import math
from pathlib import Path
from collections import Counter,defaultdict

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def readl(path):return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]
def dump(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def writel(path,rows):Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')

def prepare(run,pack,out):
    run,pack,out=map(Path,(run,pack,out));manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='collected' or not manifest.get('runtime_stable'):raise ValueError('stable_complete_run_required')
    if sha(run/'traces.json')!=manifest['trace_sha256'] or sha(pack/'answer_key.jsonl')!=manifest['gold_sha256']:raise ValueError('run_or_gold_changed')
    out.mkdir(exist_ok=False);gold={t['turn_id']:t for c in readl(pack/'answer_key.jsonl') for t in c['turns']}
    rows=json.loads((run/'traces.json').read_text(encoding='utf-8'))['rows'];random.Random(20261014).shuffle(rows)
    questions={c['case_id']:c for c in readl(pack/'questions.jsonl')};queue=[];mapping=[];counts=Counter();sample=[]
    for i,row in enumerate(rows,1):
        rid=f'BLIND-{i:03d}';g=gold[row['turn_id']];r=row.get('result') or {}
        blank={'reviewer_id':None,'independent_of_development':None,'action_score':None,'point_scores':{p['point_id']:None for p in g['required_points']},'citation_score':None,'provenance_time_score':None,'communication_score':None,'hard_failures':[],'claim_evidence_map':[],'rationale':None,'reviewed_at':None}
        queue.append({'review_id':rid,'question':row['question'],'scenario_questions':[t['question'] for t in questions[row['case_id']]['turns'][:row['turn_index']]],
            'actual_visible_answer':row['actual_visible_text'],'actual_prior_history':row.get('history_after',[])[:-1],
            'contexts':[{k:v for k,v in d.items() if k not in ('file_path','parent_content','timestamp')} for d in r.get('contexts',[])],
            'citations':r.get('citations',[]),'rubric':{k:g[k] for k in ('expected_action','required_points','forbidden_outcomes','evidence')},
            'reviewers':[dict(blank),dict(blank)],'arbitration':None,'final_status':'not_reviewed'})
        mapping.append({'review_id':rid,'turn_id':row['turn_id'],'transport':row['transport'],'case_id':row['case_id']})
        # Pre-register a balanced calibration subset before seeing human scores.
        stratum=(row['transport'],g['expected_action'])
        if counts[stratum]<6:sample.append(rid);counts[stratum]+=1
    writel(out/'review_queue.jsonl',queue);dump(out/'private_mapping.json',{'rows':mapping})
    m={'status':'pending_independent_humans','trace_sha256':manifest['trace_sha256'],'gold_sha256':manifest['gold_sha256'],'rows':len(queue),
       'calibration_sample_ids':sample,'minimum_calibration_rows':30,'minimum_human_pass_and_fail_each':5,'mapping_sha256':sha(out/'private_mapping.json'),
       'review_queue_sha256':sha(out/'review_queue.jsonl'),
       'independent_human_reviews':0,'blindness':'Mask transport, case ID, model scores and retrieval diagnostics; reviewers still see question, gold and actual evidence','identity_verification':'Human attestation only; no external identity validation'}
    dump(out/'manifest.json',m)
    (out/'README.md').write_text('# 双人核验待评材料\n\n分别复制 review_queue.jsonl 给两位未参与开发的评审，不分发 private_mapping.json 或机器评分。\n\n两人独立填写自己的 reviewer 槽位；评分 0/1/2；业务事实题引用/范围不可留空。每个事实填写 claim_evidence_map。分歧由第三位真人填写 arbitration。禁止用模型代填独立人工分数。\n\n优先完成 manifest 中预登记的校准样本，再评剩余样本。未评和分歧未裁决均保留 pending；暂不发布业务准确率或裁判可信度。\n\n表内包含本场景问题顺序；多轮历史实际可见输出以实际痕迹为准。原始 traces.json 由管理员留存。\n',encoding='utf-8')
    return m

def validate_review(r,points,requires_facts):
    if not isinstance(r,dict) or not isinstance(r.get('reviewer_id'),str) or not r['reviewer_id'].strip() or r.get('independent_of_development') is not True:return None
    if not r.get('rationale') or not r.get('reviewed_at'):return None
    value=lambda x:type(x) is int and x in (0,1,2)
    if not all(value(r.get(k)) for k in ('action_score','communication_score')):return None
    if set(r.get('point_scores',{}))!=set(points) or not all(value(v) for v in r['point_scores'].values()):return None
    for k in ('citation_score','provenance_time_score'):
        if not value(r.get(k)) and (requires_facts or r.get(k) is not None):return None
    if not isinstance(r.get('hard_failures'),list) or not set(r['hard_failures'])<={'HF01','HF02','HF03','HF04','HF05'}:return None
    if not isinstance(r.get('claim_evidence_map'),list):return None
    if requires_facts and not r['claim_evidence_map']:return None
    for claim in r['claim_evidence_map']:
        if not isinstance(claim,dict) or not claim.get('claim') or claim.get('support') not in ('supported','partial','unsupported','contradicted') or not isinstance(claim.get('citation_numbers'),list):return None
    return {k:r[k] for k in ('action_score','point_scores','citation_score','provenance_time_score','communication_score','hard_failures')}

def review_pass(r,material):
    dimensions=[(.2,r['action_score']),(.4,sum(r['point_scores'].values())/max(1,len(r['point_scores']))),(.2,r['citation_score']),(.15,r['provenance_time_score']),(.05,r['communication_score'])]
    active=[(w,v) for w,v in dimensions if v is not None];score=100*sum(w*v/2 for w,v in active)/sum(w for w,v in active)
    return not r['hard_failures'] and r['action_score']==2 and all(r['point_scores'][k]==2 for k in material) and r['citation_score'] in (2,None) and r['provenance_time_score'] in (2,None) and score>=90

def binary_kappa(pairs):
    if not pairs:return None
    n=len(pairs);observed=sum(a==b for a,b in pairs)/n
    pa=sum(a for a,b in pairs)/n;pb=sum(b for a,b in pairs)/n
    expected=pa*pb+(1-pa)*(1-pb)
    return (observed-expected)/(1-expected) if expected<1 else None

def wilson(success,total):
    if not total:return None
    z=1.96;p=success/total;denom=1+z*z/total
    center=(p+z*z/(2*total))/denom
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denom
    return [max(0,center-half),min(1,center+half)]

def calibration_ready(sample,final,pairs,minimum,minimum_each):
    return (set(sample)<=set(final) and len(pairs)>=minimum and
            min(sum(a for a,b in pairs),sum(not a for a,b in pairs))>=minimum_each)

def summarize(packet,completed,judge_run=None,judge_file=None):
    packet=Path(packet);m=json.loads((packet/'manifest.json').read_text(encoding='utf-8'))
    if sha(packet/'private_mapping.json')!=m['mapping_sha256']:raise ValueError('mapping_changed')
    if sha(packet/'review_queue.jsonl')!=m['review_queue_sha256']:raise ValueError('original_queue_changed')
    original={r['review_id']:r for r in readl(packet/'review_queue.jsonl')};submitted=readl(completed)
    if len({r['review_id'] for r in submitted})!=len(submitted):raise ValueError('duplicate_review_id')
    agreements=[];reviewer_pairs=[];final={};pending=[]
    immutable=('question','scenario_questions','actual_visible_answer','actual_prior_history','contexts','citations','rubric')
    for row in submitted:
        rid=row['review_id']
        if rid not in original or any(row.get(k)!=original[rid].get(k) for k in immutable):raise ValueError('review_payload_changed:'+rid)
        rubric=row['rubric'];points=[p['point_id'] for p in rubric['required_points']];material=[p['point_id'] for p in rubric['required_points'] if p['material']]
        validated=[validate_review(x,points,rubric['expected_action']=='answer') for x in row.get('reviewers',[])]
        if len(validated)!=2 or not all(validated) or row['reviewers'][0]['reviewer_id']==row['reviewers'][1]['reviewer_id']:pending.append(rid);continue
        a,b=validated;agreements.append(a==b);reviewer_pairs.append((review_pass(a,material),review_pass(b,material)))
        if a!=b:
            arb=row.get('arbitration');c=validate_review(arb,points,rubric['expected_action']=='answer')
            if not c or arb['reviewer_id'] in {x['reviewer_id'] for x in row['reviewers']}:pending.append(rid);continue
            a=c
        final[rid]=review_pass(a,material)
    report={'status':'pending_human_review','submitted_rows':len(submitted),'two_reviewer_rows':len(agreements),'completed_adjudicated_rows':len(final),'total_rows':m['rows'],'pending_rows':m['rows']-len(final),'reviewer_dimension_exact_agreement':sum(agreements)/len(agreements) if agreements else None,'reviewer_pass_kappa':binary_kappa(reviewer_pairs),'calibration':None,'limits':'Reviewer independence is attested, not externally verified; partial coverage must not be reported as full accuracy'}
    if judge_run is not None:
        run=Path(judge_run);jm=json.loads((run/'scoring_manifest.json').read_text(encoding='utf-8'))
        if jm['trace_sha256']!=m['trace_sha256'] or jm['gold_sha256']!=m['gold_sha256']:raise ValueError('judge_run_mismatch')
        scores=readl(judge_file or run/'model_assisted_scores.jsonl');lookup={(s['turn_id'],s['transport']):s for s in scores}
        mapping={x['review_id']:x for x in json.loads((packet/'private_mapping.json').read_text(encoding='utf-8'))['rows']}
        pairs=[]
        for rid in m['calibration_sample_ids']:
            x=mapping[rid];s=lookup.get((x['turn_id'],x['transport']))
            if rid in final and s and s.get('judge_error') is None and type(s.get('provisional_pass')) is bool:pairs.append((final[rid],s['provisional_pass']))
        positives=sum(a for a,b in pairs);negatives=len(pairs)-positives
        eligible=calibration_ready(m['calibration_sample_ids'],final,pairs,m['minimum_calibration_rows'],m['minimum_human_pass_and_fail_each'])
        false_accepts=sum(not a and b for a,b in pairs)
        report['calibration']={'status':'computable' if eligible else 'insufficient_pre_registered_human_scores','pre_registered_rows':len(m['calibration_sample_ids']),'human_reviewed_pre_registered':len(set(m['calibration_sample_ids'])&set(final)),'matched_rows':len(pairs),'unmatched_or_judge_error_rows':len(m['calibration_sample_ids'])-len(pairs),'human_passes':positives,'human_failures':negatives,'judge_agreement':sum(a==b for a,b in pairs)/len(pairs) if eligible else None,'judge_pass_kappa':binary_kappa(pairs) if eligible else None,'judge_false_accept_rate':false_accepts/negatives if eligible else None,'judge_false_accept_rate_wilson_95pct':wilson(false_accepts,negatives) if eligible else None,'meaning':'Requires human review of the entire pre-registered subset. Agreement is conditional on valid judge outputs; errors remain counted. Not certification of judge reliability'}
    if len(final)==m['rows']:report['status']='fully_human_reviewed'
    return report

def main():
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='mode',required=True)
    a=sp.add_parser('prepare');a.add_argument('--run',type=Path,required=True);a.add_argument('--pack',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    a=sp.add_parser('import');a.add_argument('--packet',type=Path,required=True);a.add_argument('--completed',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--judge-run',type=Path);a.add_argument('--judge-file',type=Path)
    a=p.parse_args()
    if a.mode=='prepare':r=prepare(a.run,a.pack,a.out)
    else:
        if a.out.exists():raise ValueError('refuse_overwrite_report')
        r=summarize(a.packet,a.completed,a.judge_run,a.judge_file);dump(a.out,r)
    print(json.dumps(r,ensure_ascii=False));return 0 if a.mode=='prepare' or r['status']=='fully_human_reviewed' else 2
if __name__=='__main__':raise SystemExit(main())
