"""Read frozen traces; report engineering evidence without editing gold/scores."""
import argparse, hashlib, json
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))

NOTES={
 'H-B05':('citation_mismatch_blocked','数值2000元在检索块1，但模型引用[3]，该块不含此金额。守卫拦截有依据；生成引用错误。不证明原句其他事实正确。','保留逐句绑定；只允许同上下文最多一次重新生成并完整复验。'),
 'H-C05':('citation_mismatch_blocked','数值50万元在检索块1而不在模型实际引用块。守卫拦截有依据；属于生成引用失败。','不把全局检索数字当作实际引用证据。'),
 'H-B09':('invalid_citation_blocked','引用[5]超出实际上下文范围，拦截正确；业务回答未交付。','逐句编号提示改进；不自动把[5]改为[1]，不推定原始正文正确。'),
 'H-B10':('invalid_citation_blocked','引用[5]超出实际上下文范围，拦截正确；正文未保留。','原文列表项5与上下文编号可能混淆，但无原始正文不能确证。'),
 'H-U05':('invalid_citation_blocked','HTTP引用[8]超出3个上下文，拦截正确；同题WS成功只说明入口生成波动。','不能把条文第八条直接当作引用[8]；混淆原因仅假设。'),
 'H-F02':('intent_false_refusal','请求核实旧利率表是否能代表当前报价，没有请求代选或收益预测；却进入投资建议拒答。','记录分类语境后续工作；本次不扩大至整套BERT或规则重训。'),
 'H-F07':('provisional_label_dispute','正文否认整理日期等于新利率生效日期，基本响应了必答点；answered标签不等于事实错误。WS的“未提供任何生效日期规则”措辞需复核范围。','保留abstain原标签；交真人审查行为契约与额外句子，不能按结果重标。'),
 'H-N06':('nonnumeric_support_review','HTTP把“到期一次支取本息”扩展为“提前支取均一次支取”，并从产品特殊性推出不能直接套用第24条，引用中没有该推导。','第4项建议只实现受支持的资料不足回答及法规适用性推断防护，先经用户确定范围。'),
 'H-P08':('bounded_numeric_false_block','题设“放了四个月”未被已存时长规则覆盖；WS另有60%与六折等价表达缺口。未保存拒绝原文，不能断言原句完全正确。','新增有界题设时长及折扣系数；禁止升格为银行期限或年利率。'),
 'H-P09':('negated_duration_hypothesis','两年是问题提出的待否定期限。原始正文未保留，只能确认两年未被所引块正面支持，不能确认当时是肯定还是否定。','仅在当前问题提及、明确否定且同产品所引资料有上限时允许；肯定两年继续拦截。'),
 'H-R12':('protected_intent_overwritten','原模型风险决策后，指代无历史导致普通澄清覆盖拒答；trace记录unresolved/no_history。','原始收益预测决策保持绑定，历史或指代不能降低。'),
 'H-S04':('protected_intent_overwritten','原账户敏感决策被指代澄清覆盖；合成验证码仍不授权账户验证操作。','原账户敏感决策保持人工转接，测试声明不能降级。'),
 'H-U04':('retrieval_or_faq_coverage','当前问题走业务路径但无合格最终上下文，原检索候选重排最高约0.1165<0.15。gold依据在FAQ，当前Milvus排除FAQ，FAQ未命中。','仅能确认本次候选被阈值过滤；不能说降低阈值就能找到正确资料。另做FAQ覆盖诊断。'),
}

