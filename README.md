# BankRAG：银行存款与公开业务 FAQ 演示项目

从 EduRAG 迁移的学生求职作品。核心链路已实现并有断言回归，但不等同于银行生产系统、投资顾问或法律合规认证。

> 当前验证快照：2026-10-15。最新代码的验证范围与限制见第15节；此前章节中的阶段结果按历史记录保留。

## 1. 已实现的能力与边界

| 能力 | 实现 | 边界 |
|---|---|---|
| 统一入口 | 先做规则/BERT 意图判定，再分流 FAQ/RAG | 规则及模型仍可能漏判或误拒，不承诺全部表达都识别 |
| FAQ | 规范化精确匹配、公开问法别名、BM25 候选与词覆盖阈值 | 覆盖分数不是概率；每次命中复核 MySQL 状态/有效期与真实支持文件哈希、审核及期限 |
| 检索 | BGE-M3 稠密/稀疏混合检索，父子块，BGE reranker | 单候选也执行阈值；阈值仍需独立数据调优 |
| 来源 | 服务端绑定文档 ID、块 ID、版本和 URL；接受上下文中实际出现的官方标题别名 | 缺失/越界编号或上下文外标题被拦截；合法引用不等于每句话已被语义证明 |
| 事实检查 | 检查引用材料中的阿拉伯/中文数字单位、特定电子证件/全国网点断言、通知存款部分支取条件 | 有限规则；不提供完整语义蕴含证明，可能过度拒答，不能替代金融人工复核 |
| 多轮与诊断 | 最多追溯5轮连续产品指代，原问题与消解后问题分别执行风险判断；候选与重排淘汰记录随请求返回 | 只消解预定义存款名称，歧义需澄清；诊断默认不对公开调用开放 |
| 免责声明 | 成功、拒答、信息不足、FAQ、异常统一附加 | WS 先发送免责；已经断开的网络无法接收最后一帧 |
| 流式交付 | 模型输出先缓冲校验，再分段发送 | 不再透传未经校验的模型 token，因此首个业务正文会延迟 |
| 时效 | 生效日期、整理日期、复核期限分离，检索前过滤 | 期限是本地演示的新鲜度策略，不是法律失效日期 |
| 会话 | HttpOnly Cookie 或 X-Session-Token 归属校验；HTTP/WS 均存历史 | 匿名演示会话隔离，不是实名银行认证 |
| 工程 | 工作线程隔离同步调用、依赖健康检查、幂等导入、快照发布 | 尚无生产压测、灾备或完整运营治理 |

支持五类意图：闲聊、业务咨询、收益预测、投诉、账户敏感。无法可靠确认时返回信息不足。纯问候采用完整匹配，带后续业务内容时正常进入分类。

## 2. 数据治理

金融知识在 `rag_qa/data/finance/`，审核注册表为 `knowledge_catalog.json`。

- `demo_approved` 是本地演示允许清单，**不表示银行、法务或独立事实审核通过**。
- 注册表绑定内容 SHA-256；文件修改后需要重新复核并更新注册表，否则进入 pending。
- 明确声明包含大量过时信息的旧 financezhidao FAQ 已拒绝导入。
- 官方生效/施行日期优先于文件名；整理日期独立记录。未知生效日期为 0，不伪造为入库当天。
- 没有官方失效日期时，演示复核期限为：利率 30 天，产品/业务规则/FAQ 90 天；法规可不设失效日期，但不表示已确认其最新法律效力。
- 境外资料保留地区标识，默认境内客服检索只使用 CN。南非利率不会作为境内利率返回。
- 当前利率问题只使用有效的利率表；当前库中的境内旧利率表已超过复核期限，因此相关问题应返回信息不足。
- Markdown FAQ 是统一导入源；同内容 TSV 是历史导出附件，避免重复导入两份。
- Milvus 以完整快照构建后切换 `finance_deposit_v1_active` 别名。保留一个回滚快照；旧原始集合不再用于 v2 检索。
- 单个进程执行入库；并发导入的分布式互斥、法律审查与自动官方更新尚未实现。

## 3. 目录

