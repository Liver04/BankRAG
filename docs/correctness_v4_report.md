# BankRAG 第1—3项修复与针对性验证

最终代码版本：v2.3.3。人工评分待完成；第4项仅提出建议范围，尚未实现。

## 1. 逐题归因

23条暂定标签不匹配（含5条退步候选）全部逐项核查，见 `evaluation/results/correctness_v4_development/case_audit.md/json`；每条保存原问题、实际回答、源文档/块/版本及trace行号。原gold、原结果不变。工程归因不是独立人工评分。

|归因类别|记录数|
|---|---:|
|错引数字被拦截|3|
|越界引用被拦截|4|
|公开时效问题误拒|2|
|暂定行为标签争议|3|
|非数值无据推断待复核|1|
|题设/等价表达支持缺口|2|
|否定期限语境待确证|2|
|风险意图被指代覆盖|4|
|FAQ/检索覆盖不足|2|

五条退步候选：B05 HTTP、C05 WS属于错引数字被拦；F07 HTTP可能是暂定行为契约过严，仍需逐句核验额外断言；P09 HTTP/WS未保存原始拒绝正文，仅能确定数字不在实际引用中，不能确证当时是否否定。不能声称全部误拦或全部金融事实错误。

## 2. 修改前后

### 2.1 意图与指代优先级

修改前：模型单独判风险时，`resolve_query`可把拒答覆盖为普通澄清。修改后：原始收益预测/账户敏感/投诉决策保持绑定；普通业务无指代依据才澄清，成功解析后重新过gate。代价是模型误判风险仍可能误拒，不能宣称分类问题全部解决。

```python
# before
if not blocked or original_rule is None:
    ...
    if effective_query is None: blocked = clarification
# after
protected = blocked is not None and intent in ("收益预测", "账户敏感", "投诉")
if protected: resolution = {"status": "not_attempted_protected_intent", "intent": intent}
else: ...  # ordinary resolution, then gate again
```

### 2.2 数值语境与等价表达

修改前：只支持部分已存措辞，不识别六折到60%的折算，正面数字存在性无法判断超上限的否定。修改后：同题明确已存时长允许有界复述，保留银行期限/费用/利率禁用条件；折数归一为百分比，但必须是折扣系数并匹配利率或费用基准；否定期限必须在问题中出现且超过同产品被引资料明确给出的计息档上限。该检查不是法律/金融语义证明。

```text
允许：客户“放了四个月” → “实际存期为四个月”。
允许：被引利率打六折 → 该基准利率的60%，或六折（即60%）。
拦截：年利率为60%；将手续费折扣当利率折扣；另一产品/已识别其他银行的数值。
有条件允许：问题提及两年，所引同产品原文无论存多久只按1年期档 → 不会延长到两年。
继续拦截：肯定两年档；没有明确上限就否定；跨“但可以”把肯定语句视为否定。
```

### 2.3 错误文档引用

修改前：记录数字未支持但缺少逐数字实际块绑定诊断。修改后：每个数字保存实际引用编号、doc/block/version、支持编号及未引用替代块编号；替代块只作重答线索，不能让原答案通过。数字在同属性、相容产品/已知银行的其他实际上下文中存在时，最多重生成一次，随后执行完整引用与事实守卫；不直接改编号。无来源数字、缺失/越界引用继续拦截，异常只交付安全文本。

未知否定措辞不会凭上限直接放行。若每个未支持数值都有同属性替代块，或该期限在问题中出现且同产品实际引用明确给出更低计息档上限，最多一次重新生成，只解释原文上限、避免复述未支持年数，再完整校验。源上限仅用于重答资格，不作为原错误句的支持证明。原本错误的肯定两年句必须先失败；重答仍错误则继续失败。

完整修改前后代码：[correctness_v4_changes.diff](correctness_v4_changes.diff)。备份：`.correctness_backups/v4`（本轮前）及v4_final、v4_causal、v4_cap_repair（各补充前）。

## 3. 验证结果与版本范围

最终发布后自动化测试：**238/238**，包含原175项及新增63项；43条当前可用CN FAQ通过同一有限支持守卫。它们不代表独立事实准确率。

原v2.2已交付RAG正文用最终守卫及当轮真实上下文离线回放：95/95保持通过。只说明这些固定正文未新增拦截，不能证明新生成不会退步。快照日至当前日的24份资料可用性变化：0份。

|批次|版本|计划/完成|运行指纹稳定|请求重试|
|---|---|---|---|---|
|首批针对性|v2.3|40/40|True|0|
|等价/措辞补充|v2.3.1|26/26|True|0|
|因果否定补充|v2.3.2|12/12|True|0|
|最终核心专项复测|v2.3.3|12/12|True|0|

所有批次保留失败结果；补充改善了数值等价/时长/否定措辞，另建最终批次，不能把不同批次合称最终版本全量通过。另有一次P09单独诊断生成，不是原始被拦正文、不计入成绩；定位“不因存期延长而升档至”因果否定，旧守卫拒绝、新守卫通过，比较证据见p09_causal_comparison.json。本轮没有重跑全220轮。

|最终入口|完成|免责一次|历史正确|已回答/其中引用绑定有效|生成异常|
|---|---:|---:|---:|---|---:|
|http|6/6|6|6|4/4|0|
|websocket|6/6|6|6|4/4|0|

### 各版本逐题结果（不代替人工评分）

