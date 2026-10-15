"""One-pass traceable RAG; citations are validated BEFORE any generated text is emitted."""
import re
import inspect
from time import perf_counter
from langchain_core.documents import Document
from base.config import config
from base.safety import Answer,finalize,citation,render_citations,eligible,validate_source,current_rate_query,safe_answer_text,redact
from rag_qa.core.prompts import RAGPrompts
from rag_qa.core.query_classifier import QueryClassifier
from rag_qa.core.strategy_selector import StrategySelector
from base.evidence_guard import check_evidence
from base.condition_plan import condition_plan,notice_answer

class RAGSystem:
    def __init__(self,vector_store,llm,llm_stream=None,classifier=None,strategy_selector=None):
        self.vector_store,self.llm=vector_store,llm
        self.llm_stream=llm_stream or (lambda p:iter([llm(p)]))
        self.query_classifier=classifier or QueryClassifier()
        self.strategy_selector=strategy_selector or StrategySelector()
        self.rag_prompt=RAGPrompts.rag_prompt()

    def gate(self,query):
        intent=self.query_classifier.predict_category(query)
        if intent=='业务咨询' and re.search(r'信用卡分期|基金定投|基金净值',query):
            return intent,Answer(self._no_answer(),'policy',intent,'insufficient_evidence')
        phone=config.CUSTOMER_SERVICE_PHONE
        fixed={
            '收益预测':('很抱歉，我不能为您提供投资建议或收益预测。请通过银行官方渠道了解产品资料。','refused'),
            '投诉':(f'非常抱歉给您带来不便，请拨打人工客服电话 {phone} 处理。','handoff'),
            '账户敏感':(f'为保障个人信息安全，本系统不查询或操作账户。请通过官方渠道核实身份，电话 {phone}。','handoff'),
            '闲聊':('您好，我是银行存款业务演示客服，可以解答存款与公开业务 FAQ。','greeting'),
            '未知':('意图无法可靠确认，请联系人工客服。','insufficient_evidence')}
        if intent in fixed:
            text,decision=fixed[intent]
            return intent,Answer(finalize(text),'policy',intent,decision)
        return intent,None

    def _refuse(self,category):
        # Compatibility for external callers; same fixed policy as gate.
        texts={'收益预测':'不能为您提供投资建议或收益预测。','投诉':'请联系人工客服处理投诉。','账户敏感':'请通过官方渠道核实身份后办理。'}
        return finalize(texts.get(category,'信息不足，请联系人工客服。'))
    def _chitchat(self):return finalize('您好，我是银行存款业务演示客服。')
    def _no_answer(self):return finalize(f'信息不足，无法回答，请联系人工客服，电话：{config.CUSTOMER_SERVICE_PHONE}。')

    def retrieve_and_merge(self,query,source_filter=None,strategy=None,trace=None):
        validate_source(source_filter)
        if current_rate_query(query):
            if source_filter not in (None,'rate_table'):return []
            source_filter='rate_table'
        strategy=strategy or self.strategy_selector.select_strategy(query)
        queries=[query]
        if strategy=='假设问题检索':
            queries=[self.llm(RAGPrompts.hyde_prompt().format(query=query)).strip()]
        elif strategy=='回溯问题检索':
            queries=[self.llm(RAGPrompts.backtracking_prompt().format(query=query)).strip()]
        elif strategy=='子查询检索':
            queries=[q.strip() for q in self.llm(RAGPrompts.subquery_prompt().format(query=query)).splitlines() if q.strip()][:3]
        # Always retain the literal user question: generated queries are retrieval
        # aids, never replacements or sources of factual claims.
        queries=list(dict.fromkeys([query]+queries))[:4]
        if trace is not None:trace.update(strategy=strategy,searches=[])
        docs={}
        for q in queries:
            search_trace={}
            search=self.vector_store.hybrid_search_with_rerank
            kwargs=dict(k=config.RETRIEVAL_K,source_filter=source_filter)
            if 'trace' in inspect.signature(search).parameters:kwargs['trace']=search_trace
            else:search_trace['status']='adapter_without_trace'
            candidates=search(q,**kwargs)
            if trace is not None:trace['searches'].append(search_trace)
            for d in candidates:
                if eligible(d.metadata):
                    docs[(d.metadata.get('doc_id'),d.metadata.get('parent_id'))]=d
        return list(docs.values())[:config.CANDIDATE_M*3]

    def _format_context(self,docs):
        return '\n\n'.join(f"[{i}]《{d.metadata.get('title','')}》 doc={d.metadata.get('doc_id','')} block={d.metadata.get('parent_id','')}\n{d.page_content}" for i,d in enumerate(docs,1))
    @staticmethod
    def _format_history(history):
        return '\n'.join(f"问：{h['question']}\n答：{h['answer']}" for h in (history or []))

    def _validated(self,text,docs,query=None,trace=None):
        refs=[int(x) for x in re.findall(r'\[(\d+)\]',text or '')]
        if trace is not None:trace['citation_check']={'numbers':refs,'context_count':len(docs)}
        if not refs or any(x<1 or x>len(docs) for x in refs):
            raise ValueError('missing_or_invalid_citation')
        # Official titles occurring literally in the retrieved content are valid
        # aliases; the server still renders the bound catalog title and IDs.
        cited_docs=[docs[i-1] for i in set(refs)]
        titles={d.metadata.get('title','') for d in cited_docs}
        titles.update(t for d in cited_docs for t in re.findall(r'《([^》]+)》',d.page_content))
        titles.update(t.strip() for d in cited_docs for t in re.findall(r'(?m)^#\s+([^\n]+)',d.page_content))
        rejected=[t for t in re.findall(r'《([^》]+)》',text) if t not in titles]
        if rejected:
            if trace is not None:trace['citation_check']['rejected_titles']=[redact(t[:200]) for t in rejected[:20]]
            raise ValueError('fabricated_title')
        # Conservative output guard is an extra rule, not semantic proof of financial compliance.
        if not safe_answer_text(text):
            raise ValueError('unsafe_output')
        refs=list(dict.fromkeys(refs))
        if query is not None:
            check=check_evidence(query,text,docs,refs)
            if trace is not None:trace['evidence_check']=check
            if not check['passed']:raise ValueError('evidence_guard_failed')
        return [citation(docs[i-1],i) for i in refs]

    def _validate_references(self,answer,context_docs):
        self._validated(answer,context_docs)
        return answer

    @staticmethod
    def _is_insufficient_response(text):
        """Recognize conservative answers so content and decision cannot diverge."""
        patterns=(r'资料(?:中|里)?(?:未提供|没有提供|未说明|没有说明|不足以|无法确认)',
                 r'(?:信息|证据)(?:不足|不充分)',r'无法(?:从现有资料|根据现有资料|确认|判断|核实)',
                 r'不能(?:从现有资料|根据现有资料|确认|判断|核实)',r'无法回答')
        return any(re.search(p,text or '') for p in patterns)

    def _repair_citation_once(self,prompt,docs,query,trace,timings,raw):
        """Retry only missing/out-of-range citations; never renumber model output."""
        valid_numbers=', '.join(f'[{i}]' for i in range(1,len(docs)+1))
        repair_prompt=(prompt+'\n【引用格式校正】上一版引用缺失或编号越界。请基于完全相同的上下文重新作答，'
            f'每个事实句只可使用这些真实上下文编号：{valid_numbers}。'
            '不得创造、换算或猜测编号；事实不够时只明确说明资料不足，不补充未经支持的事实。')
        trace['citation_repair']={'attempts':1,'context_count':len(docs),'allowed_numbers':list(range(1,len(docs)+1))}
        phase=perf_counter()
        repaired=self.llm(repair_prompt)
        timings['generation_seconds']=round(timings.get('generation_seconds',0.0)+perf_counter()-phase,6)
        phase=perf_counter()
        try:
            citations=self._validated(repaired,docs,query,trace)
        except ValueError as exc:
            timings['validation_seconds']=round(timings.get('validation_seconds',0.0)+perf_counter()-phase,6)
            trace['citation_repair']['passed']=False
            trace['citation_repair']['error']=str(exc)
            return None,None,repaired
        timings['validation_seconds']=round(timings.get('validation_seconds',0.0)+perf_counter()-phase,6)
        trace['citation_repair']['passed']=True
        return repaired,citations,repaired

    def generate_result(self,query,source_filter=None,history=None,intent=None,use_stream=False):
        validate_source(source_filter)
        if intent is None:
            intent,blocked=self.gate(query)
            if blocked:return blocked
        trace={}
        timings={}
        started=perf_counter()
        def finish(result):
            timings['total_seconds']=round(perf_counter()-started,6)
            result.diagnostics.setdefault('rag_phase_timings',{}).update(timings)
            return result
        try:
            phase=perf_counter()
            docs=self.retrieve_and_merge(query,source_filter=source_filter,trace=trace)
            timings['retrieval_and_rerank_seconds']=round(perf_counter()-phase,6)
            contexts=[{'text':d.page_content,**d.metadata} for d in docs]
            if not docs:return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',diagnostics=trace))
            phase=perf_counter()
            structured=notice_answer(query,docs,intent)
            timings['structured_answer_seconds']=round(perf_counter()-phase,6)
            if isinstance(structured,Answer):
                structured.contexts=contexts;structured.diagnostics.update(trace)
                return finish(structured)
            phase=perf_counter()
            plan=condition_plan(query,docs)
            timings['condition_plan_seconds']=round(perf_counter()-phase,6)
            trace['condition_plan']=plan
            prompt=self.rag_prompt.format(context=self._format_context(docs),question=query,
                history=self._format_history(history),phone=config.CUSTOMER_SERVICE_PHONE)
            if plan['requirements']:
                prompt+='\n【服务端条件核对清单】\n'+str(plan['requirements'])+'\n逐项回答并在每项旁标注对应上下文编号；不能把一项条件当成另一项。'
            # Buffer model streaming until citations and output rules pass.
            if structured:
                raw=structured['raw'];trace.update(generation_mode=structured['mode'],scenario=structured['scenario'])
                timings['generation_seconds']=0.0
            else:
                phase=perf_counter()
                raw=''.join(self.llm_stream(prompt)) if use_stream else self.llm(prompt)
                timings['generation_seconds']=round(perf_counter()-phase,6)
                trace['generation_mode']='vendor_stream_buffered' if use_stream else 'vendor_completion'
            phase=perf_counter()
            abstention=self._is_insufficient_response(raw)
            if abstention:
                timings['validation_seconds']=round(perf_counter()-phase,6)
                trace['decision_normalization']={'from':'answered_candidate','to':'insufficient_evidence','reason':'answer_text_expresses_insufficient_evidence'}
                return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',contexts=contexts,diagnostics=trace))
            try: citations=self._validated(raw,docs,query,trace)
            except ValueError as e:
                timings['validation_seconds']=round(perf_counter()-phase,6)
                citation_numbers=trace.get('citation_check',{}).get('numbers',[])
                has_out_of_range=bool(citation_numbers) and any(n<1 or n>len(docs) for n in citation_numbers)
                if str(e)=='missing_or_invalid_citation' and has_out_of_range and not structured:
                    repaired,citations,_=self._repair_citation_once(prompt,docs,query,trace,timings,raw)
                    if repaired is None:
                        return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',contexts=contexts,
                            error_code='citation_repair_failed',diagnostics=trace))
                    raw=repaired
                    if self._is_insufficient_response(raw):
                        trace['decision_normalization']={'from':'answered_candidate','to':'insufficient_evidence','reason':'repaired_answer_expresses_insufficient_evidence'}
                        return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',contexts=contexts,diagnostics=trace))
                    return finish(Answer(finalize(raw+'\n\n【服务端来源】\n'+render_citations(citations)),
                        'rag',intent,'answered',citations,contexts,diagnostics=trace))
                check=trace.get('evidence_check',{})
                issues=check.get('issues',[])
                omitted=bool(issues) and all(x.startswith('missing_condition:') for x in issues)
                unsupported=check.get('numeric_support',{}).get('unsupported',[])
                numeric_repair=issues==['unsupported_numeric_atom'] and bool(unsupported) and all(x.get('alternative_context_numbers') or x.get('repair_cap_context_numbers') for x in unsupported)
                cap_repair=numeric_repair and any(x.get('repair_cap_context_numbers') for x in unsupported)
                # At most one re-generation from identical context. Wrong-source
                # numbers remain rejected unless the new full answer validates.
                # Do not rewrite IDs or repair missing/out-of-range references.
                if str(e)=='evidence_guard_failed' and (omitted or numeric_repair) and not structured:
                    kind='missing_conditions' if omitted else 'cited_interest_cap' if cap_repair else 'numeric_citation_mismatch'
                    trace['repair']={'attempts':1,'kind':kind,'initial_issues':issues,'initial_evidence_check':check}
                    instruction=('首次回答遗漏了以下受原文支持的条件：'+str(issues)) if omitted else ('首次回答中数值没有被实际引用块支持。以下仅为重新核对线索，不是事实证明：'+str(unsupported))
                    if cap_repair:instruction+='只解释所列repair_cap_context_numbers的原文明示计息档上限。不要复述客户猜测但原文未列的年数；不要把客户猜测当成实际档次，不能预测收益。'
                    phase=perf_counter()
                    raw=self.llm(prompt+'\n【重新作答】\n'+instruction+'。请逐句核对相同上下文、业务属性和适用范围后重新回答；每句紧接真实支持它的编号，无法支持则明确资料不足，不增加新事实。')
                    timings['generation_seconds']=round(timings.get('generation_seconds',0.0)+perf_counter()-phase,6)
                    phase=perf_counter()
                    try:citations=self._validated(raw,docs,query,trace);trace['repair']['passed']=True
                    except ValueError as repaired:
                        timings['validation_seconds']=round(timings.get('validation_seconds',0.0)+perf_counter()-phase,6)
                        trace['repair']['passed']=False
                        return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',contexts=contexts,error_code=str(repaired),diagnostics=trace))
                    else:
                        timings['validation_seconds']=round(timings.get('validation_seconds',0.0)+perf_counter()-phase,6)
                else:
                    return finish(Answer(self._no_answer(),'rag',intent,'insufficient_evidence',contexts=contexts,error_code=str(e),diagnostics=trace))
            else:
                timings['validation_seconds']=round(perf_counter()-phase,6)
            return finish(Answer(finalize(raw+'\n\n【服务端来源】\n'+render_citations(citations)),
                'rag',intent,'answered',citations,contexts,diagnostics=trace))
        except Exception:
            return finish(Answer(finalize('服务暂时异常，未输出未经校验的答案，请联系人工客服。'),
                'rag',intent or '未知','error',error_code='rag_failed',diagnostics=trace))

    def generate_answer(self,query,source_filter=None,history=None):
        return self.generate_result(query,source_filter,history).answer

    def generate_answer_stream(self,query,source_filter=None,history=None):
        # Preamble reaches the client before blocking retrieval/generation; interruptions retain it.
        yield config.DISCLAIMER+'\n\n'
        result=self.generate_result(query,source_filter,history,use_stream=True)
        body=result.answer.replace(config.DISCLAIMER,'').strip()
        for i in range(0,len(body),32):yield body[i:i+32]