- `base/safety.py`：公共输出、白名单、有效期、脱敏、引用结构。
- `base/knowledge.py`：注册表、生效/整理日期、稳定文档版本。
- `base/evidence_guard.py`：有边界的事实与条件检查；`base/conversation.py`：保守产品指代。
- `evaluation/human_calibration.py`：匿名待评材料、真人双评导入、同批裁判校准；空表不生成成绩。
- `integrated_qa.py`：统一合规入口、FAQ/RAG、会话。
- `rag_qa/core/`：意图分类、父子块、混合检索、引用校验。
- `mysql_qa/`：独立连接、唯一问题指纹、版本化缓存。
- `app.py`：HTTP、WebSocket、匿名会话归属、健康检查。
- `tests/`：确定性回归，模型和外部服务使用可控替身。
- `evaluation/cases_v2.json`：带版本和哈希的固定评测集。
- `evaluation/results/`：新评测结果；每种结果注明 fixture/live。
- `docs/remediation_report.md`、`docs/remediation.diff`：本次改造说明和修改前后完整对比。

## 4. 本地启动（Windows CMD）

先进入项目目录，激活自己的 Python 环境。模型仍使用本地目录。API Key 从进程环境或根目录 `local_secrets.env` 读取；该文件被 Git 与 Docker 忽略。Compose 测试使用 `docker compose --env-file local_secrets.env ...`。不要提交或打包本地凭据。

```cmd
cd /d D:\pythonProject\EduRAG_project\Bank_RAG_code\qa_system
conda activate EduRAG
python faq_to_mysql.py --dry-run
python ingest.py --dry-run
python faq_to_mysql.py
python ingest.py --ingest-only
python -m uvicorn app:app --host 127.0.0.1 --port 8090
```

前两个命令仅检查；后两个命令分别发布 FAQ 和向量知识快照。首次升级会迁移 BankRAG 自己的 FAQ 表并增加唯一约束；旧数据不再作为自动审核通过的数据使用。不要对 EduRAG 数据库执行这些命令。

MySQL、Redis、Milvus 连接仍使用项目现有配置。模型默认放在 `rag_qa/models`，也可用 `MODELS_DIR` 指向既有模型。不要把整个模型目录链接到 EduRAG 后再向其中训练写入。

依赖直接版本见 requirements.txt，实际测试环境见 evaluation/results/environment.json。2026-10-15 已在全新 Python 3.10.18 虚拟环境中安装 requirements.txt，pip check 无依赖冲突，255 条自动化测试通过。共享 EduRAG 环境额外安装的 langchain-experimental 0.4.2 与项目锁定的 langchain-community 0.4.1 不兼容；这项冲突未出现在隔离环境。Docker Compose 配置解析通过，但应用镜像构建未完成，原因和边界见第15节。

## 5. API 使用

浏览器先 POST `/api/create_session`，服务端设置 HttpOnly Cookie；随后 HTTP 和 WebSocket 使用返回的 session_id。非浏览器客户端可自行生成高熵访问令牌，所有请求通过同一 `X-Session-Token` 发送。

- POST /api/query：query、source_filter、session_id。
- WS /api/stream：相同字段，帧类型 start/token/end/error。
- GET/DELETE /api/history/{session_id}：需要同一 Cookie/令牌。
- GET /health：检查 MySQL、Redis、Milvus、分类模型；依赖异常返回 503。
- source_filter 仅接受 product/rate_table/regulation/business_rule/faq。
- 诊断 contexts/diagnostics 默认关闭；仅本地评测时设置 BANKRAG_ALLOW_TRACE=1。普通响应提供 citations，不暴露完整上下文。
- 跨域来源通过 CORS_ORIGINS 配置；HTTPS 部署时设置 BANKRAG_COOKIE_SECURE=1。

## 6. 测试与指标口径

```cmd
python -m unittest discover -s tests -v
python compliance_evaluate.py --backend fixture --transport both
python compliance_evaluate.py --backend live --transport both --output evaluation/results/compliance_live_v2.json
python ragas_evaluate.py --backend live
```

