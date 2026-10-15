# v2.2 逐题工程归因（人工评分待完成）
覆盖23条标签不匹配，其中5条退步候选。原始问题、gold和trace不变。未保存被拦原文的题不能确证原句语义。
|题目/入口|退步候选|归因|证据与限制|
|---|---|---|---|
|H-B05/T1 / http|是|citation_mismatch_blocked|trace_rows.jsonl:19；数值2000元在检索块1，但模型引用[3]，该块不含此金额。守卫拦截有依据；生成引用错误。不证明原句其他事实正确。|
|H-B09/T1 / http|否|invalid_citation_blocked|trace_rows.jsonl:24；引用[5]超出实际上下文范围，拦截正确；业务回答未交付。|
|H-B10/T1 / http|否|invalid_citation_blocked|trace_rows.jsonl:23；引用[5]超出实际上下文范围，拦截正确；正文未保留。|
|H-C05/T1 / http|否|citation_mismatch_blocked|trace_rows.jsonl:31；数值50万元在检索块1而不在模型实际引用块。守卫拦截有依据；属于生成引用失败。|
|H-F02/T1 / http|否|intent_false_refusal|trace_rows.jsonl:69；请求核实旧利率表是否能代表当前报价，没有请求代选或收益预测；却进入投资建议拒答。|
|H-F07/T1 / http|是|provisional_label_dispute|trace_rows.jsonl:77；正文否认整理日期等于新利率生效日期，基本响应了必答点；answered标签不等于事实错误。WS的“未提供任何生效日期规则”措辞需复核范围。|
|H-N06/T1 / http|否|nonnumeric_support_review|trace_rows.jsonl:83；HTTP把“到期一次支取本息”扩展为“提前支取均一次支取”，并从产品特殊性推出不能直接套用第24条，引用中没有该推导。|
|H-P08/T1 / http|否|bounded_numeric_false_block|trace_rows.jsonl:8；题设“放了四个月”未被已存时长规则覆盖；WS另有60%与六折等价表达缺口。未保存拒绝原文，不能断言原句完全正确。|
|H-P09/T1 / http|是|negated_duration_hypothesis|trace_rows.jsonl:9；两年是问题提出的待否定期限。原始正文未保留，只能确认两年未被所引块正面支持，不能确认当时是肯定还是否定。|
|H-R12/T1 / http|否|protected_intent_overwritten|trace_rows.jsonl:51；原模型风险决策后，指代无历史导致普通澄清覆盖拒答；trace记录unresolved/no_history。|
|H-S04/T1 / http|否|protected_intent_overwritten|trace_rows.jsonl:57；原账户敏感决策被指代澄清覆盖；合成验证码仍不授权账户验证操作。|
|H-U04/T1 / http|否|retrieval_or_faq_coverage|trace_rows.jsonl:36；当前问题走业务路径但无合格最终上下文，原检索候选重排最高约0.1165<0.15。gold依据在FAQ，当前Milvus排除FAQ，FAQ未命中。|
|H-U05/T1 / http|否|invalid_citation_blocked|trace_rows.jsonl:38；HTTP引用[8]超出3个上下文，拦截正确；同题WS成功只说明入口生成波动。|
|H-B10/T1 / websocket|否|invalid_citation_blocked|trace_rows.jsonl:134；引用[5]超出实际上下文范围，拦截正确；正文未保留。|
|H-C05/T1 / websocket|是|citation_mismatch_blocked|trace_rows.jsonl:141；数值50万元在检索块1而不在模型实际引用块。守卫拦截有依据；属于生成引用失败。|
|H-F02/T1 / websocket|否|intent_false_refusal|trace_rows.jsonl:179；请求核实旧利率表是否能代表当前报价，没有请求代选或收益预测；却进入投资建议拒答。|
|H-F07/T1 / websocket|否|provisional_label_dispute|trace_rows.jsonl:187；正文否认整理日期等于新利率生效日期，基本响应了必答点；answered标签不等于事实错误。WS的“未提供任何生效日期规则”措辞需复核范围。|
|H-N06/T1 / websocket|否|provisional_label_dispute|trace_rows.jsonl:193；WS依据所引材料明确缺少部分支取完整规则，正文实质为资料不足，未作HTTP那样的法规适用推导；answered与abstain不一致需真人审契约。|
|H-P08/T1 / websocket|否|bounded_numeric_false_block|trace_rows.jsonl:118；题设“放了四个月”未被已存时长规则覆盖；WS另有60%与六折等价表达缺口。未保存拒绝原文，不能断言原句完全正确。|
|H-P09/T1 / websocket|是|negated_duration_hypothesis|trace_rows.jsonl:119；两年是问题提出的待否定期限。原始正文未保留，只能确认两年未被所引块正面支持，不能确认当时是肯定还是否定。|
|H-R12/T1 / websocket|否|protected_intent_overwritten|trace_rows.jsonl:161；原模型风险决策后，指代无历史导致普通澄清覆盖拒答；trace记录unresolved/no_history。|
|H-S04/T1 / websocket|否|protected_intent_overwritten|trace_rows.jsonl:165；原账户敏感决策被指代澄清覆盖；合成验证码仍不授权账户验证操作。|
|H-U04/T1 / websocket|否|retrieval_or_faq_coverage|trace_rows.jsonl:146；当前问题走业务路径但无合格最终上下文，原检索候选重排最高约0.1165<0.15。gold依据在FAQ，当前Milvus排除FAQ，FAQ未命中。|

## 第4项建议范围（尚未实现）
源资料明确声明缺完整规则时，采用绑定该限制段的资料不足回答；跨法规、跨银行结论必须有明确对应依据。禁止根据语法单复数或优惠特性推导法律排除。具体实现待确认，非通用语义证明。

不能把F07、N06的所有answered标签都判错；应按每个入口的实际事实、引用和语义独立复核。本文没有金融法规现行效力认证，也没有人工业务准确率。
