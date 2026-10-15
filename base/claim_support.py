"""Bounded numeric provenance: cited rules, explicit scenarios, exact subtraction.

Customer-supplied rates/fees are never promoted to bank facts. This is not a
general semantic entailment system or a financial calculation engine.
"""
import re
from decimal import Decimal

RULE_SCOPES={
    'discount_factor':r'利率的|利率乘以|基准的|折算系数(?:为|是)?|折扣系数(?:为|是)?|打(?=\s*$)',
    'minimum_opening':r'起存|最低存入|开户最低金额',
    'minimum_withdrawal':r'最低支取|最小支取|最低取款|支取下限',
    'minimum_remaining':r'最低留存|最低剩余|留存下限|剩余(?:金额)?.{0,4}(?:不得低于|不低于|至少)',
    'fee':r'手续费|服务费|收费金额|收取费用',
    'rate':r'年利率|挂牌利率|年化利率|利率为|利率是',
}
def quantities(text):
    from base.evidence_guard import NUM,CN_NUMBER,numeric_atoms
    found=[]
    discount=re.compile(r'(\d+(?:\.\d+)?|'+CN_NUMBER+r')\s*折')
    patterns=[discount,NUM,re.compile('('+CN_NUMBER+r')\s*(元|个月|月|年|天|%|％)'),re.compile('百分之('+CN_NUMBER+')')]
    for pattern in patterns:
        for m in pattern.finditer(text):
            atoms=numeric_atoms(m[0])
            if len(atoms)==1:found.append({'start':m.start(),'end':m.end(),'atom':next(iter(atoms)),'raw':m[0]})
    result=[]
    for q in sorted(found,key=lambda x:(x['start'],-x['end'])):
        if any(q['start']>=x['start'] and q['end']<=x['end'] for x in result):continue
        result.append(q)
    return result

def money_scenario(query):
    values={};items=[q for q in quantities(query) if q['atom'][1]=='元']
    if any(q['start'] and query[q['start']-1] in '-−' for q in items):return {'status':'invalid','values':{}}
    for q in items:
        prefix=query[max(0,q['start']-14):q['start']];suffix=query[q['end']:q['end']+5]
        role=None
        if re.search(r'(?:剩(?:余|下)?|留存)(?:了|为|是|有|金额)?$',prefix):role='remaining'
        elif re.search(r'(?:支取|取(?:出|走|了)?)(?:了|金额为|金额是)?$',prefix):role='withdrawal'
        elif re.search(r'(?:存(?:入|了|有|着)?|本金|原有|余额|账户里有)(?:为|是|了|有)?$',prefix) or re.match(r'(?:支取|取)',suffix):role='total'
        if role:values.setdefault(role,set()).add(q['atom'][0])
    if any(len(v)>1 for v in values.values()):return {'status':'ambiguous','values':{}}
    data={k:Decimal(next(iter(v))) for k,v in values.items()}
    if any(v<0 for v in data.values()):return {'status':'invalid','values':{}}
    derived=False
    if 'total' in data and 'withdrawal' in data:
        remaining=data['total']-data['withdrawal']
        if remaining<0:return {'status':'inconsistent','values':{}}
        if 'remaining' in data and data['remaining']!=remaining:return {'status':'inconsistent','values':{}}
        if 'remaining' not in data:data['remaining']=remaining;derived=True
    return {'status':'parsed' if data else 'not_found','values':{k:str(v.normalize()) for k,v in data.items()},'remaining_derived':derived}

def quantity_scope(q,prefix):
    if q['raw'].endswith('折'):return 'discount_factor'
    matched=[(m.start(),key) for key,pattern in RULE_SCOPES.items() for m in re.finditer(pattern,prefix)]
    scope=max(matched)[1] if matched else None
    if scope is None and q['atom'][1]=='%' and re.search(r'折\s*(?:[（(]\s*)?(?:即|也就是|相当于|等于|=|＝)\s*$',prefix):return 'discount_factor'
    return scope


