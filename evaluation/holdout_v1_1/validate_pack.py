"""Offline pack integrity checks. Never imports BankRAG or calls a model/service.

Run from qa_system: python -B evaluation/holdout_v1/validate_pack.py
Exit 0 = artifact integrity passed, NOT model accuracy or human approval.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata


def sha(b):
    return hashlib.sha256(b).hexdigest()


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKC', s).lower() if c.isalnum())


def load_jsonl(p):
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('path_outside_project')
    return path


def old_texts(project, inventory):
    found = set()

    def keep(s):
        if isinstance(s, str) and 4 <= len(norm(s)) and len(s) <= 1500 and 'sk-' not in s:
            found.add(norm(s))

    def visit(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in {'question', 'query', 'user_input'} and isinstance(v, str):
                    keep(v)
                else:
                    visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    for item in inventory:
        p = inside(project, item['file'])
        if p.suffix == '.jsonl':
            for row in load_jsonl(p):
                keep(row.get('query'))
        elif p.suffix == '.json':
            visit(json.loads(p.read_text(encoding='utf-8-sig')))
        elif p.suffix == '.py':
            for node in ast.walk(ast.parse(p.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r'[\u4e00-\u9fff]', node.value):
                    keep(node.value)
    return found


def validate(project, pack):
    checks = []

    def check(name, condition, detail=None):
        checks.append(dict(check=name, passed=bool(condition), detail=detail))

    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    for rel, expected in manifest['artifacts_sha256'].items():
        p = inside(pack.parents[1], rel)
        check('artifact_sha256:' + rel, p.is_file() and sha(p.read_bytes()) == expected)

    cases = load_jsonl(pack / 'answer_key.jsonl')
    questions = load_jsonl(pack / 'questions.jsonl')
    review = load_jsonl(pack / 'review_records.jsonl')
    audit = json.loads((pack / 'contamination_audit.json').read_text(encoding='utf-8'))
    snapshot = json.loads((pack / 'source_snapshot.json').read_text(encoding='utf-8'))
    documents = {d['path']: d for d in snapshot['documents']}
    turns = [t for c in cases for t in c['turns']]
    check('scenario_count', len(cases) == 100)
    check('turn_count', len(turns) == 110)
    check('multi_turn_count', sum(c['case_type'] == 'multi_turn' for c in cases) == 10)
    check('case_ids_unique', len({c['case_id'] for c in cases}) == len(cases))
    check('turn_ids_unique', len({t['turn_id'] for t in turns}) == len(turns))
    check('questions_unique', len({norm(t['question']) for t in turns}) == len(turns))
    check('review_form_complete_and_unscored', len(review) == 110 and
          {r['turn_id'] for r in review} == {t['turn_id'] for t in turns} and
          all(r['candidate_answer'] is None and r['final_status'] == 'not_reviewed' and
              all(x['action_score'] is None for x in r['reviewers']) for r in review))
    check('gold_human_status_honest', all(c['gold_status'] == 'pending_independent_human_review' for c in cases))
    check('as_of_date_consistent', all(c['as_of_date'] == 20261013 for c in cases))
    check('question_only_payloads_match_gold',
          len(questions) == len(cases) and all(q['case_id'] == c['case_id'] and
          q['turns'] == [{k: t[k] for k in ('turn_id', 'question', 'source_filter')} for t in c['turns']]
          for q, c in zip(questions, cases)))
    check('question_file_has_no_answer_key', all(set(q) == {'case_id','category','as_of_date','jurisdiction','case_type','turns'} and
          all(set(t) == {'turn_id','question','source_filter'} for t in q['turns']) for q in questions))
    check('catalog_unchanged', sha((project / 'rag_qa/data/finance/knowledge_catalog.json').read_bytes()) == snapshot['catalog_sha256'])
    for rel, d in documents.items():
        p = inside(project / 'rag_qa/data/finance', rel)
        check('source_sha256:' + rel, sha(p.read_bytes()) == d['raw_sha256'])
    evidence_count = 0
    for t in turns:
        tid = t['turn_id']
        check('action_contract:' + tid, t['expected_action'] in {'answer','refuse','handoff','abstain','clarify','greet'} and bool(t['acceptable_decisions']))
        check('filter_enum:' + tid, t['source_filter'] in (None, 'product', 'rate_table', 'regulation', 'business_rule', 'faq'))
        ids = {e['evidence_id'] for e in t['evidence']}
        check('evidence_ids_unique:' + tid, len(ids) == len(t['evidence']))
        check('point_evidence_binding:' + tid, bool(t['required_points']) and all(set(p['evidence_ids']) <= ids for p in t['required_points']))
        if t['expected_action'] == 'answer':
            check('answer_has_grounding:' + tid, bool(t['evidence']) and all(p['evidence_ids'] for p in t['required_points']))
        for e in t['evidence']:
            evidence_count += 1
            d = documents[e['document_path']]
            lines = inside(project / 'rag_qa/data/finance', e['document_path']).read_text(encoding='utf-8').splitlines()
            a, b = e['line_start'], e['line_end']
            actual = '\n'.join(lines[a-1:b])
            check('exact_quote:' + tid + ':' + e['evidence_id'], 1 <= a <= b <= len(lines) and actual == e['quote'] and sha(actual.encode()) == e['quote_sha256'])
            # Catch anchors containing only blank lines/headings: existence is insufficient.
            meaningful = [x for x in actual.splitlines() if x.strip() and not x.lstrip().startswith('#')]
            check('substantive_quote:' + tid + ':' + e['evidence_id'], bool(meaningful))
            check('document_binding:' + tid + ':' + e['evidence_id'], e['doc_id'] == d['doc_id'] and e['version'] == d['version'])
            if e['role'] == 'support':
                check('support_eligible:' + tid + ':' + e['evidence_id'], d['eligible_at_as_of'] and e['eligible_at_as_of'])

    for item in audit['prior_files']:
        check('old_corpus_unchanged:' + item['file'], sha(inside(project, item['file']).read_bytes()) == item['sha256'])
    prior = old_texts(project, audit['prior_files'])
    check('old_corpus_reconstructed', len(prior) == audit['unique_prior_texts'] and
          sha(json.dumps(sorted(prior),ensure_ascii=False,separators=(',',':')).encode()) == audit['prior_corpus_sha256'])
    duplicate_ids = [t['turn_id'] for t in turns if norm(t['question']) in prior]
    check('no_exact_old_question_duplicates', not duplicate_ids, duplicate_ids)
    check('all_semantic_adjudications_pending', len(audit['turns']) == 110 and all(r['manual_semantic_adjudication'] == 'pending' for r in audit['turns']))
    freeze = json.loads((pack / 'runtime_freeze.json').read_text(encoding='utf-8'))
    for rel, expected in freeze['files'].items():
        check('runtime_unchanged:' + rel, sha(inside(project, rel).read_bytes()) == expected)
    summary = dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
        scope='Offline artifact validation only; no model/API/database calls; no human review',
        dataset_version=manifest['dataset_version'], scenarios=len(cases), turns=len(turns), evidence_entries=evidence_count,
        prior_unique_texts=len(prior), exact_old_question_duplicates=len(duplicate_ids),
        checks_passed=sum(c['passed'] for c in checks), checks_total=len(checks),
        human_review_completed=0, model_questions_executed=0,
        failed_checks=[c for c in checks if not c['passed']], checks=checks)
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--pack', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    try:
        report = validate(args.project.resolve(), args.pack.resolve())
    except Exception as exc:
        report = dict(status='failed', failure_type=type(exc).__name__, scope='Offline artifact validation')
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'checks'}},ensure_ascii=False,indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
