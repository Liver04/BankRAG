# BankRAG v2 改造与自测报告

本轮按照用户清单修复；P0-1 API Key 问题明确跳过。对比原始 AST，API Key、MySQL/Redis 密码配置逻辑一致，config.ini 原字节一致；未改动 EduRAG。

## 1. 分模块修改前后

| 优先级 / 模块 | 修改前 | 修改后 | 验证 |
|---|---|---|---|
| P0 / 合规入口 | FAQ 命中先返回，绕过分类 | gate → FAQ/RAG；业务结果统一 decision | test_faq_cannot_bypass；真实双通道拒答 |
| P0 / FAQ 元数据 | 只有问题答案，缺审核/有效期 | 文档/块 ID、来源、版本、demo_approved、有效期；每次命中回查 DB | 过期/待审/缓存失效/别名断言 |
| P1 / 参数注入 | source 直接字符串插值 | Pydantic Literal + 核心枚举校验 + 固定表达式 | HTTP/WS 非法表达式被拒绝 |
| P1 / 时效 | 整理日期误作生效；失效为 0 | 正文生效/施行日期、整理日期、复核期限分别解析；旧 FAQ rejected | 日期边界、南非地区隔离；当前利率无有效资料则信息不足 |
| P1 / 引用 | 缺失或越界只记日志 | 服务端绑定文档/块 ID，拒绝缺失/0号/越界/虚构标题 | test_citations_reject |
| P1 / 免责 | 正常 RAG 完成才追加 | 所有业务结果 finalize；WS 先发免责，缓冲校验正文 | 异常、中断前置免责、FAQ、拒答断言 |
| P1 / 单候选 | 一个父块直接返回 | 一个候选也 rerank + threshold | test_single_candidate_threshold |
| P1 / 意图 | 转账/身份证/骗等泛词误杀；问候前缀吞业务 | 区分个人操作与公开咨询，问候完整匹配；禁止敏感判断随意降级 | 公共问题及带问候业务断言；真实开户问法复测 |
| P1 / 评测 | 关键词即算拒答；另行检索 contexts；结果版本错位 | HTTP/WS 同一用例版本和哈希；结构化计分；读取实际生成 trace；逐题结果 | fixture/live 分开，真实 RAGAS 输出 |
| P1 / API 与隐私 | 无会话归属；同步阻塞；health 固定 healthy | Cookie/令牌归属；线程 + 并发限制；脱敏历史/日志；依赖 readiness | 越权、历史、健康失败、事件循环断言 |
| P2 / 幂等与旧块 | 重复追加 FAQ；文本 ID 跨来源覆盖 | 唯一规范化问题指纹；事务快照；稳定 doc/version/chunk；Milvus 别名原子切换 | MySQL 连续两次 76/76；快照重入 unchanged；失败不切换断言 |
| P2 / 缓存 | 热点续期；旧索引长期存在 | 固定 TTL + 知识版本 + 命中复核 + BankRAG 前缀主动失效 | 版本和过期缓存断言；不清 Redis 全库 |
| P2 / 配置与退出 | eval；异常后仍宣称完成 | JSON 配置解析；失败非零退出；未完成快照不发布 | 语法、SQL 回滚、快照失败断言 |

### 关键代码对比：合规入口

修改前：
```python
answer, need_rag = self.bm25_search.search(query, ...)
if answer:
    return answer, 'faq'
```

修改后：
```python
intent, blocked = self.rag_system.gate(query)
if blocked:
    result = blocked
else:
    row = self.bm25_search.search_record(...)
    # 每次检查有效期/审核状态，再绑定来源、执行输出规则并追加免责
```

### 关键代码对比：引用

修改前：
```python
if not refs:
    return answer
# 越界仅记录日志，原样返回
```

修改后：
```python
if not refs or any(x < 1 or x > len(docs) for x in refs):
    raise ValueError('missing_or_invalid_citation')
# 使用 citation(docs[i-1], i) 绑定服务端文档和块 ID
```

### 关键代码对比：时效与阈值

修改前：
```python
doc.metadata['effective_date'] = filename_date
doc.metadata['expiry_date'] = 0
if len(parent_docs) < 2:
    return parent_docs
```

修改后：正文生效/施行日期优先，整理日期单列；按注册表内容哈希、演示复核期限和地区过滤；非空候选全部调用 reranker，含单候选。

### 关键代码对比：工程与评测

修改前：共享 MySQL 游标、HTTP 不保存历史、softmax 阈值当匹配概率、RAGAS 重新检索、重复调用裁判分档/总体评分。

修改后：每次操作独立连接；HTTP/WS 同样保存历史；匹配阈值标为词覆盖率；RAGAS 从实际 API trace 取上下文，对每题只评分一次，保存逐题分数和回答覆盖率。

完整可审查的逐文件 unified diff： [remediation.diff](remediation.diff)。凭据内容已从 diff 输出中隐藏，凭据逻辑未修改。

## 2. 真实测试输出

```text
Unit tests: 51/51, failures=0, errors=0
Live HTTP/WebSocket route regression: 36/36
MySQL rows=76, unique questions=76
Milvus snapshot rows=186; second import=unchanged
Evidence-document retrieval checks: 5/5
RAGAS faithfulness=0.982143, valid=7/7
RAGAS answer_relevancy=0.884280, valid=7/7
RAGAS context_precision=0.904762, valid=7/7
RAGAS context_recall=1.000000, valid=7/7
```

