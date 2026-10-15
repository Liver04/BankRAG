# BankRAG 收尾改进记录（2026-10-15）

## 变更

1. RAG 回答正文出现明确“资料不足/无法确认”语义时，结构化决策归一为 `insufficient_evidence`，使用统一保守答复，不再把它报告为 `answered`。
2. 对缺失或越界引用最多进行一次受限重答，只允许引用当前检索上下文的编号；服务端再次完整执行引用绑定与证据检查。修复失败则返回信息不足。没有自动重编号。
3. 数值守卫支持同一来源中可明确串联的事实：题设给出的存期按场景前提复述；大额存单剩余金额规则可引用同一文件明确列出的购买起点。跨产品金额仍由来源兼容规则拦截。
4. FAQ 为忘记网银登录凭据的公开流程增加受控问法别名，命中仍由 FAQ 原有审核、来源文件哈希和有效期校验决定。没有降低全局 Reranker 阈值。
5. 新建 holdout v1.2.0：保留 v1.1 冻结包，H-N02/H-N04 增加 `clarify` 可接受决策。问题文本、证据和其他评分点不变。

## 回归边界

运行命令与真实结果：

```text
python -B -m unittest discover -s tests -v
Ran 255 tests in 3.002s
OK

python -B evaluation/holdout_v1_2/validate_pack.py
status=passed, checks_passed=918, checks_total=918
scenarios=100, turns=110, prior_unique_texts=2511, exact_old_question_duplicates=0
```

完整输出保存在 `evaluation/results/closeout_20261015/`。数值语境专项：45/45 通过。离线校验不调用模型或数据库，不构成线上接口回归。FAQ 的真实 MySQL 记录状态及完整 HTTP/WebSocket 生成行为尚未用新云端请求复测；新阶段时延也需另批授权请求采集。gold 仍标为待独立人工审题，本包只用于诊断。

## 修改前后行为

| 情况 | 修改前 | 修改后 |
|---|---|---|
| 正文说资料不足但引用合法 | 仍可能返回 `answered` | 归一为 `insufficient_evidence`，走统一保守答复 |
| 引用编号越界 | 立即安全回退 | 同上下文最多重答一次并完整复验；仍失败则回退 |
| 缺少引用编号 | 立即安全回退 | 仍立即安全回退，不尝试生成引用 |
| P01/P13 数字语境 | 题设存期或同文档交叉引用可能被误判为无依据 | 只接纳可定位到题设或同一来源明确交叉关系的数字；跨产品仍拦截 |
| 忘记网银登录凭据的变体问法 | FAQ 可能未命中，随后进入低分 RAG 检索 | 受控映射到已审核 FAQ 条目，再执行原有来源与有效期检查 |
| H-N02/H-N04 的澄清答复 | gold 不接受 `clarify` | v1.2 加入 `clarify`，v1.1 原包保持不变 |
