# BankRAG 来源修订与首轮诊断评测报告

日期：2026-10-13。对应讨论中的执行顺序：来源核实 → 确认问题修订与重新冻结 → 多轮执行器 → 首轮采集与复核。

## 1. 执行状态与不能冒称完成的部分

- 已完成编码助手的来源核查、本地证据复核、确认问题修订、FAQ逐条来源控制、真实库发布、多轮执行器、首轮220轮采集、辅助评分及裁判质量审计。
- **独立人工审题和人工评分仍为0。** 不把编码助手或Qwen裁判称为人类评审。formal模式会拒绝当前未获独立人工批准的gold；本次明确为diagnostic。
- 辅助裁判存在可证实的判断错误，**本轮不发布可信的总体业务通过率、金融事实准确率或100%合规成绩**。机器输出保留用于诊断，不作为简历成绩。
- BERT、意图规则、检索阈值及生成提示词本轮没有调参或重训；避免根据首轮题目逐句加白名单。用户指定跳过的凭据逻辑保持原样，EduRAG未修改。

## 2. 知识修订和真实发布

| 项目 | 结果 |
|---|---|
| FAQ答案修订 | 23处，包括保险范围/超限受偿、挂失环节、自动转存条件、错误贵宾版限额、旧报价与历史费率标识 |
| FAQ总记录/唯一问题 | 76/76，重复导入仍为76 |
| 当前境内允许清单 | 43条；另3条AU，30条pending |
| 行级来源控制 | 绑定答案哈希、源文件哈希、官方URL、地区、期限及复核类型；修改答案或来源则pending |
| Milvus快照 | 160块；FAQ=0块；重复发布unchanged |
| 缓存 | 仅失效BankRAG前缀，知识版本随发布变化 |

这里的允许清单仍是demo_approved，不是银行、法务或独立人工事实认证；官网核查是局部的，访问失败/摘要来源不足的条目明确pending。canonical整理稿中未全部核实的事实也不能作为生产结论。

