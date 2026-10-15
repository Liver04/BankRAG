# BankRAG 来源修订后首轮诊断包 v1.1.0

100场景、110轮；问题文本与v1完全一致。v1保持原样归档，不能用其旧知识/代码哈希代表本轮。

本轮完成编码助手的来源核查和本地证据复核，仍无独立人工审题。因此只能用显式diagnostic模式采集，formal模式默认拒绝未获独立人工批准的gold。

运行命令（qa_system目录）：

```cmd
python -B -m evaluation.holdout_runner --mode diagnostic --transport both --workers 2 --output-dir evaluation/results/holdout_first_run_v1_1
```

输出目录必须不存在，防止覆盖首次结果。两种传输共220轮；多轮同场景保留实际回答历史，HTTP与WS会话分开。不会把gold发给生成模型。

来源修订：FAQ逐条绑定答案/来源哈希、地区、期限及复核状态；76条中43条CN可用、3条AU、30条pending。FAQ不再进入Milvus，避免整文件元数据绕过逐条控制。

金标准变化在gold_changes.json，全部发生于首轮运行前。H-P07补全“支取金额本身不足最低额”的遗漏；H-U04同步官方找回前提的原文；其余只更新位置与版本。所有gold_status仍待独立人工审题。

来源有效性、库内证据正确性和生成成绩分别记录。辅助模型评分不叫人工评分，同模型生成/裁判存在偏差。本包首轮后用于修复就属于回归集。

原评分标准在docs/holdout_review_standard.md。完整结果与实际知识/代码版本由执行器保存，不覆盖旧RAGAS指标。