def _source_supports(atom,scope,evidence,discount_basis=None):
    from base.evidence_guard import numeric_atoms
    if atom not in numeric_atoms(evidence):return False
    # The same cited sentence must contain both the quantity and its attribute.
    for s in re.split(r'[。；;\n，,]',evidence):
        if scope=='discount_factor' and discount_basis=='interest' and not re.search(r'利率|计息',s):continue
        if scope=='discount_factor' and discount_basis=='fee' and not re.search(r'手续费|收费|费用',s):continue
        for q in quantities(s):
            if q['atom']!=atom:continue
            prefix=s[:q['start']]
            source_scope=quantity_scope(q,prefix)
            # Discount percentage is a multiplier, never an annual interest rate.
            if scope is None and source_scope!='discount_factor':return True
            if scope is not None and source_scope==scope:return True
            if scope is None:continue
            if '均' in prefix and re.search(RULE_SCOPES[scope],prefix) and len(numeric_atoms(s))==1:return True
    return False


def _linked_numeric_support(atom,scope,evidence,query):
    """Accept narrowly linked facts within one cited, product-compatible source."""
    from base.evidence_guard import numeric_atoms
    if scope=='rate' and atom[1] in ('年','月') and atom in numeric_atoms(query):
        term_documented=any(
            re.search(r'存期(?:为|分为|包括|是)|期限(?:为|分为|包括|是)',line)
            and any(q['atom']==atom for q in quantities(line))
            for line in evidence.splitlines())
        rate_rule=bool(re.search(r'(?:存期内|定期存款).{0,160}(?:利率调整|遇利率调整).{0,20}(?:不分段计息|按(?:开户日|存入日).{0,12}利率)',evidence))
        if term_documented and rate_rule:return True
    if scope=='minimum_remaining':
        links_remaining=bool(re.search(r'(?:剩余部分|剩余金额|留存金额).{0,24}(?:需|应|必须).{0,12}(?:满足|达到|不低于).{0,12}(?:大额存单)?起点金额',evidence))
        threshold_documented=any(
            re.search(r'(?:购买|认购|产品)?起点金额|最低起存金额',line)
            and re.search(r'(?:不低于|不少于|至少|最低为|為)',line)
            and atom in numeric_atoms(line)
            for line in evidence.splitlines())
        if links_remaining and threshold_documented:return True
    return False


def _negated_term_mention(prefix,suffix):
    negative=(r'(?:不会|不能|不应|不再)(?:(?!但是|但|而是|可以|会|却).){0,24}(?:延长|延伸|升档|升级|升|变|转|提高)(?:到|至|为)$'
        r'|(?:不因|不随)(?:(?!但是|但|而是|可以|却).){0,24}(?:延长|延伸|升档|升级|上调|提高|变|转)(?:到|至|为)$'
        r'|(?:并非|而非|不是|不按|不适用|不会按|不会以|不会改用)(?:按)?$')
    return bool(re.search(negative,prefix) and re.match(r'(?:期|档|利率|计息|\s|\[|$)',suffix))


def _negated_term_support(query,clause,q,docs,refs):
    """Only reject a query-suggested term above an explicit cited interest cap.

    This does not authorize arbitrary negation of invented terms or numbers.
    """
    from base.evidence_guard import CN_NUMBER,numeric_atoms
    atom=q['atom'];prefix=clause[:q['start']];suffix=clause[q['end']:]
    if atom[1] not in ('月','年') or atom not in numeric_atoms(query):return []
    if not _negated_term_mention(prefix,suffix):return []
    months=Decimal(atom[0])*(12 if atom[1]=='年' else 1);supported=[]
    topics=('定活两便','整存整取','零存整取','通知存款','存本取息','教育储蓄')
    asked=[p for p in topics if p in query]
    if len(asked)!=1:return []
    for i in refs:
        doc=docs[i-1]
        if asked[0] not in doc.metadata.get('title',''):continue
        for line in doc.page_content.splitlines():
            if not re.search(r'无论存期多长|最高|最多|最长',line):continue
            if re.search(r'并非|不是|不按|不再|不能',line):continue
            # Require a single explicit capped interest tier in the same line.
            caps=[]
            for m in re.finditer(r'(\d+(?:\.\d+)?|'+CN_NUMBER+r')\s*(个月|月|年)期?利率',line):
                atoms=numeric_atoms(m[0])
                if len(atoms)==1:
                    value,unit=next(iter(atoms));caps.append(Decimal(value)*(12 if unit=='年' else 1))
            if len(set(caps))==1 and months>caps[0]:supported.append(i)
    return supported