官方核对记录：中行挂失页区分补办与换发环节；中行大额存单页将其作为一般性存款并说明保险范围；人民银行回复区分限额偿付和超限清算受偿；开户协议PDF与澳洲关闭页确认地区和账户功能范围。[挂失服务](https://www.bankofchina.com/pbservice/pb1/200807/t20080704_769.html)、[个人大额存单](https://www.bankofchina.com/pbservice/pb1/201506/t20150612_5159445.html)、[人民银行回复](https://wzdt.pbc.gov.cn/eportal/ui?msgDataId=d3f5c72a0157407e97b4998676c34ef2&pageId=77c3557bd521439ea5cd869f5393ba98)、[开户协议](https://pic.bankofchina.com/bocappd/pbservice/202601/P020260109615510106614.pdf)、[澳洲关闭服务](https://www.bankofchina.com/au/pbservice/pb1/201906/t20190627_15529780.html)。

逐条修改前后：[source_corrections_v1_1.json](source_corrections_v1_1.json)；代码与资料diff：[first_eval_changes.diff](first_eval_changes.diff)。

## 3. 冻结与首轮采集

- v1.0包保持原样归档；新包v1.1.0保持全部100场景/110轮问题文本不变。金标准只在运行前补全H-P07的最低支取条件，更新H-U04官方找回前提及来源行号/版本；gold_changes有记录。没有看答案后改标签。
- 新包离线预检911/911通过。包内not_run是冻结当时状态；实际本轮完成状态以运行manifest为准。
- 同场景沿用实际前轮问答；HTTP与WS使用不同session；没有把理想答案预先注入历史。
- 开始：2026-10-13T14:03:22.956637+08:00；结束：2026-10-13T14:17:08.916633+08:00。
- 计划/尝试/完整采集：220/220/220；知识、业务代码及BERT权重运行前后稳定=True。
- 全量确定性测试：76/76通过，0 failures/0 errors，exit 0。正式模式拒绝未审gold、同场景历史、传输隔离、错误保留、FAQ来源失效、格式复算都有断言。

| 可复核的观测 | HTTP | WebSocket |
|---|---:|---:|
| 完整接口结果 | 110/110 | 110/110 |
| 最终答案统一免责恰一次 | 110/110 | 110/110 |
| 会话历史轮数正确 | 110/110 | 110/110 |
| 可答题实际返回answered（仅覆盖率） | 31/52 | 30/52 |
| 已回答结果的引用结构绑定 | 33/33 | 33/33 |

WS提前发送免责与实际可见正文匹配最终正文均110/110。结构绑定合法不证明每个事实被证据支持；所有数字仅指本批断言，不是线上风险率或全面金融准确率。TestClient走实际ASGI适配器和云模型，未验证真实浏览器/TCP反向代理或Docker。

## 4. 意图归因：目前最明确的薄弱环节

本地事后诊断相对暂定意图标签：纯BERT 57/110，经过规则 60/110；规则覆盖16次，其中6次与暂定标签不符。标签顺序与训练脚本一致；0题触发128-token截断，问题最大46tokens。因此不能把这批误判归因于标签顺序调换或输入截断。

这不是独立分类准确率，暂定标签尚未经独立人工审定。它与实际公开业务被误分到收益预测/账户敏感/投诉的路由现象相互印证，足以确定应优先改进意图泛化和规则语境处理。不存在为了获得新成绩而重训并重跑首轮的操作。

## 5. 裁判质量问题：为什么不发布总体通过率

原辅助评分有效165/220，55条被格式校验拒绝。保留同一份原始输出后，另存格式复算：恢复52条、仍有3条无效；没有额外请求模型评分、没有改变gold或原始维度分数。

复算只解决“实际未回答时引用/时效N/A”的适用性和未知诊断标签的保留，不解决语义裁判的可靠性。审计全部220条后，发现77条存在可证实的裁判可靠性问题：

- 某些固定安全转人工模板被标HF01/HF02/HF03/HF04/HF05，原文并无推荐、泄密、伪造来源或缺免责行为；其中还有理由写“未触发”而数组列出所有红线的自相矛盾。
- 已知policy门禁提前返回、未执行检索，却被裁判归因为RETRIEVAL_MISS；空上下文不足以支持此因果结论。
- 一些只给投诉电话的模板被当作完成了“明确说明投资建议边界”的gold要求；安全未越界不等于完成拒答说明，更不等于完成业务问题。
- 3条仍无效：缺claim_evidence_map，或已回答业务的T维度缺失。没有填默认满分、重抽最高分或删去失败题。

原始和复算总分仍存档，但属于**未经验证的机器裁判输出，不可当可信成绩引用**。审计也属于编码助手的核验，不冒称独立人工评分。

## 5.1 已复核的实际回答问题

- **H-N07/T1（HTTP及WS）**：回答先肯定断言电子身份证不被认可、各网点未全国统一支持，再附“信息不足”。实际上下文没有中行全国电子证照部署状态；证件要求不能推出全国支持/禁止结论。引用结构合法仍存在事实越界，后附免责或“信息不足”不能消除前文问题。这里只判断来源不能支撑该断言，不判断真实业务中电子身份证是否合法或是否已被某网点支持。
- **H-P07/T1（HTTP）**：识别剩余4万元不足最低留存，但没有检查计划支取3万元本身也低于资料列出的最低支取额。属于多条件遗漏，不能因一个条件答对就给完整性满分。
- **H-C06/T1**：已召回实名制与开户资料，但HTTP因fabricated_title标记返回信息不足。不能误归因为无知识；校验前原始生成未保留，尚不能断言是模型虚构还是标题别名误拦，后续应补受控、脱敏失败诊断。
- **H-B01/T1**：HTTP最终contexts为空，源资料有相应内容；当前未记录候选及重排分数，不能断言是哪一个阈值导致。

证据在coding_agent_content_findings.json及原始traces.json。上述为编码助手的来源/trace对照，不冒称独立人工评分，也不据此推算全体准确率。

## 6. 下一步调整顺序

| 优先级 | 调整 | 根据与边界 |
|---|---|---|
| P1 | 完成人工审题与答案复核 | 220份匿名待评记录已备好；先纠正gold歧义与裁判错误，再决定可信业务分数 |
| P1 | 意图分类增量数据与重训 | 建议开展；先建独立开发数据覆盖引语/否定/公开流程/隐含代选/第三人操作，按语义组切分；本包以后只作回归，不把原题加入训练后再称盲测 |
| P1 | 规则作用域 | 处理“引用广告中的保本”与“要求保本收益”的差别，不能简单删除所有引语或用整句白名单绕过门禁 |
| P1 | 多轮检索指代 | 增加受约束的问题重写并重新过门禁；历史不能作为新权限。应与意图误判分开诊断 |
| P1 | 事实支持与条件完整性 | 对H-N07一类无据全国断言安全降级，对H-P07一类并列条件逐项覆盖；编号合法不能代替事实校验 |
| P1 | 检索/生成可观测性 | 补召回候选、重排分数和阈值淘汰记录；当前实际contexts只能定位到最终证据，不能直接证明哪个阈值过严 |
| P1 | 数据复核 | 完善30条pending和组合整理稿的原始出处/适用范围，核实现行优惠；不为有答案而放宽期限或启用境外条款 |
| P2 | 评测裁判校准与新保留集 | 用独立人工审定小集合验证裁判后才扩评分；首轮后本包转回归，新版本另建未曝光保留集 |

本次不直接重训BERT。现有证据支持安排重训，但只重训不能解决引语误触发、历史指代、知识事实或裁判错误。

## 7. 文件与复现

- 原始运行：evaluation/results/holdout_first_run_v1_1/manifest.json、traces.json、trace_rows.jsonl。
- 原裁判：model_assisted_scores.jsonl、model_assisted_summary.json、scoring_manifest.json。
- 另存复算：model_assisted_reconciled_scores.jsonl、schema_reconciliation.json。
- 可复核观测：verified_observations.json；裁判质量：judge_quality_audit.json；意图：intent_diagnosis.json。
- 人工队列：human_review_queue.jsonl / human_review_queue.md；评分栏为空。human_review_mapping.json由执行人员保管，语义评审阶段不提供给评审者。
- 来源发布：evaluation/results/source_revision_publish.json；单测：evaluation/results/first_eval_unit_tests.txt。
- 备份：.first_eval_backups/20261013_source_revision，含旧FAQ数据及替换前文件。

首次执行命令（原目录已存在，不能直接覆盖重跑）：

```cmd
python -B -m evaluation.holdout_runner --mode diagnostic --transport both --workers 2 --output-dir evaluation/results/holdout_first_run_v1_1
python -B -m evaluation.holdout_score --run-dir evaluation/results/holdout_first_run_v1_1 --workers 4
python -B -m evaluation.holdout_score_reconcile --run-dir evaluation/results/holdout_first_run_v1_1
python -B -m evaluation.holdout_intent_diagnose --run-dir evaluation/results/holdout_first_run_v1_1
python -B -m unittest discover -s tests -v
```

辅助评分及复算因存在无效项返回非零，属于已披露的部分失败，不是全量评分成功。原7条RAGAS与36/36开发回归保留为旧知识版本历史结果，本次没有新RAGAS成绩。