- fixture 结果证明确定性路由、协议和拦截逻辑，不证明真实金融问答准确率。
- live 结果使用本地真实模型、数据库和 API；固定用例已用于开发回归，**不是独立盲测**。
- 合规计分检查结构化 decision/intent、明确拒答、禁止推荐性输出及引用绑定，不再将“咨询客户经理”等词视为拒答成功。
- RAGAS 从同一生成结果读取真实 contexts，不再另行检索。只对可回答子集评分，同时披露回答覆盖率和被排除的失败项。
- RAGAS 每题只评分一次，保存逐题结果与有效样本数；无效/NaN 不默默计入满分。
- 历史根目录结果文件属于旧版本，不能代表本版本。旧 README 的 100% 合规、85% 检索、RAGAS .66/.80 已撤下。
- BERT 历史 checkpoint 验证准确率约 98.33%，来自合成数据随机验证切分；不是本轮独立测试成绩。
- 2026-10-12改造历史结果见docs/remediation_report.md；2026-10-13来源修订后的首轮诊断见docs/first_holdout_evaluation_report.md。知识版本不同，旧36/36回归和7条RAGAS不能代表新测试集成绩；不承诺“零漏判”或“100%合规”。
- 2026-10-12 的默认适配器真实云端冒烟是历史结果，见 evaluation/results/default_adapter_live_smoke.json；它不代表后续代码状态。2026-10-15 最新代码的实时后端验证见第15节。

评测问题与隐私测试标识为合成示例，不应输入真实客户账户或身份数据。

## 7. 尚未达到生产级的部分

匿名会话不是客户认证；规则式脱敏不是完整 PII 识别；引用编号校验不是事实蕴含证明；数据审核清单不是监管认证。仍需独立盲测、人工事实审核、生产认证授权、并发压测、监控告警、保留期限治理、灾备以及部署验收。


## 8. 历史：2026-10-13来源修订与首轮诊断

- FAQ逐条绑定来源/答案哈希、地区、期限及复核状态；76条中43条CN可用、3条AU、30条pending。FAQ只走MySQL，不再整文件进入Milvus。
- 向量知识快照160块；重复导入幂等，配置和凭据逻辑未改变。
- 确定性单元测试76/76通过；100场景、HTTP/WS共220轮真实ASGI接口结果已保存。
- 本批免责与会话历史检查220/220；66个已回答结果引用结构绑定有效。这不证明事实准确率。
- 52个暂定可答轮次中，HTTP31个、WS30个返回answered，仅表示回答覆盖率。
- 相对暂定意图标签，本地BERT为57/110，前置规则后60/110；不是独立分类准确率。这是升级前结果；当前版本比较见下一节，仍不视为盲测准确率。
- 辅助裁判出现错误红线、错误因果归因和不成立的通过判断；不发布其总体分数为可信成绩。独立人工评分仍为0。
- 来源修订包为evaluation/holdout_v1_1；v1.0保留作历史快照。首轮后本包进入回归用途，后续泛化应另建保留集。

详细报告：[首轮诊断与下一步调整](docs/first_holdout_evaluation_report.md)。人工复核队列：[human_review_queue.md](evaluation/results/holdout_first_run_v1_1/human_review_queue.md)，评分栏未填写。


## 9. 历史 v2.1.1 改进与验证范围

- **BERT 已实际 CPU 重训并替换**：从本地 bert-base-chinese 全参数微调5轮；480条合成措辞样本来自120个基础请求。按55个人工定义语义族划分：训练42族/368条，验证13族/112条，组交叉为0。验证匹配109/112（97.32%），仅是开发验证分数，标签仍待人工复核。
- 旧100场景/110轮已成为回归集。相同暂定意图标签上，纯 BERT 57→106/110；当前规则和指代模块配旧模型为80/110、配新模型为109/110。它们是开发后比较，不能当独立泛化或端到端业务正确率。
- FAQ输出同时绑定FAQ记录和真实支持文件；命中时重新检查文件哈希/审核/有效期；支持文件改变或有限事实检查失败，回落RAG。43条当前CN可用FAQ通过支持文件校验，其中42条通过最终有限事实规则，1条题设月份复述被保守拦截并回落RAG；不等于已获独立事实审核。
- 检索保留原始问题，并最多追加3条策略查询。诊断保存实际过滤表达式、候选ID/混合分数、父块重排分数、阈值与淘汰原因；诊断不存完整检索问题，也没有共享的 last_trace 状态。
- 流式仍是供应商流生成→服务端完整缓冲与校验→安全分段交付。有限事实检查失败时不输出被拒正文，统一返回信息不足及免责。
- 新保留集候选版30场景/33轮已冻结，尚未执行、未发云端；gold为空待独立人工审定。作者参与开发，不能称为第三方独立盲测。
- 独立人工评审仍为0；用户选择先交付待评材料。历史Qwen裁判失真问题未被“调高分数”掩盖。本轮不发布新的裁判总体分数、人工一致性或RAGAS成绩。
- 初版 context_v2 的基础请求划分过细，30轮接口回归已中止并保留，不能计为完成；最终采用更粗语义族的 context_v2_1，所有历史文件保留。

