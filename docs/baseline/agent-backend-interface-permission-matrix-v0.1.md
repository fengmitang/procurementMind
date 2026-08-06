# Agent 与采购后端接口复用及权限矩阵 v0.1

## 1. 范围

本矩阵基于 `openapi-backend-v0.1.json`，覆盖 35 条路径、39 个 HTTP 操作。
它约束的是“哪些后端能力可以提供给 Agent，尤其是可以提供给模型调用的 MCP 工具”，
不替代采购后端自身的身份、角色、楼宇、状态机、乐观锁、幂等和事务校验。

## 2. 分类

| 分类 | 含义 |
|---|---|
| 只读可用 | 可由固定后端客户端调用，并可按白名单逐步封装为只读 MCP 工具 |
| 需扩展 | 现有接口可作为基础，但需要安全投影、幂等能力或专用客户端封装；当前不直接暴露给模型 |
| 人工写入 | 会修改正式业务数据；P0 禁用，后续只能经 Human-in-the-loop 确认后调用 |
| 禁止调用 | 不得暴露为模型工具；仅允许运维、后台任务或人工管理入口按说明调用 |

## 3. 全局硬约束

1. Agent、MCP 和 EchoMind 参考模块都不得直接访问采购 MySQL 或 Redis。
2. 所有业务调用通过采购后端 HTTP API，身份由可信网关上下文签名；模型不得提供员工、角色、楼宇或签名密钥。
3. 后端是最终权限裁决方。Agent 侧的工具白名单不能替代后端二次校验。
4. P0 MCP 默认只读。模型生成的工具名、路径、身份字段和任意 URL 不得直接执行。
5. 正式业务写入必须先展示草稿、暂停、接受用户明确确认，再使用最新 `expected_version`；状态流转继续使用唯一 `action_token`。
6. 权限不足、状态冲突、版本冲突和数据不存在时直接返回结构化错误，不重试为其他身份，也不猜测结果。
7. 联系方式、银行账号、通知错误和会话内容按最小必要原则返回；模型上下文不得因为调用者有权就自动包含全部敏感字段。
8. `/demo-api/proxy` 仅用于开发体验且未进入 OpenAPI，不得被 Agent、MCP 或生产集成调用。

## 4. 系统与身份接口

| 方法与路径 | 当前权限/语义 | 分类 | Agent 使用规则 |
|---|---|---|---|
| `GET /health` | 无业务身份；仅报告进程存活 | 禁止调用 | Agent 服务监控可固定调用，不注册为模型工具 |
| `GET /ready` | 无业务身份；探测 MySQL、Redis | 禁止调用 | 编排和运维可固定调用，不向模型泄露依赖状态细节 |
| `GET /api/v1/users/me` | 可信网关身份；返回当前员工、角色和楼宇 | 只读可用 | 作为会话上下文初始化及 `get_current_user` 工具；模型不能覆盖返回身份 |

## 5. Agent 会话支撑接口

这些接口都要求当前用户拥有会话，关联采购单时还会由后端验证可见范围。它们用于 Agent
运行时持久化，不作为模型自由选择的 MCP 工具。

| 方法与路径 | 当前权限/语义 | 分类 | Agent 使用规则 |
|---|---|---|---|
| `POST /api/v1/agent/conversations/active` | 当前用户获取或创建活动会话 | 需扩展 | 封装到固定 `AgentSessionClient`；限制 `current_action` 枚举和长度 |
| `GET /api/v1/agent/conversations/{conversation_id}/messages` | 仅会话所有者；分页读取 | 需扩展 | 运行时恢复上下文使用；进入模型前执行消息裁剪和敏感信息处理 |
| `POST /api/v1/agent/conversations/{conversation_id}/messages` | 仅会话所有者；外部消息 ID 幂等 | 需扩展 | 固定客户端写入；发送者类型由运行时控制，模型不能伪造 USER/SYSTEM |
| `GET /api/v1/agent/conversations/{conversation_id}/state` | 仅会话所有者；Redis 丢失时从 MySQL 快照恢复 | 需扩展 | Graph 恢复使用，不注册为模型工具 |
| `PUT /api/v1/agent/conversations/{conversation_id}/state` | 仅活动会话；保存短期结构化状态 | 需扩展 | Graph 节点固定调用；写入前校验状态 Schema 和大小上限 |
| `POST /api/v1/agent/conversations/{conversation_id}/snapshot` | 仅活动会话；保存 MySQL 快照 | 需扩展 | 在任务切换、等待确认和结束前由运行时固定调用 |
| `POST /api/v1/agent/conversations/{conversation_id}/complete` | 仅活动会话；完成会话并清理 Redis 状态 | 需扩展 | 仅编排终止节点调用；模型输出不能直接触发 |

