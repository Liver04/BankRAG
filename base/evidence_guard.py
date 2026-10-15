"""Bounded evidence checks; NOT complete semantic entailment."""
import re
from decimal import Decimal
NUM=re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(万|亿)?\s*(元|个月|月|年|天|%|％)?')
CN_DIGITS=dict(zip('零〇一二两三四五六七八九壹贰叁肆伍陆柒捌玖', [0,0,1,2,2,3,4,5,6,7,8,9,1,2,3,4,5,6,7,8,9]))
CN_UNITS={'十':10,'拾':10,'百':100,'佰':100,'千':1000,'仟':1000,'万':10000,'亿':100000000}
CN_NUMBER=r'[零〇一二两三四五六七八九十百千壹贰叁肆伍陆柒捌玖拾佰仟][零〇一二两三四五六七八九十百千万亿点壹贰叁肆伍陆柒捌玖拾佰仟]*'
def chinese_number(s):
    if '点' in s:
        integer,fraction=s.split('点',1)
        if not fraction or any(c not in CN_DIGITS for c in fraction):raise ValueError('invalid_chinese_decimal')
        return chinese_number(integer)+Decimal('0.'+''.join(str(CN_DIGITS[c]) for c in fraction))
    if not s:return Decimal(0)
    if all(c in CN_DIGITS for c in s):return Decimal(''.join(str(CN_DIGITS[c]) for c in s))
    total=section=number=0
    for c in s:
        if c in CN_DIGITS:number=CN_DIGITS[c]
        elif c in CN_UNITS:
            unit=CN_UNITS[c]
            if unit<10000:section+=(number or 1)*unit;number=0
            else:
                section+=number;number=0
                if unit==100000000:total=(total+section)*unit;section=0
                else:total+=section*unit;section=0
        else:raise ValueError('invalid_chinese_number')
    return Decimal(total+section+number)
def numeric_atoms(text):
    atoms=set()
    for m in NUM.finditer(re.sub(r'\[\d+\]','',text)):
        value=Decimal(m[1])*({'万':10000,'亿':100000000}.get(m[2],1))
        unit=m[3] or ('元' if m[2] else '')
        if unit:atoms.add((str(value.normalize()),unit.replace('％','%').replace('个月','月')))
    for m in re.finditer('('+CN_NUMBER+r')\s*(元|个月|月|年|天|%|％)',text):
        try:atoms.add((str(chinese_number(m[1]).normalize()),m[2].replace('％','%').replace('个月','月')))
        except ValueError:pass
    for m in re.finditer('百分之('+CN_NUMBER+')',text):
        try:atoms.add((str(chinese_number(m[1]).normalize()),'%'))
        except ValueError:pass
    for m in re.finditer(r'(\d+(?:\.\d+)?|'+CN_NUMBER+r')\s*折',text):
        value=Decimal(m[1]) if m[1][0].isdigit() else chinese_number(m[1])
        atoms.add((str((value*10).normalize()),'%'))
    return atoms
def check_evidence(query,text,docs,refs):
    evidence='\n'.join(docs[i-1].page_content for i in refs);issues=[]
    # Catch explicit claims that a quoted phrase is absent when it is present in
    # the cited source, and named authorities that the cited documents do not contain.
    for phrase in re.findall(r'(?:未|没有)(?:在[^，。；;]{0,16})?出现[“「\"]([^”」\"]{2,30})[”」\"](?:字样|表述|内容)?',text or ''):
        if phrase in evidence:issues.append('source_text_misread')
    authorities=(
        (r'中国人民银行|人民银行|央行',r'中国人民银行|人民银行|央行'),
        (r'中国银行|中行',r'中国银行|中行|bankofchina\.com'),
        (r'招商银行|招行',r'招商银行|招行|cmbchina\.com'),
        (r'工商银行|工行',r'工商银行|工行|icbc\.com\.cn'),
        (r'建设银行|建行',r'建设银行|建行|ccb\.com'),
        (r'农业银行|农行',r'农业银行|农行|abchina\.com'),
        (r'交通银行|交行',r'交通银行|交行|bankcomm\.com'),
    )
    for sentence in re.split(r'[。！？；;\n]+',text or ''):
        mentioned=[(name,source) for name,source in authorities if re.search(name,sentence)]
        if not mentioned:continue
        sentence_refs=[int(x) for x in re.findall(r'\[(\d+)\]',sentence)] or list(refs)
        cited='\n'.join(docs[i-1].page_content+' '+str(docs[i-1].metadata) for i in sentence_refs if 1<=i<=len(docs))
        if any(not re.search(source,cited,re.I) for _,source in mentioned):issues.append('unsupported_named_authority')
    for sentence in re.split(r'[。！？；;\n]+',text or ''):
        if not re.search(r'(?:教育储蓄|通知存款|大额存单|定活两便).{0,100}(?:特殊性|特殊规则|虽|虽然|但是|但).{0,100}(?:不能直接套用|不能套用|不适用|不能适用|不得套用)',sentence):continue
        subject=re.search(r'教育储蓄|通知存款|大额存单|定活两便',sentence).group(0)
        sentence_refs=[int(x) for x in re.findall(r'\[(\d+)\]',sentence)] or list(refs)
        cited='\n'.join(docs[i-1].page_content for i in sentence_refs if 1<=i<=len(docs))
        if not (subject in cited and re.search(r'(?:不能直接套用|不能套用|不适用|不能适用|不得套用)',cited)):
            issues.append('unsupported_legal_scope_inference')
    from base.claim_support import numeric_support
    numeric=numeric_support(query,text,docs,refs)
    if not numeric['passed']:issues.append('unsupported_numeric_atom')
    assertions=[r'(?:电子身份证|电子证件).{0,35}(?:不属于|不能|不支持|不接受|可以|支持|认可)',r'(?:全国|所有城市|各网点).{0,35}(?:统一|支持|接受|不支持|尚未|不能)',r'(?:必须|须|需要).{0,20}(?:身份证件|身份证).{0,6}原件']
    for pattern in assertions:
        for claim in re.findall(pattern,text):
            if claim not in evidence:issues.append('unsupported_identity_or_deployment_claim')
    conditions=[]
    if '通知存款' in query and re.search(r'部分|取出|支取|剩|留存',query):
        if re.search(r'最低支取|最低(?:支取|取款)金额|每次支取.*?最低',evidence):conditions.append(('withdrawal_minimum',r'最低支取|最小支取|最低取款|支取下限|取款下限|(?:支取|取出)(?:(?!剩|留存|后).){0,10}(?:不足|低于)(?:(?!剩|留存|后).){0,8}(?:最低|门槛)'))
        if re.search(r'剩余|留存|留在账户|保留',evidence):conditions.append(('remaining_minimum',r'剩余|留存|留在账户|保留'))
        for name,pattern in conditions:
            if not re.search(pattern,text):issues.append('missing_condition:'+name)
    from base.condition_plan import condition_plan,missing_conditions
    plan=condition_plan(query,docs,refs)
    for kind in missing_conditions(plan,text):issues.append('missing_condition:'+kind)
    return {'version':'bounded_evidence_v4','passed':not issues,'issues':sorted(set(issues)),'required_conditions':list(dict.fromkeys([name for name,_ in conditions]+plan['requirements'])),
        'numeric_support':numeric,'condition_plan':plan,'limits':'Cited numeric scopes/explicit scenarios/exact subtraction/selected conditions only; no complete semantic proof'}
