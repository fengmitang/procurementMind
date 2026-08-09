# Web Agent 与 HITL 契约基线 v0.1

更新日期：2026-08-09

## 服务边界

- 浏览器只访问采购后端提供的开发 BFF：`/demo-api/agent-chat` 与
  `/demo-api/agent-actions/{confirm|cancel}`，不持有身份网关 Secret。
- Agent 服务通过签名身份调用现有采购后端 HTTP API；正式写入仍由采购后端校验权限、状态机、
  乐观锁、幂等和字段规则。
- Agent 不接受任意 URL、SQL 或数据库连接参数。确认执行器只允许固定动作枚举映射到固定接口。

## Web 展示契约

智能协同结果统一展示回答、业务分析、知识引用、检索 Trace 摘要、Review、执行详情和待确认动作。
知识引用包含文档标题、章节路径、版本、源文件和行号；Trace 展示原问题、改写问题以及
Dense、Sparse、RRF、Rerank、Parent 扩展数量。实时事实仍以 Tool 返回为准。

## 人工确认状态契约

`PendingAction` 包含不可预测的 `action_id`、一次性 `confirmation_token`、受控 `action_type`、
结构化 `draft`、创建时间和过期时间。确认/取消接口同时绑定平台身份、会话和动作。

- 未确认：不调用业务写接口。
- 确认：校验身份、会话、动作、凭证、有效期和草稿后，通过现有采购 API 执行一次。
- 取消：清理待确认状态，不调用业务写接口。
- 过期：记录 `EXPIRED`，不调用业务写接口。
- 重复请求：返回 `ALREADY_EXECUTED`、`ALREADY_CANCELED` 或 `ALREADY_EXPIRED`，不重复执行。
- 并发请求：同一进程按身份与会话串行；跨实例仍由采购后端动作 Token 和版本号兜底。

处理结果写回现有 Agent Session 的 `collected_data.last_resolved_action`，清除
`pending_action` 和 `awaiting_confirmation`，并保存 MySQL 快照。确认凭证不会写入已处理记录。

## 正式动作映射

允许动作覆盖提交采购申请、审批通过、驳回、最终供应商/采购结果、提交入库、登记入库和完成采购。
每类动作只映射到对应的采购后端端点；草稿不完整时 Web 禁用确认，服务端仍会再次拒绝。

## 验收

- HITL 单元与接口测试覆盖未确认不执行、一次执行、重复、取消、过期、错误凭证、草稿缺失和并发。
- BFF 测试覆盖测试身份白名单及只允许 `confirm`/`cancel`。
- 前端测试覆盖 Secret 扫描、Citation、Trace、确认和取消控件。
- 本地真实浏览器已验证智能协同页、能力状态、对话输入与结构化结果布局可见。