def _scenario_role(prefix):
    if re.search(r'最低|不得低于|不低于|至少|上限|下限',prefix):return None
    if re.search(r'(?:支取后)?(?:剩余|剩下|留存)(?:金额)?(?:为|是|有)?$',prefix):return 'remaining'
    if re.search(r'(?:本次支取|本次取出|取出|支取)(?:金额)?(?:为|是|有)?$',prefix):return 'withdrawal'
    if re.search(r'(?:原金额|原有|存入|本金)(?:金额)?(?:为|是|有)?$',prefix):return 'total'
    return None


def _source_compatible(query,clause,doc):
    """Reject explicit product/bank conflicts; unknown entities are not proven."""
    topics=('定活两便','整存整取','零存整取','通知存款','存本取息','教育储蓄','大额存单','整存零取')
    asked={p for p in topics if p in query}
    if len(asked)!=1:asked={p for p in topics if p in clause}
    titled={p for p in topics if p in doc.metadata.get('title','')}
    if len(asked)==1 and titled and not asked.intersection(titled):return False
    banks={'boc':r'中国银行|中行','cmb':r'招商银行|招行','icbc':r'工商银行|工行',
           'ccb':r'建设银行|建行','abc':r'农业银行|农行','bocom':r'交通银行|交行'}
    requested={k for k,p in banks.items() if re.search(p,query)}
    if len(requested)!=1:requested={k for k,p in banks.items() if re.search(p,clause)}
    known={k for k,p in banks.items() if re.search(p,doc.page_content+' '+doc.metadata.get('title',''))}
    url=doc.metadata.get('source_url','')
    if re.search(r'https://(?:[\w-]+\.)?bankofchina\.com/',url):known.add('boc')
    if len(requested)==1 and known and not requested.intersection(known):return False
    return True