def audit(root,out):
    src=root/'evaluation/results/quality_v3_full';m=read(src/'manifest.json')
    if sha(src/'traces.json')!=m['trace_sha256']:raise ValueError('frozen_trace_changed')
    rows=read(src/'traces.json')['rows'];lookup={(r['turn_id'],r['transport']):r for r in rows}
    dev=root/'evaluation/results/quality_v3_development'
    failures=read(dev/'quality_v3_remaining_cases.json')['rows']
    regressions=read(dev/'quality_v3_decision_regression_candidates.json')['rows']
    regkeys={(r['turn_id'],r['transport']) for r in regressions}
    baseline=read(root/'evaluation/results/context_v2_1_regression/traces.json')['rows']
    old={(r['turn_id'],r['transport']):r for r in baseline}
    result=[]
    for f in failures:
        key=(f['turn_id'],f['transport']);r=lookup[key];res=r['result'];d=res.get('diagnostics',{})
        group,note,next_step=NOTES[r['case_id']]
        if r['case_id']=='H-N06' and r['transport']=='websocket':
            group='provisional_label_dispute';note='WS依据所引材料明确缺少部分支取完整规则，正文实质为资料不足，未作HTTP那样的法规适用推导；answered与abstain不一致需真人审契约。';next_step='不能因同题HTTP有错误就把WS答案一并判错。'
        record={'turn_id':r['turn_id'],'transport':r['transport'],'regression_candidate':key in regkeys,
          'classification':group,'finding':note,'next_step':next_step,'human_status':'pending',
          'original_expected_action':f['expected_action_provisional'],'actual_decision':res['decision'],
          'question':r['question'],'actual_visible_answer':r['actual_visible_text'],
          'error_code':res.get('error_code'),'citation_check':d.get('citation_check'),
          'numeric_check':d.get('evidence_check',{}).get('numeric_support') if d.get('evidence_check') else None,
          'reference_resolution':d.get('reference_resolution'),
          'source_bindings':[{'number':i,'doc_id':x.get('doc_id'),'block_id':x.get('parent_id'),'version':x.get('version'),'title':x.get('title'),'text_sha256':hashlib.sha256(x['text'].encode()).hexdigest()} for i,x in enumerate(res.get('contexts',[]),1)],
          'retrieval_summary':[{'candidate_count':len(s.get('candidates',[])),'selected_count':s.get('selected_count'),'max_rerank_score':max((x['raw_score'] for x in s.get('rerank',[])),default=None)} for s in d.get('searches',[])],
          'evidence_locator':f'evaluation/results/quality_v3_full/traces.json rows[{rows.index(r)}]',
          'trace_rows_line':next(i for i,x in enumerate((src/'trace_rows.jsonl').read_text(encoding='utf-8').splitlines(),1) if (json.loads(x)['turn_id'],json.loads(x)['transport'])==key),
          'rejected_raw_text_available':False if res.get('error_code') else None}
        if key in regkeys:record['prior_full_version_visible_answer']=old[key]['actual_visible_text'];record['prior_full_version_decision']=old[key]['result']['decision']
        result.append(record)
    if len(result)!=23 or sum(x['regression_candidate'] for x in result)!=5:raise ValueError('audit_count_changed')
    report={'scope':'23 provisional label mismatches including five regression candidates; engineering audit, no independent human grading',
      'frozen_trace_sha256':sha(src/'traces.json'),'gold_sha256_unchanged':sha(root/'evaluation/holdout_v1_1/answer_key.jsonl'),
      'independent_human_reviews':0,'gold_modified':False,'rows':result,
      'item4_proposed_scope':{'implement_now':False,'evidence':['H-N06 HTTP unsupported paraphrase and legal applicability inference','H-N06 WS mostly evidence-bound uncertainty; not same defect','H-F07 mostly label/wording review; not automatically wrong'],
        'proposal':'源资料明确声明缺完整规则时，采用绑定该限制段的资料不足回答；跨法规、跨银行结论必须有明确对应依据。禁止根据语法单复数或优惠特性推导法律排除。具体实现待确认，非通用语义证明。'}}
    out.mkdir(parents=True,exist_ok=False)
    (out/'case_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    md=['# v2.2 逐题工程归因（人工评分待完成）\n','覆盖23条标签不匹配，其中5条退步候选。原始问题、gold和trace不变。未保存被拦原文的题不能确证原句语义。\n',
      '|题目/入口|退步候选|归因|证据与限制|\n|---|---|---|---|\n']
    for r in result:md.append(f"|{r['turn_id']} / {r['transport']}|{'是' if r['regression_candidate'] else '否'}|{r['classification']}|trace_rows.jsonl:{r['trace_rows_line']}；{r['finding']}|\n")
    md+=['\n## 第4项建议范围（尚未实现）\n',report['item4_proposed_scope']['proposal']+'\n',
      '\n不能把F07、N06的所有answered标签都判错；应按每个入口的实际事实、引用和语义独立复核。本文没有金融法规现行效力认证，也没有人工业务准确率。\n']
    (out/'case_audit.md').write_text(''.join(md),encoding='utf-8')
    print(json.dumps({'audited':len(result),'regression_candidates':5,'gold_modified':False,'human_reviews':0},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args();audit(a.root,a.out)
