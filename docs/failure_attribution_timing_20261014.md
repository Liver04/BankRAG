# 2026-10-14 回归失败归因与阶段计时

本报告基于 `evaluation/results/worklist_20261014/full_v2_4/trace_rows.jsonl`、对应冻结 gold `evaluation/holdout_v1_1/answer_key.jsonl`，逐轮按 `turn_id` 对齐。该批是已完成的 100 个合成场景、220 次 HTTP/WebSocket 诊断回归。没有重新请求 DashScope。

## 一、39 条安全守卫回退如何解释

`error_code` 非空共 39 条。逐轮对齐 gold 后，不应把 39 条都算成系统错误：

| 归因 | 数量 | 对应结果 | 判断 |
|---|---:|---|---|
| 本应回答，但守卫将回答回退为信息不足 | 21 | 16 条引用越界；4 条数值支持不通过；1 条机构名称缺少引用来源支持 | 回答覆盖损失，需要针对性修复与复测 |
| 预期本就应信息不足 | 16 | 15 条因模型没有给引用编号而走安全回退；1 条教育储蓄材料误读被守卫拦截 | 最终决策符合 gold；错误码描述的是候选生成未通过校验 |
| 预期澄清，回退为信息不足 | 2 | H-N01 两个传输结果 | gold 明确把 `insufficient_evidence` 列为可接受结果 |

细分证据：

- 33 条 `missing_or_invalid_citation` 中，16 条引用编号大于当前上下文数量，且都对应预期回答的场景；17 条没有编号，全部来自预期信息不足/澄清场景。
- 6 条 `evidence_guard_failed` 中，4 条 `unsupported_numeric_atom`（H-P01、H-P13 各两种传输），1 条 `unsupported_named_authority`（H-U06/HTTP），1 条 `source_text_misread`（H-N06/HTTP）。最后一条对应预期信息不足，拦截结果正确。
- 预期回答但被拦截的 21 条分别为 H-B01、H-B09、H-B10、H-B12、H-C06、H-M05/T2、H-M08/T2、H-P01、H-P13、H-U05、H-U06。引用越界的 16 条全部落在这组可回答场景里。

代码仍坚持服务端引用绑定与证据守卫；不建议自动重编号或放宽数值/来源规则。适合的修复方向是：对越界引用做一次受限重答并完整重验；把可识别的标准“信息不足”答复作为正式 `insufficient_evidence` 决策，而不要求它伪造事实引用；对数值规则按“用户题设”与“银行事实”分开校验。

## 二、没有错误码但决策不符合 gold 的记录

- H-N05/HTTP 与 H-N06/WebSocket 的正文都表达了“资料不足/无法确认”，却被标为 `answered`；对应另一传输分别被守卫回退。说明当前决策由“回答通过引用与证据校验”推导，不能识别正文中的保守拒答语义。
- H-F07/HTTP 与 WebSocket 均为 `answered`，正文虽然说“不能”并指出资料未说明利率调整与整理日期的关系，但 gold 期望 `insufficient_evidence`。同样需要把答复语义与决策字段绑定。
- H-U04/HTTP 与 WebSocket 均为 `insufficient_evidence`，但其 gold 支持材料存在于 `rag_qa/data/finance/faq/开户销户FAQ__20261011.md`。FAQ 没有命中；RAG 检索返回 10 个候选，最终 0 个通过 0.15 重排阈值。应优先检查 FAQ 问题归一化/同义词召回和候选证据，再决定是否调整阈值，不能直接全局降阈值。
- H-N02、H-N04 两个澄清问题在 HTTP 与 WebSocket 都返回了正确的 `clarify`，但 gold 的 `acceptable_decisions` 只列 `insufficient_evidence` 和 `answered`，漏了 `clarify`。这是评测 schema 与期望行为不一致；冻结包不应在本轮静默改写，后续应升版本修订 gold 并保留旧包。

## 三、三组跨传输差异

| 场景 | HTTP | WebSocket | 归因 |
|---|---|---|---|
| H-N05 | 有引用、标为 `answered`，正文实际说明资料未提供完整金额 | 无引用，被守卫回退为 `insufficient_evidence` | 内容接近，但决策/引用因生成措辞不同而分叉 |
| H-N06 | 文本误读守卫拦截，`insufficient_evidence` | 引用了资料的不完整性并说明无法确认，却标为 `answered` | 对相同材料生成措辞不同；决策识别也不一致 |
| H-U06 | 机构来源守卫拦截无来源支持的机构表述 | 生成简短、来源支持的回答并标为 `answered` | 守卫正确阻止未支持声明；云端生成有波动 |

因此 `temperature=0` 下跨请求仍不保证逐字或逐决策确定。不能把三组差异简单归因于 HTTP/WebSocket 传输实现；目前证据更支持两次独立模型生成的波动及决策规范化缺失。

## 四、已增加阶段计时

改动在 `integrated_qa.py` 和 `rag_qa/core/rag_system.py`：

- `route_phase_timings`：策略门、历史读取、问题解析、FAQ 检索、FAQ 来源验证、RAG 调用、历史写入和路由总耗时。
- `rag_phase_timings`：检索与重排、结构化答案、条件计划、模型生成、证据验证和 RAG 总耗时。
- 新计时位于内部诊断字段；普通 `Answer.public()` 会移除 diagnostics，不向普通客户端响应暴露。需要诊断时仍受既有 `include_trace` 配置限制。
- 新增专项断言验证计时字段存在、非负；不把 fixture 的耗时当生产性能数据。

本轮未使用新增计时字段重跑云端请求，所以旧批次的端到端 P50/P95 不能拆分成这些阶段。运行该批次后，才有真实的 FAQ、检索/重排、生成和校验耗时分布。重新调用 DashScope 需要对新一批测试外发另行授权。

## 五、验证与下一轮顺序

- 专项测试：10/10 通过。
- 全量测试：`Ran 248 tests in 2.980s`，`OK`。
- 阶段计时前源文件备份在 `evaluation/results/worklist_20261014/timing_before/`；差异文件 `evaluation/results/worklist_20261014/timing_changes.diff`。

建议后续按此顺序处理：

1. 修复“内容表达资料不足却标 answered”的决策归一，并仅对越界引用做一次有边界的重答；拒答仍须可追溯，引用仍需原样校验。
2. 修复 H-P01/H-P13 的数值语境支持，建立用户题设数字与引用银行事实的分离规则；H-U06 保持机构名称必须有来源支持。
3. 为 H-U04 增加受控 FAQ 同义词/问题变体召回，确认命中后仍执行来源哈希、审核状态与期限校验。
4. 新版本评测包将 `clarify` 加入对应 gold 的可接受决策，并保留原冻结版本。
5. 在获准的下一批真实接口回归中采集新 `route_phase_timings` 与 `rag_phase_timings`，再判断检索、重排或模型阶段是否是时延主因。

当前 holdout gold 标记为 `pending_independent_human_review`；以上归因用于工程诊断，不代表独立人工事实评分或正式金融业务验收。