## 6. 采购查询、履历与推荐接口

| 方法与路径 | 当前权限/语义 | 分类 | Agent 使用规则 |
|---|---|---|---|
| `GET /api/v1/requirements` | 后端按本人、当前处理人、楼宇或管理员范围过滤 | 只读可用 | 参数白名单、分页和最大返回量；不得用提示词扩大 `view` 权限 |
| `GET /api/v1/requirements/{requirement_id}` | 后端校验采购单可见性；银行账号按角色脱敏 | 只读可用 | 首批 `get_purchase_request` 工具来源；保留后端脱敏结果 |
| `GET /api/v1/requirements/{requirement_id}/handler-candidates` | 仅申请人、当前处理人、所属楼长或管理员可见 | 只读可用 | 仅在生成待确认流转草稿时读取；不得自动选择并执行流转 |
| `GET /api/v1/requirements/{requirement_id}/timeline` | 后端校验可见性；联系方式默认脱敏 | 只读可用 | 首批 `get_purchase_timeline` 工具来源 |
| `GET /api/v1/requirements/{requirement_id}/timeline/{log_id}/contact` | 返回经授权流程记录中的明文手机号 | 禁止调用 | 不注册模型工具；如未来确需使用，必须有单独用户动作、目的说明和审计 |
| `GET /api/v1/purchase-records` | 后端按管理员、楼宇或参与关系过滤；支持有限筛选和分页 | 只读可用 | 历史采购工具来源；限制页大小、日期范围和最大总记录数 |
| `GET /api/v1/recommendations/products` | 需求人、楼长、采购员或管理员 | 只读可用 | 产品历史推荐工具来源；结果只表示历史记录，不宣称兼容性 |
| `GET /api/v1/recommendations/purchase-history` | 楼长、采购员或管理员，且采购单可见 | 只读可用 | 相似历史工具来源；保留黑名单状态和来源采购单 ID |
| `GET /api/v1/recommendations/suppliers` | 楼长、采购员或管理员，且采购单可见；过滤有效黑名单 | 只读可用 | 供应商候选工具来源；不得将候选解释为最终采购决定 |

## 7. 采购业务写入接口

以下接口均不得作为 P0 MCP 工具。后续启用时，调用链必须为：Agent 生成草稿 → 用户查看或
编辑 → 用户明确确认 → 重新读取详情和版本 → 采购后端再次校验 → 写入 → 记录审计结果。

| 方法与路径 | 当前权限/状态约束 | 分类 | 额外门禁 |
|---|---|---|---|
| `POST /api/v1/requirements` | 需求人角色、所属楼宇；创建 DRAFT | 人工写入 | 用户确认楼宇后才能创建；避免空草稿泛滥 |
| `PATCH /api/v1/requirements/{requirement_id}/applicant-fields` | 本人 DRAFT/REJECTED，或当前处理楼长在 PENDING_REVIEW；版本锁 | 人工写入 | 展示字段差异；确认后使用最新 `expected_version` |
| `POST /api/v1/requirements/{requirement_id}/submit-review` | 本人、DRAFT、字段完整；指定合法楼长；版本锁和 `action_token` | 人工写入 | 确认提交及下一处理人；禁止自动补齐未知业务字段 |
| `POST /api/v1/requirements/{requirement_id}/reject` | 当前处理楼长、所属楼宇、PENDING_REVIEW；版本锁和 `action_token` | 人工写入 | 明示驳回原因和影响；不得根据模型风险判断自动驳回 |
| `POST /api/v1/requirements/{requirement_id}/resubmit-review` | 本人、REJECTED；指定合法楼长；版本锁和 `action_token` | 人工写入 | 展示修改内容和重提对象后确认 |
| `PATCH /api/v1/requirements/{requirement_id}/review-fields` | 当前处理楼长、所属楼宇、PENDING_REVIEW；版本锁 | 人工写入 | Agent 仅生成建议草稿；价格、供应商、合同信息由用户确认 |
| `POST /api/v1/requirements/{requirement_id}/submit-purchaser` | 当前处理楼长、PENDING_REVIEW、审核字段完整；版本锁和 `action_token` | 人工写入 | 确认审核通过和采购员；不得由 Agent 自主批准 |
| `POST /api/v1/requirements/{requirement_id}/start-purchase` | 当前处理采购员、PENDING_PURCHASE；版本锁和 `action_token` | 人工写入 | 用户确认开始采购 |
| `PATCH /api/v1/requirements/{requirement_id}/purchase-fields` | 当前处理采购员、PURCHASING；版本锁；后端重算金额 | 人工写入 | 银行、税号、金额及供应商主档更新必须逐项确认 |
| `POST /api/v1/requirements/{requirement_id}/submit-warehouse` | 当前处理采购员、PURCHASING、采购字段完整；版本锁和 `action_token` | 人工写入 | 确认仓管和采购记录完整性 |
| `PATCH /api/v1/requirements/{requirement_id}/warehouse-fields` | 当前处理仓管、PENDING_WAREHOUSE；版本锁 | 人工写入 | 数量差异和备注必须展示并确认 |
| `POST /api/v1/requirements/{requirement_id}/complete` | 当前处理仓管、PENDING_WAREHOUSE、入库字段完整；版本锁和 `action_token` | 人工写入 | 完成后不可普通回退，必须二次确认 |