证据和最终接口运行状态见 [本轮改进报告](docs/context_upgrade_report.md)。模型上线前版本保存在 `.context_upgrade_backups/`。已运行的网页进程须重启才能加载新代码和权重。

### 可重复命令（Windows CMD）

```cmd
python -B -m unittest discover -s tests -v
python -B scripts/build_context_intents.py --version context_v2_1
python -B scripts/train_context_intent.py --root D:\pythonProject\EduRAG_project\Bank_RAG_code\qa_system --version context_v2_1 --epochs 5
```

训练器仅写候选目录；目录存在时拒绝覆盖，应使用新的版本名复现。构建数据后先人工检查语义族；不要运行历史随机切分脚本覆盖当前服务模型。本轮训练没有使用原2400条随机划分数据。若重新训练、增加数据或改gold，应新增版本并保留原结果。

人工评分材料使用 `python -B -m evaluation.human_calibration prepare --run evaluation/results/context_v2_1_regression --pack evaluation/holdout_v1_1 --out evaluation/review_context_v2_1` 生成，输出目录存在时不覆盖。评分人员分别填写后，用 `import --packet ... --completed ... --out ...` 导入；待评时退出码2，不把待评标为失败或满分。裁判校准须同批 trace/gold 哈希匹配，并满足预登记样本量与正反样本要求。

最终自动化测试 140/140 通过；v2.1完整回归220/220，最终事实/引用补丁另有22/22专项接口复测。二者版本范围分别报告，不能混称最终代码全量220轮。独立人工评审与新保留集执行均未完成。


## 10. 历史 v2.2：检索、数值支持和完整回归

- 最终代码自动化测试175/175通过；100场景、HTTP/WS共220轮真实后端ASGI接口回归完成，运行前后指纹一致。不是公网部署验收。
- 父块采用原文窗口重排，阈值保持0.15，引用和生成上下文仍绑定完整父块；窗口最大分可能增加误候选和CPU时延，不能作为置信概率。
- 数值校验区分被引银行规则、明确题设与精确减法；不把用户假设的利率/费用当银行事实。通知存款金额例题按原文分别核对两项门槛；来源缺项/冲突/外币时不套用；一般条件漏项最多内部重答一次再校验。
- FAQ有限规则检查43/43通过；没有独立人工评分、新RAGAS分数或新保留集成绩。BERT和知识文档未改动。
- 回答覆盖、引用绑定和协议通过都不等于金融事实正确；具体数值、剩余问题及耗时见 [本轮报告](docs/quality_v3_report.md)，修改前后见 [代码对比](docs/quality_v3_changes.diff)。
- 本节测试数量属于历史v2.2；当前结果以第11节及correctness_v4_development/release_manifest为准。网页服务需重启；不需要重训BERT或重新导入Milvus。

本轮仍有23条暂定行为标签不匹配，其中5条相对参考完整版本由匹配转为不匹配；未声称端到端零退步。数值等价/否定语境、部分非数值断言、既有风险意图与指代优先级、以及P95时延仍需改进，详见本轮报告。


## 11. 历史阶段 v2.3.3：风险指代与数值引用修复