|版本|题目|入口|v2.2行为|本批行为|错误码|
|---|---|---|---|---|---|
|v2.3.1|H-B01/T1|http|answered|insufficient_evidence|missing_or_invalid_citation|
|v2.3.1|H-B05/T1|http|insufficient_evidence|answered|-|
|v2.3.1|H-C05/T1|http|insufficient_evidence|answered|-|
|v2.3.1|H-C06/T1|http|answered|insufficient_evidence|missing_or_invalid_citation|
|v2.3.1|H-M01/T1|http|answered|answered|-|
|v2.3.1|H-M01/T2|http|answered|answered|-|
|v2.3.1|H-M02/T1|http|answered|answered|-|
|v2.3.1|H-M02/T2|http|answered|answered|-|
|v2.3.1|H-P07/T1|http|answered|answered|-|
|v2.3.1|H-P08/T1|http|insufficient_evidence|answered|-|
|v2.3.1|H-P09/T1|http|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.1|H-R12/T1|http|clarify|refused|-|
|v2.3.1|H-S04/T1|http|clarify|handoff|-|
|v2.3.1|H-B01/T1|websocket|answered|insufficient_evidence|missing_or_invalid_citation|
|v2.3.1|H-B05/T1|websocket|answered|answered|-|
|v2.3.1|H-C05/T1|websocket|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.1|H-C06/T1|websocket|answered|insufficient_evidence|missing_or_invalid_citation|
|v2.3.1|H-M01/T1|websocket|answered|answered|-|
|v2.3.1|H-M01/T2|websocket|answered|answered|-|
|v2.3.1|H-M02/T1|websocket|answered|answered|-|
|v2.3.1|H-M02/T2|websocket|answered|answered|-|
|v2.3.1|H-P07/T1|websocket|answered|answered|-|
|v2.3.1|H-P08/T1|websocket|insufficient_evidence|answered|-|
|v2.3.1|H-P09/T1|websocket|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.1|H-R12/T1|websocket|clarify|refused|-|
|v2.3.1|H-S04/T1|websocket|clarify|handoff|-|
|v2.3.2|H-B05/T1|http|insufficient_evidence|answered|-|
|v2.3.2|H-C05/T1|http|insufficient_evidence|answered|-|
|v2.3.2|H-P08/T1|http|insufficient_evidence|answered|-|
|v2.3.2|H-P09/T1|http|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.2|H-R12/T1|http|clarify|refused|-|
|v2.3.2|H-S04/T1|http|clarify|handoff|-|
|v2.3.2|H-B05/T1|websocket|answered|answered|-|
|v2.3.2|H-C05/T1|websocket|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.2|H-P08/T1|websocket|insufficient_evidence|answered|-|
|v2.3.2|H-P09/T1|websocket|insufficient_evidence|insufficient_evidence|evidence_guard_failed|
|v2.3.2|H-R12/T1|websocket|clarify|refused|-|
|v2.3.2|H-S04/T1|websocket|clarify|handoff|-|
|v2.3.3|H-B05/T1|http|insufficient_evidence|answered|-|
|v2.3.3|H-C05/T1|http|insufficient_evidence|answered|-|
|v2.3.3|H-P08/T1|http|insufficient_evidence|answered|-|
|v2.3.3|H-P09/T1|http|insufficient_evidence|answered|-|
|v2.3.3|H-R12/T1|http|clarify|refused|-|
|v2.3.3|H-S04/T1|http|clarify|handoff|-|
|v2.3.3|H-B05/T1|websocket|answered|answered|-|
|v2.3.3|H-C05/T1|websocket|insufficient_evidence|answered|-|
|v2.3.3|H-P08/T1|websocket|insufficient_evidence|answered|-|
|v2.3.3|H-P09/T1|websocket|insufficient_evidence|answered|-|
|v2.3.3|H-R12/T1|websocket|clarify|refused|-|
|v2.3.3|H-S04/T1|websocket|clarify|handoff|-|

真实输出：`evaluation/results/correctness_v4_development/unit_release_published.txt`、`evaluation/results/correctness_v4_release_targeted_console.log`；逐题trace、协议检查和运行前后指纹在对应批次目录。内部受限重答与请求重试分开记录。

## 4. 第4项建议范围（待用户确定）

- 教育储蓄HTTP把“到期一次支取本息”扩大为“提前支取均一次支取”，并从利率优惠等特点推导法规排除，所引原文不支持；建议优先处理该类额外推断。
- 同题WS以资料不足回应，不能因HTTP缺陷一并判错。
- 建议在原文明示缺完整规则时绑定该限制段给出资料不足，禁止从句式单复数推导业务禁令；法律适用性/跨银行相同规则必须有明确对应依据。
- 该范围不是通用NLI系统；暂不自动重标F07/N06、不扩大为全部问题模板拒答。

## 5. 保留问题与限制

引用越界/缺失的生成波动、F02公开时效问题误拒、U04 FAQ语义覆盖不足、非数值蕴含和时延仍需后续工作。各批次失败以表格和trace原样保留；没有端到端零退步、全金融事实正确或生产级合规的结论。已有100场景是开发回归集，新保留集仍未推理；当前没有新增RAGAS或独立人工分数。

模型权重、知识文档、gold、凭据文件和加载逻辑保持原哈希；没有修改EduRAG。网页服务需重启加载代码，不需要重训BERT或重新导入知识。