## 8. 供应商接口

| 方法与路径 | 当前权限/语义 | 分类 | Agent 使用规则 |
|---|---|---|---|
| `GET /api/v1/suppliers` | 已认证用户；返回摘要、税号和黑名单状态 | 只读可用 | 可作为受限搜索工具；限制关键词和分页 |
| `GET /api/v1/suppliers/{supplier_id}` | 已认证用户；采购员/管理员可见完整银行账号，其他角色仅账号脱敏；联系信息仍返回 | 需扩展 | 增加 Agent 安全投影，默认移除银行账号和联系信息后再封装 MCP |
| `POST /api/v1/suppliers` | 采购员或管理员；创建供应商；当前无 `action_token` | 需扩展 | 在增加确认令牌、幂等和审计能力前禁止 Agent 调用 |
| `POST /api/v1/suppliers/{supplier_id}/blacklist` | 所属楼长；已完成采购；供应商匹配；`action_token` 幂等 | 人工写入 | 高风险操作；展示证据、期限和影响后由用户明确确认 |
| `POST /api/v1/suppliers/{supplier_id}/blacklists/{blacklist_id}/release` | 原登记楼长或管理员；有效黑名单；`action_token` 幂等 | 人工写入 | 高风险操作；展示原原因、解除原因和影响后确认 |

## 9. 通知管理接口

| 方法与路径 | 当前权限/语义 | 分类 | Agent 使用规则 |
|---|---|---|---|
| `GET /api/v1/notifications` | 仅管理员；包含通知状态、载荷和错误信息 | 禁止调用 | 不注册模型工具；由管理页面或专用监控使用 |
| `POST /api/v1/notifications/dispatch-due` | 仅管理员；触发通知批量发送 | 禁止调用 | 仅通知 Worker 或管理员运维入口调用 |
| `POST /api/v1/notifications/{notification_id}/resend` | 仅管理员；修改失败通知并写操作日志，`action_token` 幂等 | 禁止调用 | 不允许模型触发外部通知；保留人工管理入口 |

## 10. P0 工具白名单建议

第一批 MCP 工具只从以下只读接口构建：

1. `get_current_user` → `GET /api/v1/users/me`
2. `get_purchase_request` → `GET /api/v1/requirements/{requirement_id}`
3. `get_purchase_timeline` → `GET /api/v1/requirements/{requirement_id}/timeline`
4. `search_purchase_records` → `GET /api/v1/purchase-records`
5. `recommend_products` → `GET /api/v1/recommendations/products`
6. `recommend_purchase_history` → `GET /api/v1/recommendations/purchase-history`
7. `recommend_suppliers` → `GET /api/v1/recommendations/suppliers`

`GET /api/v1/requirements`、处理人候选和供应商搜索虽然属于只读可用，但应在首批工具稳定、
完成越权和参数评测后再加入白名单。

## 11. 分类统计与待开发项

| 分类 | 操作数 |
|---|---:|
| 只读可用 | 10 |
| 需扩展 | 9 |
| 人工写入 | 14 |
| 禁止调用 | 6 |
| 合计 | 39 |

后续任务必须处理：

- `CLI-*`：会话支撑接口使用固定后端客户端，统一 HMAC、Trace、超时和错误结构。
- `MCP-002` 至 `MCP-005`：只实现 P0 白名单中的只读工具。
- 供应商详情：增加适合 Agent 的最小字段投影。
- 供应商创建：补充幂等和人工确认审计后才评估开放。
- `DEC-002`：P0 只生成、展示草稿；正式业务写入继续保持关闭，待 P1 Human-in-the-loop 范围确认。