- 核查原23条暂定标签不匹配及其中5条退步候选；保留gold和全部原始结果，不把标签匹配率当业务准确率。
- 原始风险意图保持绑定，不能被指代澄清降级；正常业务解析后重新判断权限和合规。
- 数值有限守卫支持明确题设时长、折扣百分比及有来源上限的否定；拒绝已识别的产品/银行冲突、费用/利率折扣混用。词汇和语法覆盖有限，不是完整事实蕴含。
- 错引数字或问题中有猜测期限但实际引用有明确更低上限时，可从相同上下文最多重答一次并完整复验；原句仍先拦截，不自动改引用号，不把其他检索块或源上限当原错误句的证明。缺失/越界引用继续拦截，仍可能损失回答覆盖。
- 最终自动化测试238/238；43/43当前可用FAQ通过有限守卫。v2.3、v2.3.1、v2.3.2分别完成40/40、26/26、12/12请求；最终v2.3.3核心专项12/12。完成请求不等于业务通过，批次分开保存、不能合并为最终全量220轮或挑选最佳答案。
- 第4项非数值推断防护尚未实现；人工评分仍待提交，新保留集未执行，没有本轮新RAGAS分数。BERT、知识、凭据逻辑未改。
- 真实输出、逐题失败和后续建议见 [修复与验证报告](docs/correctness_v4_report.md)、[代码对比](docs/correctness_v4_changes.diff)。网页进程需重启。

## 12. 2026-10-14跟进：诊断回归与演示材料

- 修复当前利率表问题的意图识别，补充转账费用/网点问题的必要字段追问，并加强引用文本、机构名称及法规适用范围的有限证据检查；详细改动见 `evaluation/results/worklist_20261014/step1_changes.diff`。
- WebSocket 在正文前发送免责声明；成功、异常专项用例通过。
- 新增 9 条专项测试；全量自动化测试 247/247 通过。
- 100 个合成场景、HTTP/WS 共 220 次真实 ASGI 请求完成，运行前后指纹稳定，依赖健康检查通过。免责、协议和历史写入检查 220/220 通过；85 个 `answered` 轮次的结构化引用绑定检查通过。39 个结果因引用或有限证据守卫转为安全回退；同题跨通道有 3 组决策/守卫差异。该批是诊断回归，不是准确率或独立盲测。
- HTTP 总耗时 P50/P95 为 15.951/86.021 秒；WebSocket 为 15.816/88.974 秒，首正文 P50/P95 为 15.645/88.791 秒。当前没有检索、重排和模型阶段拆分计时。
- 新增 [Windows 演示与部署步骤](docs/demo_runbook_windows.md)。`docker compose config --quiet` 通过；本轮未重新 build/up，不能视为部署验收。
- 本轮未运行 RAGAS，未新增独立人工事实评分。

逐题记录及限制见 [本轮跟进报告](docs/worklist_closeout_20261014.md)，运行指纹和状态见 [回归 manifest](evaluation/results/worklist_20261014/full_v2_4/manifest.json)。本节结果仅适用于本轮代码、知识和模型快照。

## 13. 2026-10-14后续：失败归因与阶段计时

- 按冻结 `turn_id` 对齐 39 条安全回退：21 条是预期回答被守卫拦截，18 条分别符合预期的信息不足或澄清；不把 39 条直接当错误率。
- 另发现 H-N05/H-N06/H-F07 的“正文说资料不足、decision 却为 answered”，H-U04 的 FAQ 未命中且 RAG 重排无候选通过阈值；H-N02/H-N04 的 gold 漏列 `clarify`。三组 HTTP/WS 差异及逐题原因见 [归因报告](docs/failure_attribution_timing_20261014.md)。
- 增加路由与 RAG 内部阶段耗时诊断；普通响应不包含诊断字段，开启既有 trace 后可读取。新增专项测试后，全量测试为 248/248 通过。
- 本轮没有用新增计时字段发起新一批 DashScope 请求，因此尚无新的真实阶段 P50/P95；之前的端到端数据不能拆解成阶段耗时。重新云端回归需要另行授权。

阶段计时前代码备份与差异见 `evaluation/results/worklist_20261014/timing_before/` 和 `evaluation/results/worklist_20261014/timing_changes.diff`。

## 14. 2026-10-15 收尾改进

- RAG 正文明确表达资料不足/无法确认时，决策统一归为 `insufficient_evidence`，避免正文与结构化 decision 不一致。
- 只有出现明确越界引用编号时，才基于同一检索上下文进行一次受限重答；服务端重新执行完整引用绑定和证据校验。缺失引用不重答，重答仍越界则安全回退，不自动重编号。
- 数值守卫支持同一产品资料中明确列出的存期与计息规则组合，以及“剩余部分需满足起点金额”对同一文档购买起点的明确引用。不同产品的金额仍不能互相借用，也不会把用户给出的假设利率/费用转成银行事实。
- 为忘记网银登录凭据的公开问法增加受控 FAQ 别名。命中仍需通过 FAQ 审核状态、来源文件哈希、有效期及答案证据校验；没有降低全局重排阈值。
- 新增 holdout v1.2.0，保留 v1.1 原包，仅修正 H-N02/H-N04 可接受 `clarify` 的动作契约；问题文本未变，评测仍是待独立人工审题的诊断包。
- 全量本地测试 255/255、数值语境专项 45/45 通过；v1.2 离线完整性检查 918/918 通过。未发起新一批 DashScope 请求，因此不报告新线上回答质量或阶段时延。