实际执行命令：

```cmd
python -m unittest discover -s tests -v
python compliance_evaluate.py --backend fixture --transport both
python scripts/live_validate.py
python ingest.py --validate-only
python ragas_evaluate.py --backend live --from-traces evaluation/results/live_validation.json --output-dir evaluation/results/ragas_live_v2
```

## 3. 首轮失败与修复

真实联调首轮 34/36。开户问法“开户需要身份证吗”分类正确，但检索上下文不够直接，模型输出未满足引用要求，系统安全返回信息不足。没有放松引用校验；增加该公开问法到既有“开立个人账户需要出示什么证件？”的显式别名，并继续按来源/状态/有效期校验。重测 36/36。

首轮逐题记录保存在 evaluation/results/live_validation_before_alias.json，最终记录为 live_validation.json。它们是开发回归，不是独立盲测。

本地 SDK 还发现 pymilvus 3 已无 pymilvus.model；代码支持 milvus_model 导入并保留旧版本回退，真实本地模型已加载成功。本轮没有安装 CUDA 或改变 API Key 配置。

## 4. 结果解读与剩余边界

- RAGAS 只有 7 条可回答开发样本，包含近义问题；recall=1.0 原样披露，不通过混入负样本人为降分。不能解释为独立、全面的金融知识召回率。
- 合规回归通过只表示本集合的明确断言通过，不能宣称全表达“100%合规”。
- 引用校验验证编号、标题和文档块绑定，没有独立证明每个事实被引用内容蕴含。
- demo_approved 是演示允许清单，非银行或法务审核。
- 期限是复核期限，不是法规法定失效；当前境内利率文档已过演示复核期限，拒绝实时利率请求是预期行为。
- 匿名会话隔离不是银行客户认证；规则式脱敏无法识别全部个人信息。
- 流式内容先校验再分片，不能称为未缓冲的实时模型透传；已经断开的网络不能接收最终帧。
- 已在本机既有环境完成测试，尚未完成干净环境安装、Docker 构建、生产压测和灾备验收。
- Milvus 旧原始集合保留用于回滚，不再被 v2 查询使用；别名只指向一份完整新快照。并发导入仍按单写者运行。

## 5. 升级与回退

代码同步前逐文件检查原始哈希，并备份被替换文件到 .remediation_backups。FAQ 迁移前原数据 JSON 一并备份；Milvus 仍保留原始集合及一个上版快照。仅使用 BankRAG 数据库、集合和 Redis bankrag: 前缀，未修改 EduRAG。

重启 Web 服务后使用新代码。当前 HTTP/WS 会话必须先创建，不兼容旧无所有权凭据的 session_id；浏览器页面已调整为等待会话初始化。

## 6. 同步后的最终检查

- 55 个改造文件已同步到指定 BankRAG 目录，25 个原有文件被修改，其余为新增文件/结果。
- 在目标目录重新执行完整 unittest：51 tests，0 failures，0 errors，exit code 0。
- 再次确认 config.ini 字节未改变，API Key 和密码配置 AST 未改变。
- 默认服务适配器补充测试：真实本地模型、MySQL、Redis、Milvus；HTTP 与 WS 均走 RAG，保存两轮历史，health 为 healthy。云端 completion/stream 使用替身并阻断外部 HTTP，结果见 evaluation/results/default_adapter_offline_smoke.json。该项不计作真实云模型问答成绩。
- 额外的默认适配器真实云流式冒烟最初被自动审批拒绝，理由为检索上下文外发未获明确授权；当时采用上述本地替代方案。用户随后明确授权将公开存款资料片段及指定问题发送给配置的 DashScope API，已补跑成功，详见第 7 节。离线替身结果与真实云模型结果分别保存。
- 备份目录：.remediation_backups/20261012_173849，其中 database/faq_before_v2.json 保存迁移前 FAQ。

## 7. 获得授权后的真实云端流式冒烟

2026-10-12 获得用户明确授权后，仅使用问题“整存整取最低起存金额是多少”及公开存款资料，设置 source_filter=product，创建新的匿名演示会话。通过 FastAPI TestClient 驱动实际 HTTP/WebSocket ASGI 路由，使用默认 IntegratedQASystem、本地真实模型和数据库，以及真实 DashScope completion/stream；没有使用云端响应替身。

```text
DEFAULT_ADAPTER_LIVE_SMOKE
passed=true
HTTP decision=answered, channel=rag
WebSocket end decision=answered, channel=rag
health_status=200 (MySQL/Redis/Milvus/classifier all true)
history_count=2
provider_requests=4
provider_stream_requests=1
exit_code=0
```

已断言：两条入口均具有引用与实际检索上下文；HTTP/WS 完整答案的统一免责声明各出现一次；WS 在业务正文前先发送免责声明，全部 token 合计包含一次免责声明；两轮问答保存成功。调用计数通过包装原始 SDK 方法观测，仍调用原方法，不伪造返回值。

真实结果：[default_adapter_live_smoke.json](../evaluation/results/default_adapter_live_smoke.json)。原离线替身结果继续单独保留。本次只补充端到端集成证据，不增加独立评测样本，不更新前述 7 条 RAGAS 指标，也不证明金融事实准确率或全部合规表达的覆盖率。TestClient 验证的是 ASGI 路由与实际云端模型调用，未验证真实浏览器、网络代理、Uvicorn TCP 服务或 Docker 部署。
