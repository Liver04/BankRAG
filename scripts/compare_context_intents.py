"""Post-development comparison against provisional old regression labels."""
import argparse,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rag_qa.core.query_classifier import QueryClassifier
from base.conversation import resolve_query
def main():
    p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--candidate',default='finance_intent_context_v2_1_candidate');p.add_argument('--old',type=Path);a=p.parse_args()
    paths={'old':a.old or a.models/'finance_intent_classifier','candidate':a.models/a.candidate}
    classifiers={name:QueryClassifier(model_path=path) for name,path in paths.items()}
    assert all(c.model is not None for c in classifiers.values())
    report={'meaning':'Development regression with provisional labels; NOT blind independent accuracy','models':{},'rows':[]}
    for name,c in classifiers.items():
        report['models'][name]={'bert_only_correct':0,'pipeline_correct':0,'model_sha256':hashlib.sha256((paths[name]/'model.safetensors').read_bytes()).hexdigest()}
    for case in map(json.loads,(ROOT/'evaluation/holdout_v1_1/answer_key.jsonl').read_text(encoding='utf-8').splitlines()):
        history=[]
        for turn in case['turns']:
            q=turn['question'];expected=turn['expected_intent_diagnostic'];row={'turn_id':turn['turn_id'],'expected_provisional':expected}
            for name,c in classifiers.items():
                raw=c._predict_bert(q);resolved,_=resolve_query(q,history)
                effective=c.predict_category(q if c.rule_category(q) or resolved is None else resolved)
                row[name]={'bert':raw,'effective':effective}
                report['models'][name]['bert_only_correct']+=raw==expected
                report['models'][name]['pipeline_correct']+=effective==expected
            history.append({'question':q,'answer':''});report['rows'].append(row)
    report['turns']=len(report['rows']);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
