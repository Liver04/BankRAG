# BankRAG 2026-10-14 follow-up closeout

本报告记录上一轮认可的 1—6 项工作。范围为本机求职演示项目；本次回归使用 `bankrag_holdout_v1.1.0` 的 100 个合成场景、220 个 HTTP/WebSocket 请求，调用项目配置的 DashScope API。没有使用真实客户信息。测试问题及公开资料外发已获得用户对本批次的明确授权。

## 1. 确认问题修复

本轮修改集中在：

- `base/safety.py`：识别涉及利率表、现行利率的当前性问题，避免被归为闲聊或投资建议。
- `rag_qa/core/query_classifier.py`：在 BERT 回退前处理公开存款保险问题、缺少关键信息的转账费用和网点营业时间问题；风险规则优先级不变。
- 新增 `base/clarification.py`：转账问题缺银行/渠道/金额时追问必要字段；网点问题缺地区时追问地区，并明确系统不读取定位或实时营业状态。
- `integrated_qa.py`：在合规判断和问题指代解析后、FAQ/RAG 分流前调用公开业务澄清逻辑。
- `base/evidence_guard.py` 与 `rag_qa/core/prompts.py`：加强被引文本“未出现”判断、金融机构名称的来源支持、法规适用范围推断的证据约束；有限证据守卫版本为 `bounded_evidence_v4`。
- 新增 `tests/test_review_followup.py`，覆盖新增分类、追问、证据守卫和流式免责顺序。

9 条专项测试通过。代码快照与修改前备份/差异见 `evaluation/results/worklist_20261014/step1_manifest.json`、`evaluation/results/worklist_20261014/step1_changes.diff` 及 `evaluation/results/worklist_20261014/before/`。

这些规则是有限的模式和来源检查，不构成完整的事实蕴含判定；未解决的跨通道差异见第 3 节。

## 2. WebSocket 免责声明顺序

检查 `app.py` 的 WebSocket 路由和新增测试：连接建立后先发 `start`，在生成正文前发送免责声明 token；异常路径返回错误帧时也保留免责声明。成功与异常两条专项测试通过。

本轮真实 WebSocket 回归中 110/110 条响应的最终免责标记恰好出现一次。110/110 条在首个正文前收到 token；WebSocket 首 token P50 为 0.086 秒、P95 为 0.135 秒。这里的“首 token”是免责声明，不代表正文已开始生成。

## 3. HTTP + WebSocket 全量回归

运行命令：

```powershell
python -B -m evaluation.holdout_runner --mode diagnostic --transport both --workers 2 --output-dir evaluation/results/worklist_20261014/full_v2_4
```

真实执行结果：

- 计划/尝试/完成：220/220/220；HTTP 110 条、WebSocket 110 条；重试 0。
- 运行前后代码、模型、知识快照和 FAQ 指纹一致：`runtime_stable=true`。
- 运行依赖健康检查通过：MySQL、Redis、Milvus、意图分类器均为可用。
- HTTP 200：110/110；HTTP 与 WebSocket 协议完成、历史保存、轮数正确、最终免责声明恰好一次：各 220/220。
- 有答案的轮次 85 条：HTTP 42、WebSocket 43；这些有答案轮次的服务端引用绑定检查均通过（85/85）。其余无引用要求或被安全策略拦截的轮次不纳入此项分母。
- 结构化结果中的 `error_code` 有 39 条安全回退：33 条 `missing_or_invalid_citation`、6 条 `evidence_guard_failed`。这不是网络/模型调用崩溃；守卫拒绝发布未通过检查的生成结论。两种通道均为 0 条传输错误，且 `no_generation_error` 检查 220/220 通过。
- 同一场景的 HTTP 与 WebSocket 结果有 3 组 decision/error_code 差异：H-N05、H-N06、H-U06。差异体现生成波动或守卫结果不同；因此两种通道并非完全逐题一致，需留作回归问题。
- 结果是开发诊断集上的首轮回归，不是人工盲测，也不是金融事实准确率。辅助模型裁判的分数未用作通过结论。

逐条请求、响应、contexts、协议标记、时延及诊断保存在 `evaluation/results/worklist_20261014/full_v2_4/trace_rows.jsonl` 和 `traces.json`；最终运行状态、哈希和汇总见 `manifest.json`。SHA-256：`7956ea7f9ed2a188e330010174c24af223edd658651218535bfd4153a647af07`。

## 4. 演示/部署步骤

新增 Windows 操作手册：`docs/demo_runbook_windows.md`，覆盖启动前依赖、PowerShell `.env` 准备、Compose 配置检查、启动、FAQ 与 Milvus 数据导入、健康检查、日志、浏览器入口和停止命令。端口说明与现有 Compose 配置一致：应用 8090、MySQL 3308、Redis 6380；Milvus 使用宿主机已有实例。

本轮执行 `docker compose config --quiet` 返回退出码 0，Compose 配置解析通过。Docker Desktop 提示无法读取本机 Docker 配置文件的访问警告；本轮没有重新拉取镜像、构建镜像、启动全新 Compose 栈或验证浏览器，因此不能据此声称容器部署已经通过。

## 5. 性能观测

以下为 220 个请求的端到端实测，P95 使用 nearest-rank 口径：

| 通道/指标 | P50 | P95 | 最大值 |
|---|---:|---:|---:|
| HTTP 总耗时 | 15.951 秒 | 86.021 秒 | 91.049 秒 |
| WebSocket 总耗时 | 15.816 秒 | 88.974 秒 | 99.142 秒 |
| WebSocket 首免责声明 token | 0.086 秒 | 0.135 秒 | 0.168 秒 |
| WebSocket 首正文 | 15.645 秒 | 88.791 秒 | 98.955 秒 |

快速策略路径（问候、拒答、转人工、追问）多数约 0.4—0.6 秒；需要生成或做证据守卫的路径更慢，回答类请求 P50 约 23 秒，P95 约 86—90 秒。现有 trace 没有分别记录检索、重排、DashScope 首包及证据校验的耗时，所以只能报告端到端结果；不能断言具体哪个组件占主导。WebSocket 立即发送免责声明，但正文采用缓冲校验后再发送，首正文耗时仍接近总耗时。

这是一批 220 请求的演示负载观测，不是并发压力测试或稳定性 SLA。下一步若要定位耗时，需为各阶段加本地计时点并使用固定场景复测；再次调用云端模型需另行授权。

## 6. 自动化验证和项目描述

全量自动化测试：

```text
Ran 247 tests in 4.211s
OK
```

包括本轮新增 9 条专项测试。`README.md` 已新增本轮说明及结果链接，并保留历史版本的结果作为历史记录；当前 220 条回归明确标记为诊断用途，不称为准确率或独立盲测。Windows 演示步骤与本轮 manifest 已链接。

## 当前仍需改进

1. 处理 H-N05/H-N06/H-U06 跨 HTTP/WS 差异，并把三条场景加入固定逐题比较。
2. 逐题复核 39 次引用/证据守卫回退，判断属于合理拒绝、生成缺陷还是引用绑定问题；不应为降低回退率而放松守卫。
3. 对 85 条已回答轮次做有能力的独立事实复核。当前这批回归没有独立人工评分，不支持发布“准确率”。
4. 对高耗时路径补充阶段计时和本地压测，再决定是否需要优化检索、重排、模型调用或流式策略。
5. 若需要证明容器可复现，需在镜像源可用时完成真实 build/up、健康检查、网页操作及清理验证。
6. 本轮没有重新运行 RAGAS；旧 RAGAS 结果不能代表本轮代码和知识版本。
