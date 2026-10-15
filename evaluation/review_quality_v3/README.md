# 双人核验待评材料

分别复制 review_queue.jsonl 给两位未参与开发的评审，不分发 private_mapping.json 或机器评分。

两人独立填写自己的 reviewer 槽位；评分 0/1/2；业务事实题引用/范围不可留空。每个事实填写 claim_evidence_map。分歧由第三位真人填写 arbitration。禁止用模型代填独立人工分数。

优先完成 manifest 中预登记的校准样本，再评剩余样本。未评和分歧未裁决均保留 pending；暂不发布业务准确率或裁判可信度。

表内包含本场景问题顺序；多轮历史实际可见输出以实际痕迹为准。原始 traces.json 由管理员留存。