改动、验证输出及评测包审计说明见 [收尾记录](docs/closeout_followup_20261015.md)；新版评测包见 `evaluation/holdout_v1_2/`。

## 15. 2026-10-15 最新代码验证

- **隔离环境复现**：新建 Python 3.10.18 虚拟环境，按 `requirements.txt` 安装成功；`pip check` 输出 `No broken requirements found.`；全量自动化测试 `Ran 255 tests ... OK`。完整依赖版本、pip check 和测试输出保存在 `evaluation/results/verification_20261015/clean_environment.json`、`pip_check_clean_env.txt` 与 `unit_tests_clean_env.txt`。共享 EduRAG 环境中的 `langchain-experimental 0.4.2` 额外依赖冲突不影响隔离环境验证。
- **真实后端 ASGI 集成冒烟**：通过当前默认适配器、真实 MySQL/Redis/Milvus、意图分类器和配置的 DashScope 调用 HTTP 与 WebSocket。公开存款问题在两种通道均返回 `answered`、各有1条引用；服务端引用与本次实际上下文绑定，HTTP 数值答案在被引材料中有支持；免责声明检查通过。投资建议请求在两种通道均返回 `refused` 并带免责声明。另验证健康检查 HTTP 200（MySQL、Redis、Milvus、分类器均健康）及同一会话四轮历史写入。共15/15项断言通过，机器可读结果为 `evaluation/results/verification_20261015/live_e2e.json`。报告保存检查结果和代码哈希，不保存完整回答、上下文或凭据。
- **验证边界**：这是针对一个公开存款问法和一个拒答问法的定向集成冒烟，不是独立盲测、准确率或 RAGAS 评测。请求经 FastAPI `TestClient` 实际 ASGI 路由执行，未验证浏览器、公网网络链路或生产部署。
- **Docker**：凭据清理后重新检查，`docker compose --env-file local_secrets.env config --quiet` 通过；Docker 构建上下文由约896 MB缩至56.28 kB。`.dockerignore` 已排除本地配置、密钥、模型/知识数据、评测结果和备份。镜像构建最终状态见第16节。

以上结果仅代表 2026-10-15 记录的代码和本地知识快照。历史回归数字不与本次定向冒烟合并，也不据此声称金融事实经过独立专业审核。

## 16. 2026-10-15 上传前凭据清理

- DashScope API Key 已从源码和普通配置中移除，保存在项目根目录的本地 `local_secrets.env`，仅供本机测试；文件 ACL 已限制为当前 Windows 用户。运行时从进程环境或该文件加载。Compose 通过 `--env-file local_secrets.env` 获取本地测试所需变量；`.env.example` 只保留占位符。
- `base/config.py` 不再含 API Key 或数据库/Redis 密码默认值；Compose 改为要求运行时注入相应变量。历史文本副本中的 Token 格式内容已清理。
- 候选源码、README、差异文档和配置模板扫描：Token 格式命中0，硬编码凭据赋值候选0。Git 忽略规则已验证会排除 `local_secrets.env`、`config.ini` 和历史备份；Docker 忽略规则也覆盖这些文件以及评测产物。
- `docker compose --env-file local_secrets.env config --quiet` 通过。
- 镜像构建状态：未完成。安全构建上下文已缩至56.28 kB，随后在下载 PyTorch（约532 MB）及 CUDA 依赖阶段主动中止，避免上传前检查继续拉取数 GB 依赖；未生成/启动应用容器。因此 Docker 镜像仍未验证。
- 本项目目录尚无 `.git` 元数据；这次只检查工作区候选文件，不包括 Git 历史、暂存区或远端内容，因此尚未创建或上传 GitHub 仓库。
