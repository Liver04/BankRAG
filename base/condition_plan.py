"""Source-bound condition plans; deterministic notice-deposit example analysis."""
import re
from decimal import Decimal
from base.safety import Answer,finalize,citation,render_citations,eligible
from base.claim_support import quantities,money_scenario

def condition_plan(query,docs,refs=None):
    refs=list(range(1,len(docs)+1)) if refs is None else refs;requirements=[];rules={}
    if '通知存款' in query and re.search(r'部分|取出|支取|取.{0,12}万元|剩|留存',query):
        for i in refs:
            d=docs[i-1]
            if '通知存款' not in d.metadata.get('title','') or not eligible(d.metadata):continue
            for line in d.page_content.splitlines():
                if re.search(r'美元|外币|港币|英镑|欧元|USD|HKD|EUR|GBP',line,re.I):continue
                kinds=[k for k,pattern in [('withdrawal_minimum',r'最低支取|最低取款'),('remaining_minimum',r'最低留存|最低剩余')] if re.search(pattern,line)]
                amounts=[q for q in quantities(line) if q['atom'][1]=='元']
                # A shared minimum must explicitly say 均; separate clauses are
                # handled individually. Conflicting versions disable calculation.
                if len(amounts)==1 and (len(kinds)==1 or '均' in line):
                    for kind in kinds:rules.setdefault(kind,[]).append({'amount':amounts[0]['atom'][0],'number':i,'quote':line.strip()})
        for kind in ('withdrawal_minimum','remaining_minimum'):
            entries=rules.get(kind,[])
            if entries:requirements.append(kind)
    if re.search(r'代理.*开户|开户.*代理',query):
        evidence='\n'.join(docs[i-1].page_content for i in refs)
        for kind,pattern in [('agent_identity',r'代理人的?有效身份证件|代理人、被代理人的有效身份证件'),('principal_identity',r'被代理人的?有效身份证件|代理人、被代理人的有效身份证件'),('authorization',r'合法委托书')]:
            if re.search(pattern,evidence):requirements.append(kind)
    return {'requirements':requirements,'rules':rules,'profile':'source_bound_conditions_v2'}

def missing_conditions(plan,text):
    patterns={'withdrawal_minimum':r'最低支取|最小支取|最低取款|支取下限|取款下限',
              'remaining_minimum':r'最低留存|最低剩余|留存下限|剩余.{0,12}(?:低于|不低于|不足)|留存.{0,12}(?:低于|不低于|不足)',
              'agent_identity':r'代理人|代办人', 'principal_identity':r'被代理人|开户人|账户本人|委托人', 'authorization':r'委托书|授权书'}
    return [kind for kind in plan['requirements'] if not re.search(patterns[kind],text)]

def notice_answer(query,docs,intent):
    if '通知存款' not in query or re.search(r'美元|外币|港币|南非|英镑|欧元|澳元|加元|USD|HKD|EUR|GBP',query,re.I):return None
    if not re.search(r'满足|符合|要求|能否|是否|可以|能不能|条件|限制',query):return None
    scenario=money_scenario(query);plan=condition_plan(query,docs)
    if not all(k in plan['rules'] for k in ('withdrawal_minimum','remaining_minimum')):return None
    if scenario['status'] in ('inconsistent','ambiguous','invalid'):
        return Answer(finalize('您给出的金额条件不一致或存在多个数值，请明确原金额、支取金额和剩余金额。'),'rag',intent,'clarify',diagnostics={'condition_plan':plan})
    if not all(k in scenario['values'] for k in ('withdrawal','remaining')):return None
    picked={}
    for kind in ('withdrawal_minimum','remaining_minimum'):
        options=plan['rules'][kind]
        if len({x['amount'] for x in options})!=1:return None
        picked[kind]=options[0]
    fmt=lambda x:format(Decimal(x),'f')+'元'
    lines=['以下仅按题设金额核对已引用资料中的人民币通知存款条件：'];passed=[];refs=[]
    for kind,role,label in [('withdrawal_minimum','withdrawal','最低支取金额'),('remaining_minimum','remaining','最低留存金额')]:
        rule=picked[kind];value=scenario['values'][role];ok=Decimal(value)>=Decimal(rule['amount']);passed.append(ok);refs.append(rule['number'])
        actual='本次支取金额' if role=='withdrawal' else '支取后剩余金额'
        lines.append(f"- {label}：资料规定{fmt(rule['amount'])}。[{rule['number']}] {actual}为{fmt(value)}，{'不低于' if ok else '低于'}该门槛，{'满足' if ok else '不满足'}这一项。[{rule['number']}]")
    lines.append('结论：'+('上述两项金额条件均满足；预约通知、账户及其他办理条件仍须另行核对，不能据此保证办理成功。' if all(passed) else '上述金额条件未全部满足，不能直接认定符合资料中的部分支取要求；实际办理需按银行官方流程核实。'))
    return {'raw':'\n'.join(lines),'plan':plan,'scenario':scenario,'numbers':list(dict.fromkeys(refs)),'mode':'source_bound_deterministic_notice_conditions'}
