# BankRAG v2 API

以 README 和 app.py 为当前接口契约。旧版本无归属校验的 session_id 调用方式不再适用。

## 会话

POST /api/create_session 返回 session_id，同时设置 HttpOnly、SameSite=Strict Cookie。API 调用者也可提供高熵 X-Session-Token；服务端只保存令牌哈希。仅持有 session_id 不能读写其他访问者会话。此机制用于匿名演示隔离，不替代银行实名认证。

## HTTP

POST /api/query，JSON：
```json
{"query":"开户需要身份证吗","source_filter":"faq","session_id":"由创建接口返回的UUID"}
```

返回 answer/channel/intent/decision/citations/error_code/session_id/processing_time。decision 包括 answered、refused、handoff、greeting、insufficient_evidence、error。

include_trace 默认为 false；服务端仅在 BANKRAG_ALLOW_TRACE=1 时允许 true，并附实际生成上下文 contexts。生产展示应关闭该开关。

GET /api/history/{session_id} 返回最近五轮有效历史；DELETE 同路径逻辑删除历史。HTTP 和 WS 都保存历史，存储前进行规则脱敏。历史不再因超过五轮而物理删除，具体数据保留期限仍需运营制定。

## WebSocket

WS /api/stream：先创建会话，再发送相同 JSON。服务端检查 Origin 和会话归属。

start → token（免责前置）→ token（校验后的正文分片）→ end。end 提供结构化结果及 is_complete。error 携带脱敏错误和免责文本。

模型生成会先缓冲，校验后才交付正文；这是校验后分段输出，不能宣称完全实时透传。连接断开后无法保证最后一帧抵达，先发送的免责用于覆盖正常连接中的生成中断。

## 输入与错误

query 1~2000 字符，拒绝空白。source_filter 为五种文档类型之一；非法表达式输入返回 422。无会话所有权返回 403。默认不返回 SDK 原始错误。

## 健康检查

GET /health：依赖就绪返回 200/healthy，否则 503/degraded；不调用付费模型 API 验证额度或 Key。