def numeric_support(query,text,docs,refs):
    scenario=money_scenario(query);checks=[];unsupported=[]
    qnums=quantities(query)
    # Keep decimal points intact; only split sentence punctuation and line breaks.
    for sentence in re.split(r'[。！？；;\n]',text):
        explicit=[int(n) for n in re.findall(r'\[(\d+)\]',sentence)]
        local_refs=[i for i in explicit if i in refs] if explicit else refs
        previous_clause=''
        for clause in re.split(r'[，,]',sentence):
            clean=re.sub(r'\[\d+\]','',clause)
            for q in quantities(clean):
                atom=q['atom'];prefix=clean[:q['start']]
                negated_term=atom[1] in ('月','年') and _negated_term_mention(prefix,clean[q['end']:])
                # Use the closest attribute before the value, not a keyword in an
                # unrelated later clause.
                scope=quantity_scope(q,prefix)
                if scope is None and atom[1]=='%' and re.fullmatch(r'\s*(?:即|也就是|相当于|等于|换算为)\s*',prefix) and any(x['raw'].endswith('折') for x in quantities(previous_clause)):
                    scope='discount_factor'
                role=_scenario_role(prefix) if scope is None else None
                basis_text=query+' '+clean+' '+previous_clause
                discount_basis=('interest' if re.search(r'利率|计息',basis_text) else 'fee' if re.search(r'手续费|收费|费用',basis_text) else None)
                if scope is None and role is None:
                    inherited=[kind for kind in ('fee','rate') if re.search(RULE_SCOPES[kind],query)]
                    if len(inherited)==1:scope=inherited[0]
                origin=None
                controlled_scenario=scope is None and atom[1]=='元' and scenario['status']=='parsed' and role in scenario['values']
                if controlled_scenario:
                    if scenario['values'][role]==atom[0]:origin='derived_subtraction' if role=='remaining' and scenario.get('remaining_derived') else 'explicit_scenario'
                supporting_refs=[]
                if not controlled_scenario and not negated_term:
                    supporting_refs=[i for i in local_refs if _source_compatible(query,clean,docs[i-1]) and
                        (_source_supports(atom,scope,docs[i-1].page_content,discount_basis) or
                         _linked_numeric_support(atom,scope,docs[i-1].page_content,query))]
                    if supporting_refs:origin='cited_rule'
                if origin is None and scope is None and atom[1]=='元' and scenario['status']=='parsed':
                    if re.search(r'按题设|按您提供|假设',clause) and role is None:
                        if atom[0] in scenario['values'].values():origin='explicit_scenario'
                    elif role and scenario['values'].get(role)==atom[0]:origin='derived_subtraction' if role=='remaining' and scenario.get('remaining_derived') else 'explicit_scenario'
                # Allow only an explicitly repeated elapsed/missed-deposit duration,
                # never a bank term, required notice period, fee or quoted rate.
                if origin is None and scope is None and atom[1]=='月' and re.search(r'漏存|漏缴|中断缴存',prefix) and not re.search(r'必须|规定|要求|最少|最多|期限|允许|仅需',prefix):
                    if any(x['atom']==atom and re.search(r'漏存|漏缴|中断缴存',query[max(0,x['start']-10):x['start']]) for x in qnums):origin='explicit_missed_deposit_scenario'
                elapsed_marker=re.search(r'按题设|本例|实际|已存|存了|留了|放了|存满|持有|存放|经过|过了|(?:您|你)(?:的)?存期|存期(?:为|是)?$',prefix) or (not prefix.strip() and re.match(r'(?:的(?:存期|这笔)|属于|对应|落在)',clean[q['end']:]))
                if origin is None and not negated_term and scope is None and atom[1] in ('月','年','天') and elapsed_marker and not re.search(r'必须|规定|要求|最少|最多|最低|最高|只能|一律|固定|允许|约定|合同|产品期限|(?:本|该)?产品(?:的)?存期',prefix):
                    if any(x['atom']==atom and re.search(r'已存|存了|留了|放了|经过|过了|持有|存满',query[max(0,x['start']-12):x['start']]) for x in qnums):origin='explicit_elapsed_duration_scenario'
                if origin is None and scope is None:
                    supporting_refs=_negated_term_support(query,clean,q,docs,[i for i in local_refs if _source_compatible(query,clean,docs[i-1])])
                    if supporting_refs:origin='negated_query_term_above_cited_cap'
                # Alternative blocks are diagnostic/repair candidates only. They
                # never make an incorrectly cited answer pass validation.
                alternatives=[i for i in range(1,len(docs)+1) if i not in local_refs and _source_compatible(query,clean,docs[i-1]) and _source_supports(atom,scope,docs[i-1].page_content,discount_basis)] if origin is None else []
                cap_repair=[]
                if origin is None and scope is None and atom[1] in ('月','年'):
                    # A cap can justify re-generating a rejected claim; it does
                    # not justify accepting an unrecognized/positive statement.
                    prefix_hint='不会延长到';hint=prefix_hint+q['raw']+'期利率'
                    hint_q=dict(q,start=len(prefix_hint),end=len(prefix_hint)+len(q['raw']))
                    cap_repair=_negated_term_support(query,hint,hint_q,docs,[i for i in local_refs if _source_compatible(query,clean,docs[i-1])])
                detail={'atom':list(atom),'scope':scope,'local_citation_numbers':list(local_refs),
                    'elapsed_marker':bool(elapsed_marker),'negated_term_marker':bool(negated_term),
                    'repair_cap_context_numbers':cap_repair,
                    'supporting_citation_numbers':supporting_refs,'alternative_context_numbers':alternatives,
                    'bound_sources':[{'number':i,'doc_id':docs[i-1].metadata.get('doc_id'),'block_id':docs[i-1].metadata.get('parent_id'),'version':docs[i-1].metadata.get('version')} for i in local_refs]}
                if origin is None:unsupported.append(detail.copy())
                checks.append(dict(detail,origin=origin or 'unsupported'))
            previous_clause=clean
    return {'passed':not unsupported,'checks':checks,'unsupported':unsupported,'scenario':scenario,
            'limits':'Bounded scopes and exact total-minus-withdrawal only; no arbitrary arithmetic, interest prediction or complete entailment'}
