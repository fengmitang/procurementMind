# 数据中心设备采购智能协同 Agent 开发计划

> 版本：V1.1  
> 日期：2026-08-04  
> 现有后端仓库：`fengmitang/procurementMind`  
> 关联文档：  
> - 《数据中心设备采购智能协同 Agent 需求分析》  
> - 《数据中心设备采购智能协同 Agent 技术方案》  
> - 《数据中心设备采购智能协同 Agent 功能模块划分》  
> - 《数据中心设备采购智能协同 Agent 系统分析》

---

# 一、文档目标

本文档用于把现有采购后端扩展为一个可完整运行、可演示、可评测的采购智能协同 Agent 项目。

文档重点回答：

1. 现有后端哪些能力可以直接复用。
2. 哪些后端能力需要补充。
3. 哪些 Agent 模块需要新增。
4. 每一步具体要做什么。
5. 每一步应该如何完成。
6. 每一步完成后如何验证。
7. 整个项目最终如何串成完整链路。

---

# 二、现有后端情况

## 2.1 已经具备的能力

当前 `procurementMind` 后端已经具备以下基础能力：

### 采购业务主流程

- 创建采购草稿。
- 保存需求字段。
- 提交楼长审核。
- 驳回和重新提交。
- 楼长填写审核资料。
- 提交采购员。
- 采购员填写供应商和成交信息。
- 提交仓库。
- 仓库入库。
- 完成采购流程。

### 权限与安全

- 平台身份签名。
- HMAC-SHA256 身份校验。
- 防重放 Nonce。
- 用户、角色和楼宇权限。
- 当前处理人校验。
- 手机号和财务字段脱敏。
- 操作审计。

### 流程可靠性

- 后端状态机。
- `expected_version` 乐观锁。
- `action_token` 幂等控制。
- 状态更新和日志同事务。
- 通知 Outbox。
- 通知失败重试。

### 采购数据能力

- 采购申请详情。
- 历史采购记录。
- 流程时间线。
- 供应商主档。
- 供应商黑名单。
- 历史品牌型号推荐。
- 相似采购推荐。
- 供应商历史推荐。

### Agent 后端支撑

- 获取或创建 Agent 活动会话。
- 保存和查询对话消息。
- Redis 保存短期结构化状态。
- MySQL 保存会话状态快照。
- Redis 状态丢失后恢复。
- 完成 Agent 会话。

### 开发和测试基础

- FastAPI。
- Pydantic。
- SQLAlchemy Async。
- MySQL。
- Redis。
- Alembic。
- Pytest。
- Ruff。
- Docker Compose。
- 本地功能体验页面。
- TEST 全流程虚拟数据。

---

## 2.2 当前没有实现的能力

现有后端明确没有实现：

- 大模型调用。
- Prompt 管理。
- Agent 路由。
- LangGraph 工作流。
- RAG。
- MCP Client 和 MCP Server。
- Planner / Executor。
- 多工具动态调用。
- Review Agent。
- Agent 评测。
- Agent Trace。
- 采购复杂查询 DSL。
- 审批风险规则引擎。
- 审批异常调查。
- 真正的智能对话页面。

这些内容是本次开发的主要工作。

---

## 2.3 需要扩展的后端能力

现有接口可以支撑普通流程和简单推荐，但不足以直接支撑复杂 Agent 分析。

需要补充：

1. 受控复杂查询接口。
2. 采购风险规则接口。
3. 供应商履约统计接口。
4. 历史相似案例接口。
5. 更完整的品牌、价格、楼宇和供应商聚合统计。
6. Agent 分析结果草稿保存接口。
7. 必要的测试数据和异常数据。

---

# 三、总体开发策略

## 3.1 保留现有后端边界

现有 `app/` 继续作为采购业务后端。

它仍然是以下数据的唯一真实来源：

- 采购申请。
- 审核记录。
- 采购执行。
- 供应商。
- 黑名单。
- 入库。
- 用户权限。
- 正式业务写入。

Agent 不直接读写 MySQL 和后端 Redis。

---

## 3.2 新增独立 Agent 服务

在同一个仓库中新增独立的 Agent 服务，建议目录：

```text
procurementMind/
├─ app/                         # 已有采购业务后端
├─ agent_app/                   # 新增 Agent 服务
│  ├─ api/
│  ├─ graph/
│  ├─ agents/
│  ├─ schemas/
│  ├─ clients/
│  ├─ rag/
│  ├─ mcp/
│  ├─ memory/
│  ├─ skills/
│  ├─ observability/
│  └─ evals/
├─ knowledge/                   # 采购知识文档
├─ tests/                       # 已有后端测试
├─ tests_agent/                 # 新增 Agent 测试
├─ frontend/                    # 已有体验页面，继续扩展
└─ compose.yaml
```

P0 建议运行方式：

```text
采购后端：http://127.0.0.1:8000
Agent 服务：http://127.0.0.1:8100
MCP Server：stdio 子进程，不占独立端口
Web 前端：继续由采购后端静态挂载，或单独作为静态页面运行
```

主链路稳定后，P1/P2 可以将 MCP 改为 Streamable HTTP：

```text
MCP 服务：http://127.0.0.1:8200/mcp
```

端口可以调整，但需要固定写入配置文档。

---

## 3.3 第一版只运行一个 MCP 服务进程

需求设计中将工具分为：

- 采购数据工具。
- 产品数据工具。
- 供应商数据工具。
- 统计分析工具。

第一版不需要启动四个独立服务。

建议先实现一个标准 MCP Server，在内部按四个模块组织工具：

```text
agent_app/mcp/
├─ server.py
├─ procurement_tools.py
├─ product_tools.py
├─ supplier_tools.py
└─ analytics_tools.py
```

这样既能实际使用标准 MCP，又不会过早增加服务数量。

后续只有在工具规模和权限边界明显扩大时，再拆成多个 MCP Server。

## 3.4 Web 优先与平台适配策略

项目第一版只要求完成网页版：

- 复用现有 `frontend/` 体验页面，增加智能协同功能。
- 普通采购业务请求继续调用采购后端。
- Agent 问答、复杂查询和风险分析调用独立 Agent 服务。
- 开发环境继续使用现有 TEST 用户和角色切换。
- 正式 Web 登录、Session 和 BFF 放到 P1。
- 飞书身份、消息和卡片适配放到 P2。
- 飞书适配层只转换输入输出，不复制 Agent 工作流。
- 飞书未完成不影响项目交付和简历演示。

---

# 四、开发阶段总览

| 阶段 | 目标 | 主要产物 |
|---|---|---|
| 0 | 固化现有后端基线 | 测试结果、接口清单、开发分支 |
| 1 | 建立 Agent 服务骨架 | Agent API、配置、健康检查 |
| 2 | 打通身份和后端调用 | 后端签名客户端、用户上下文 |
| 3 | 补充后端分析接口 | 查询 DSL、风险和统计接口 |
| 4 | 建立标准 MCP 工具层 | MCP Server、工具 Schema |
| 5 | 建立采购知识库 | 文档、索引、RAG 检索 |
| 6 | 接入会话记忆 | 消息、状态、快照、恢复 |
| 7 | 建立 LangGraph 主工作流 | State、节点、条件分支 |
| 8 | 完成 Router 和 Skills | 路由、复合任务、规则加载 |
| 9 | 完成知识问答 | 文档问答、业务混合问答 |
| 10 | 完成复杂查询分析 | Planner、查询 DSL、多工具调用 |
| 11 | 完成审批风险调查 | 风险规则、证据补查、摘要 |
| 12 | 完成 Review Agent | 证据核验、打回重查 |
| 13 | 完成人工确认 | 意见草稿、暂停和继续 |
| 14 | 完成 Web 主入口 | 采购工作台、对话、风险、Trace 页面 |
| 15 | 完成 Trace 和评测 | 调用链、测试集、回归测试 |
| 16 | 完成容错和部署 | 重试、降级、Compose |
| 17 | 完成最终演示和文档 | 演示数据、验收脚本、README |

---

# 五、阶段 0：固化现有后端基线

## 5.1 目标

确保开始开发 Agent 前，现有后端是稳定、可运行、可回退的。

## 5.2 具体步骤

### 步骤 1：创建开发分支

建议：

```text
feature/intelligent-agent
```

所有 Agent 开发先在该分支进行，不直接修改 `main`。

### 步骤 2：按现有文档启动项目

执行：

1. 配置 `.env` 和 `.env.docker`。
2. 启动 MySQL 和 Redis。
3. 执行数据库迁移。
4. 执行 `seed_demo_data.py`。
5. 启动 FastAPI。
6. 打开 `/demo/`。

### 步骤 3：跑完整后端检查

执行：

- Pytest。
- Ruff check。
- Ruff format check。
- `/health`。
- `/ready`。
- Swagger 页面。
- 全流程角色切换体验。

### 步骤 4：保存接口基线

保存一份当前：

```text
GET /openapi.json
```

文件建议放到：

```text
docs/baseline/openapi-backend-v0.1.json
```

### 步骤 5：建立接口复用清单

将当前接口分为：

- Agent 可以直接调用。
- 需要后端扩展。
- 只允许人工调用。
- 不允许 Agent 调用。

## 5.3 完成标准

- 现有测试全部通过。
- TEST 数据可以完整跑通采购流程。
- 当前 OpenAPI 已保存。
- 明确记录当前提交 SHA。
- Agent 开发出现问题时可以回退到稳定基线。

---

# 六、阶段 1：建立 Agent 服务骨架

## 6.1 目标

创建一个独立 FastAPI Agent 服务，但暂时不实现智能逻辑。

## 6.2 具体步骤

### 步骤 1：创建目录

新增：

```text
agent_app/
├─ __init__.py
├─ main.py
├─ core/
│  ├─ config.py
│  ├─ logging.py
│  └─ exceptions.py
├─ api/
│  ├─ router.py
│  └─ routes/
│     ├─ health.py
│     ├─ chat.py
│     ├─ tasks.py
│     └─ traces.py
└─ schemas/
   ├─ chat.py
   ├─ task.py
   └─ common.py
```

### 步骤 2：添加 Agent 依赖

在项目依赖中增加 Agent 可选依赖组，至少包括：

- LangGraph。
- LangChain Core。
- 大模型 Provider SDK。
- MCP Python SDK。
- Chroma。
- Embedding 相关依赖。
- 结构化日志。
- 测试依赖。

避免一次性引入所有可选框架。

### 步骤 3：建立配置

配置项至少包括：

- Agent 服务端口。
- 采购后端地址。
- 身份网关密钥。
- 主模型。
- 备用模型。
- Embedding 模型。
- Chroma 存储目录。
- 最大工具调用数。
- 最大执行步骤数。
- 单任务超时。
- RAG Top-K。
- 是否启用 Review。
- 是否启用 Trace。

### 步骤 4：建立健康检查

实现：

```text
GET /health
GET /ready
```

`/ready` 需要检查：

- 模型配置是否存在。
- 采购后端是否可访问。
- MCP 是否可连接。
- 向量库是否可访问。

第一阶段可以只检查 Agent 进程和采购后端。

### 步骤 5：建立聊天接口占位

实现：

```text
POST /api/v1/chat
```

第一版先返回固定响应，并生成：

- `trace_id`
- `task_id`
- `conversation_id`

## 6.3 完成标准

- Agent 服务可以独立启动。
- `/health` 和 `/ready` 正常。
- 能调用固定聊天接口。
- Agent 服务日志与原后端日志分开。
- Agent 服务异常不会影响采购后端启动。

---

# 七、阶段 2：打通身份和后端调用

## 7.1 目标

让 Agent 服务以可信中间层身份调用现有采购后端。

## 7.2 具体步骤

### 步骤 1：实现采购后端客户端

新增：

```text
agent_app/clients/procurement_backend.py
```

封装：

- 基础 URL。
- 超时。
- HMAC 签名。
- Nonce。
- 时间戳。
- 请求重试。
- 统一响应解析。
- 错误码转换。
- `X-Request-Id` 透传。

### 步骤 2：建立 Web 用户上下文

P0 开发环境：

- 复用现有 `TEST_PLATFORM` 身份和角色切换。
- Web 页面只提交测试用户标识，不保存签名密钥。
- Agent 服务以服务端身份调用采购后端。

P1 正式 Web 环境：

- 增加登录和服务端 Session。
- Web BFF 根据 Session 解析平台用户 ID。
- BFF 或 Agent 服务在服务端生成采购后端签名。
- 浏览器只持有安全 Cookie，不接触 `IDENTITY_GATEWAY_SECRET`。

Agent 服务不能接收客户端自报的：

- 员工编号。
- 角色。
- 姓名。
- 手机号。
- 楼宇权限。

### 步骤 3：调用当前用户接口

无论开发 TEST 身份还是正式 Web Session，每个新会话首先调用：

```text
GET /api/v1/users/me
```

得到：

- employee_id。
- 角色。
- 楼宇。
- 当前平台身份。

将结果写入 Agent 任务状态。

### 步骤 4：实现统一业务错误处理

需要识别后端错误码，例如：

- 权限不足。
- 采购单不存在。
- 并发版本冲突。
- 重复操作。
- 状态不允许。
- Redis 或数据库不可用。

Agent 返回面向用户的说明，但保留原始错误码进入 Trace。

### 步骤 5：建立集成测试

至少测试：

- Web TEST 身份切换。
- 浏览器不包含网关密钥。
- 无 Session 或无效 Session。
- 需求人身份。
- 楼长身份。
- 采购员身份。
- 仓管身份。
- 管理员身份。
- 签名错误。
- Nonce 重放。
- 越权访问。

## 7.3 完成标准

- Agent 服务能安全调用 `/users/me`。
- 能调用采购详情和历史查询接口。
- `X-Request-Id` 在 Agent、MCP 和采购后端中保持一致。
- 用户不能通过对话伪造角色。
- 越权数据不会传给模型。

---

# 八、阶段 3：补充后端分析接口

## 8.1 目标

补齐复杂查询和审批风险分析所需的确定性数据能力。

## 8.2 原则

- 统计和风险数字由后端计算。
- Agent 不直接查询数据库。
- Agent 不直接执行 SQL。
- 新接口继续使用现有身份、角色和楼宇权限。
- 新接口统一返回 `trace_id`。
- 新查询默认只读。

---

## 8.3 新增复杂查询 DSL

### 建议接口

```text
POST /api/v1/analytics/purchase-query
```

### 请求结构

至少支持：

- `created_from`
- `created_to`
- `building_ids`
- `device_professions`
- `device_name`
- `brands`
- `models`
- `supplier_ids`
- `status`
- `min_unit_price`
- `max_unit_price`
- `min_total_price`
- `max_total_price`
- `exclude_blacklisted`
- `exclude_delayed_suppliers`
- `group_by`
- `aggregations`
- `sort_by`
- `sort_order`
- `page`
- `page_size`

### 实现步骤

1. 建立 Pydantic 查询 Schema。
2. 为每个字段建立白名单。
3. 在 Repository 层组合 SQLAlchemy 条件。
4. 在 Service 层执行权限过滤。
5. 支持分页。
6. 支持有限的聚合。
7. 限制最大查询范围。
8. 限制最大返回行数。
9. 增加查询超时。
10. 返回实际使用的查询条件和统计口径。

### 第一版聚合

只实现：

- count。
- average unit price。
- median unit price。
- total amount。
- group by brand。
- group by building。
- group by supplier。
- group by device name。

不要第一版就做任意组合表达式。

---

## 8.4 新增风险检查接口

### 建议接口

```text
GET /api/v1/requirements/{requirement_id}/risk-signals
```

### 第一版风险规则

#### 规则 1：重复申请

检查：

- 相同楼宇。
- 相同或相似设备名称。
- 最近 30 天或配置周期。
- 状态未取消。

#### 规则 2：价格异常

比较：

- 当前预计或实际单价。
- 近半年同类设备历史中位价。
- 偏差比例。

#### 规则 3：数量异常

比较：

- 当前数量。
- 同类设备历史平均数量和区间。

#### 规则 4：黑名单供应商

检查当前拟选或实际供应商是否处于有效黑名单。

#### 规则 5：供应商延期

使用：

- 楼长填写的 expected_arrival_date。
- 仓库 received_at。
- 判断是否延期。

#### 规则 6：长期未入库

检查：

- 已提交仓库或已采购。
- 超过设定时间仍未完成入库。

#### 规则 7：相似历史申请

返回相似采购申请编号和基本信息。

### 返回结构

每项风险返回：

- `risk_code`
- `risk_level`
- `matched`
- `facts`
- `metrics`
- `related_record_ids`
- `threshold`
- `time_range`

### 实现步骤

1. 新建风险 Schema。
2. 新建 `RiskAnalysisService`。
3. 将每条规则实现为独立函数或规则类。
4. 规则只返回事实，不生成长文本。
5. 建立统一规则执行器。
6. 对不同角色过滤可见字段。
7. 增加单元测试。
8. 用虚拟数据覆盖命中和不命中情况。

---

## 8.5 新增供应商履约统计

### 建议接口

```text
GET /api/v1/suppliers/{supplier_id}/performance
```

### 返回内容

- 历史采购次数。
- 最近合作时间。
- 平均交付周期。
- 延期次数。
- 延期率。
- 入库数量异常次数。
- 当前黑名单状态。
- 黑名单历史数量。
- 涉及楼宇。

### 实现步骤

1. 从采购执行、审核预计到货时间和入库时间中汇总。
2. 明确统计时间范围。
3. 处理没有 expected_arrival_date 的记录。
4. 所有比例同时返回分子和分母。
5. 做权限和脱敏。

---

## 8.6 新增相似案例接口

### 建议接口

```text
GET /api/v1/requirements/{requirement_id}/similar-cases
```

### 第一版相似标准

优先匹配：

1. 设备专业。
2. 设备名称。
3. 品牌。
4. 型号。
5. 楼宇。
6. 数量区间。
7. 驳回原因。
8. 风险类型。

第一版可先使用规则相似度，不急于在业务后端中做向量检索。

---

## 8.7 新增分析草稿保存接口

### 建议接口

```text
POST /api/v1/requirements/{requirement_id}/analysis-drafts
```

用途：

- 保存审批意见草稿。
- 保存风险分析报告草稿。
- 记录 Agent 生成时间。
- 记录生成 Trace。
- 记录用户最终确认版本。

第一版也可以先不新增表，只在 Agent 服务中保存草稿；但正式写入审批备注时必须继续调用现有审批接口。

## 8.8 完成标准

- 复杂查询结果与直接数据库标准答案一致。
- 每条风险规则有单元测试。
- 越权查询被后端拒绝。
- Agent 无需直接访问数据库即可得到所需数据。
- OpenAPI 文档已更新。

---

# 九、阶段 4：建立标准 MCP 工具层

## 9.1 目标

通过标准 MCP 将后端能力提供给 Agent。

## 9.2 具体步骤

### 步骤 1：建立 MCP Server

新增：

```text
agent_app/mcp/server.py
```

第一版使用一个 MCP Server 进程。

### 步骤 2：建立采购工具

建议工具：

- `get_current_user`
- `get_requirement_detail`
- `list_requirements`
- `query_purchase_records`
- `get_requirement_timeline`
- `get_similar_cases`

### 步骤 3：建立产品工具

建议工具：

- `search_historical_products`
- `get_product_recommendations`
- `get_purchase_history_recommendations`

第一版没有可靠兼容性数据时，不提供“确认兼容”工具。

### 步骤 4：建立供应商工具

建议工具：

- `search_suppliers`
- `get_supplier_detail`
- `get_supplier_blacklist_status`
- `get_supplier_performance`
- `get_supplier_recommendations`

### 步骤 5：建立分析工具

建议工具：

- `query_procurement_analytics`
- `get_requirement_risk_signals`
- `compare_brand_prices`
- `check_duplicate_requests`
- `summarize_supplier_performance`

其中精确计算仍由后端完成。

### 步骤 6：统一工具返回

所有工具返回：

- `success`
- `code`
- `data`
- `source`
- `trace_id`
- `partial`
- `warnings`

### 步骤 7：限制工具权限

MCP 工具调用时必须携带：

- 当前用户平台身份。
- 当前 Trace ID。
- 当前角色上下文。

但 MCP Server 不能只相信 Agent 传来的角色，仍要让采购后端重新校验。

### 步骤 8：建立 MCP 测试

每个工具测试：

- 正常结果。
- 参数错误。
- 无权限。
- 后端超时。
- 空结果。
- 部分失败。
- Trace 透传。

## 9.3 完成标准

- Agent 可以通过 MCP 而不是直接写 HTTP 业务调用。
- MCP 工具使用标准 Schema。
- 工具清单可以被 Agent 动态发现。
- 工具失败时返回结构化错误。
- 所有工具默认只读。

---

# 十、阶段 5：建立采购知识库和 RAG

## 10.1 目标

完成采购知识问答的真实知识来源。

## 10.2 知识文档准备

建议建立：

```text
knowledge/source/
├─ 采购流程说明.md
├─ 角色职责说明.md
├─ 设备采购字段要求.md
├─ 黑名单规则.md
├─ 采购状态说明.md
├─ 系统使用说明.md
├─ 审批常见问题.md
└─ 历史案例/
```

注意：

- 项目整理出的规则应标记为“项目业务规则”。
- 不要虚构为公司正式制度。
- 真实内部制度只有在允许使用时才加入。

---

## 10.3 文档 Metadata

每份文档至少记录：

- `document_id`
- `title`
- `document_type`
- `version`
- `effective_at`
- `expired_at`
- `allowed_roles`
- `device_professions`
- `chapter`
- `source_path`

---

## 10.4 文档导入流程

### 步骤 1：解析

支持 Markdown 和项目已有文档。

PDF、Word 可以放到 P1。

### 步骤 2：切分

按：

- 标题。
- 条款。
- 流程步骤。
- 问答单元。

避免只按固定字符数切分。

### 步骤 3：生成向量

使用统一 Embedding 模型。

### 步骤 4：写入 Chroma

第一版 Chroma 使用持久化目录。

### 步骤 5：保存原文引用

每个 Chunk 保留：

- 文档。
- 版本。
- 章节。
- 原文位置。

---

## 10.5 检索流程

P0：

```text
问题
→ 权限和 Metadata 过滤
→ 向量检索
→ Top-K
→ 去重
→ 返回片段
```

P1：

```text
问题
→ 查询改写
→ 向量检索
+ 关键词检索
→ 合并
→ Rerank
→ Top-K
```

---

## 10.6 建立 RAG 测试集

至少准备 30 至 50 个问题，覆盖：

- 角色职责。
- 设备字段。
- 黑名单规则。
- 流程下一步。
- 提交要求。
- 状态含义。
- 文档版本冲突。
- 无答案问题。
- 越权文档问题。

## 10.7 完成标准

- 能检索正确文档。
- 答案能引用文档名称和章节。
- 没有依据时不回答内部规则。
- 过期文档不会被默认使用。
- 不同角色能获得不同文档范围。

---

# 十一、阶段 6：接入 Agent 会话记忆

## 11.1 目标

直接复用现有会话、消息、Redis 状态和 MySQL 快照能力。

## 11.2 具体步骤

### 步骤 1：创建或获取活动会话

每次开始业务动作时调用：

```text
POST /api/v1/agent/conversations/active
```

`current_action` 可使用：

- `KNOWLEDGE_QA`
- `COMPLEX_QUERY`
- `RISK_ANALYSIS`
- `FORM_PREFILL`

### 步骤 2：写入用户消息

调用：

```text
POST /api/v1/agent/conversations/{id}/messages
```

使用外部消息 ID 保证幂等。

### 步骤 3：读取已有状态

调用：

```text
GET /api/v1/agent/conversations/{id}/state
```

### 步骤 4：定义 Agent 状态映射

复用当前 `collected_data`，内部保存：

```text
collected_data:
  task_type
  filters
  current_requirement_id
  current_plan
  completed_steps
  result_summary
  excluded_suppliers
  evidence_refs
  review_status
  trace_id
```

### 步骤 5：保存状态

每完成关键节点后调用：

```text
PUT /api/v1/agent/conversations/{id}/state
```

### 步骤 6：保存快照

以下时机保存 MySQL 快照：

- 计划生成后。
- 多工具查询完成后。
- 等待人工确认前。
- 任务完成前。
- 发生可恢复错误时。

### 步骤 7：测试恢复

测试：

1. 创建会话。
2. 保存状态。
3. 删除 Redis Key 或等待模拟失效。
4. 调用状态读取。
5. 验证从 MySQL 恢复。

## 11.3 完成标准

- 连续追问可以继承筛选条件。
- 新任务不会错误继承旧任务。
- Agent 服务重启后可以恢复关键状态。
- 消息写入具有幂等性。
- 所有会话仍受后端用户权限约束。

---

# 十二、阶段 7：建立 LangGraph 主工作流

## 12.1 目标

将 Agent 处理过程组织成可检查、可分支、可恢复的状态图。

## 12.2 定义 Graph State

至少包含：

- `trace_id`
- `task_id`
- `conversation_id`
- `user_context`
- `user_query`
- `page_context`
- `task_type`
- `subtasks`
- `skills`
- `query_filters`
- `plan`
- `completed_steps`
- `tool_results`
- `rag_results`
- `evidence`
- `draft_answer`
- `review_result`
- `retry_count`
- `errors`
- `awaiting_confirmation`
- `final_answer`

---

## 12.3 建立节点

建议第一版节点：

1. `load_user_context`
2. `load_conversation_state`
3. `route_request`
4. `load_skills`
5. `build_plan`
6. `run_knowledge_search`
7. `run_mcp_tools`
8. `check_sufficiency`
9. `compose_answer`
10. `review_answer`
11. `handle_review_failure`
12. `wait_for_confirmation`
13. `save_state`
14. `finalize`
15. `handle_error`

---

## 12.4 建立条件分支

### 知识问题

```text
Router
→ Knowledge Search
→ Compose
→ Review
→ Finalize
```

### 业务数据问题

```text
Router
→ MCP Tools
→ Compose
→ Review
→ Finalize
```

### 混合问题

```text
Router
→ RAG + MCP
→ Merge Evidence
→ Compose
→ Review
→ Finalize
```

### 复杂查询

```text
Router
→ Planner
→ MCP Executor
→ Sufficiency Check
→ 继续查询或 Compose
→ Review
→ Finalize
```

### 风险分析

```text
Router
→ 获取风险信号
→ Planner
→ 并行补查
→ RAG
→ Compose Risk Summary
→ Review
→ Finalize
```

---

## 12.5 增加边界

配置：

- 最大计划步骤。
- 最大工具调用次数。
- 最大 Review 打回次数。
- 最大循环次数。
- 单工具超时。
- 总任务超时。
- Token 预算。

## 12.6 完成标准

- 三条核心链路都能通过 Graph 跑通。
- 每个节点都记录 Trace。
- Review 可以打回前一节点。
- 达到最大循环次数时安全停止。
- 工作流异常不会进入无限循环。

---

# 十三、阶段 8：完成 Router 和 Skills

## 13.1 Router Agent

### 分类范围

- `KNOWLEDGE`
- `BUSINESS_QUERY`
- `MIXED_QA`
- `COMPLEX_ANALYSIS`
- `RISK_ANALYSIS`
- `FORM_PREFILL`
- `COMPOSITE`

### 输出结构

- 任务类型。
- 置信度。
- 子任务。
- 是否需要澄清。
- 需要的工具域。
- 是否涉及写入。

### 具体步骤

1. 定义 Pydantic Router Schema。
2. 编写 Router System Prompt。
3. 加入少量规则优先判断。
4. 模型处理模糊和复合问题。
5. 低置信度时只问一次必要问题。
6. 建立 Router 测试集。

---

## 13.2 Skills

建立：

```text
agent_app/skills/
├─ knowledge.md
├─ query.md
├─ recommendation.md
├─ risk.md
└─ review.md
```

每个 Skill 写明：

- 允许做什么。
- 允许调用什么工具。
- 禁止做什么。
- 输出必须包含什么。
- 数据不足时怎么处理。
- 示例。

### 加载步骤

1. Router 确定任务。
2. Skill Loader 读取对应文件。
3. 记录文件版本或 Hash。
4. 注入对应 Agent 上下文。
5. Trace 中记录使用版本。

## 13.3 完成标准

- Router 能稳定区分三条核心主线。
- 复合任务可以拆成至少两个子任务。
- 更新 Skill 后无需修改工作流代码。
- Skills 不承担真正权限校验。

---

# 十四、阶段 9：完成采购知识与业务问答

## 14.1 场景一：纯知识问题

示例：

> 黑名单持续时间规则是什么？

流程：

1. Router 判断为 KNOWLEDGE。
2. 加载 Knowledge Skill。
3. RAG 检索。
4. 生成带引用答案。
5. Review 检查是否忠于文档。
6. 保存消息和状态。

---

## 14.2 场景二：具体业务问题

示例：

> 当前采购单下一步由谁处理？

流程：

1. Router 判断为 BUSINESS_QUERY。
2. MCP 查询采购单详情。
3. 获取状态和当前处理人。
4. 返回实时结果。
5. 不需要 RAG 时不强行检索。

---

## 14.3 场景三：规则与实时数据混合

示例：

> 为什么这张申请不能提交？

流程：

1. 查询采购单。
2. 获取 `missing_fields` 和状态。
3. RAG 检索设备字段要求。
4. 对照规则和实际数据。
5. 返回具体原因和引用。
6. Review 检查字段与制度是否对应。

---

## 14.4 完成标准

- 三种问题能够正确分流。
- 具体采购单问题使用实时数据。
- 制度类问题提供引用。
- 检索不到规则时不编造。
- 用户无权查看的采购单不进入模型上下文。

---

# 十五、阶段 10：完成复杂查询与多约束分析

## 15.1 自然语言转查询 DSL

### 具体步骤

1. 定义 Query DSL Schema。
2. 从用户问题提取查询条件。
3. 将相对时间转为明确日期。
4. 将自然语言楼宇、设备和状态映射到合法值。
5. 校验金额和范围。
6. 对冲突条件进行一次澄清。
7. 调用 MCP 分析工具。

### 示例

用户：

> 查过去半年一号楼和二号楼采购的服务器硬盘，排除黑名单供应商，只看单价超过 3000 元的，并按品牌统计平均价格。

Agent 输出 DSL：

```text
created_from
created_to
building_ids
device_name
min_unit_price
exclude_blacklisted
group_by = brand
aggregations = average_unit_price
```

---

## 15.2 Planner / Executor

### Planner 步骤

1. 判断是否一次查询可以完成。
2. 如果不能，生成多步计划。
3. 标记依赖和可并行步骤。
4. 设置终止条件。

### Executor 步骤

1. 调用查询工具。
2. 调用供应商工具。
3. 调用统计工具。
4. 保存中间结果。
5. 判断是否需要补查。
6. 生成结构化结果。

---

## 15.3 并行调用

可并行：

- 黑名单查询。
- 履约统计。
- 历史价格。
- 相似案例。
- 制度检索。

使用 `asyncio.gather`，但要支持部分失败。

---

## 15.4 连续追问

用户：

> 再排除有延期记录的供应商。

处理：

1. 从会话状态读取原有条件。
2. 增加 `exclude_delayed_suppliers=true`。
3. 只重新执行受影响的查询。
4. 更新状态和结果。

---

## 15.5 多约束候选方案

第一版支持：

- 预算。
- 历史品牌。
- 白名单。
- 黑名单。
- 延期。
- 历史价格。

兼容性只有在存在可靠结构化数据时才加入。

## 15.6 完成标准

- 查询条件不会遗漏。
- 结果与后端标准答案一致。
- 连续追问可以正确继承条件。
- Agent 不生成任意 SQL。
- 结果以表格和总结共同展示。
- 候选方案不使用“唯一最优”表述。

---

# 十六、阶段 11：完成审批辅助与异常调查

## 16.1 触发方式

在采购单详情或审批页面增加：

```text
生成风险摘要
```

按钮。

## 16.2 完整步骤

1. 获取采购单详情。
2. 调用风险信号接口。
3. 读取后端命中的确定性风险。
4. Planner 根据风险生成补查计划。
5. 并行查询：
   - 历史价格。
   - 相似申请。
   - 供应商黑名单。
   - 供应商履约。
   - 入库异常。
   - 相关规则。
6. 将事实、规则和推测分开。
7. 生成结构化风险摘要。
8. Review Agent 逐项核验。
9. 删除无依据项或标记信息不足。
10. 展示给楼长。

---

## 16.3 风险摘要格式

每项包含：

- 风险名称。
- 风险等级。
- 是否为后端规则命中。
- 事实。
- 指标。
- 数据来源。
- 规则来源。
- 可能原因。
- 信息缺口。
- 人工核实建议。

---

## 16.4 完成标准

- 风险数字由后端返回。
- Agent 只调查和解释。
- 每条风险可追溯。
- 无风险时返回“当前规则范围内未发现明显风险”。
- Agent 不输出自动审批结论。
- 部分服务失败时明确分析范围。

---

# 十七、阶段 12：完成 Review Agent

## 17.1 目标

防止最终回答存在无依据数据、遗漏条件和越权结论。

## 17.2 审查分为两层

### 程序审查

检查：

- 数字是否在工具结果中。
- 产品和供应商 ID 是否存在。
- 用户条件是否全部进入 DSL。
- 引用文档是否在 RAG 结果中。
- 是否包含无权限字段。
- 是否有审批决定类越权内容。

### LLM 审查

检查：

- 是否把推测写成事实。
- 是否遗漏重要限制。
- 解释是否与证据一致。
- 结论是否过强。
- 是否清楚表达信息不足。

---

## 17.3 Review 输出

- `PASS`
- `REQUERY`
- `REWRITE`
- `REMOVE_UNSUPPORTED`
- `ESCALATE_TO_HUMAN`

并返回具体原因。

## 17.4 打回流程

- 缺工具证据：回到工具执行。
- 缺文档证据：回到 RAG。
- 表达过强：回到答案生成。
- 权限问题：直接终止。
- 达到最大打回次数：返回人工处理。

## 17.5 完成标准

- Review 能看到原问题、计划、工具结果和 RAG 片段。
- 不只审查最终文字。
- 无依据数字不能进入最终回答。
- Review 自身结果有结构化记录。

---

# 十八、阶段 13：完成人工确认

## 18.1 第一版功能

实现：

- 审批意见草稿。
- 补充材料请求草稿。
- 风险分析报告草稿。
- 用户确认后保存。

## 18.2 具体步骤

1. Agent 生成草稿。
2. LangGraph 进入暂停节点。
3. 返回 `awaiting_confirmation=true`。
4. 前端展示草稿编辑框。
5. 用户修改或拒绝。
6. 用户确认时提交确认令牌。
7. 后端重新查询采购单状态和版本。
8. 后端重新校验权限。
9. 使用幂等令牌写入。
10. 记录确认前和确认后的文本。

## 18.3 完成标准

- 未确认不写入。
- 页面刷新不会重复写入。
- 状态变化后旧草稿不能直接保存。
- 确认操作有审计日志。

---

# 十九、阶段 14：完成 Web 主入口

## 19.1 开发策略

第一版以网页版作为正式演示入口。

继续复用当前 `frontend/` 的开发体验页面，不必第一版重写成复杂前端框架。普通采购流程继续调用采购后端，智能功能调用独立 Agent 服务。

## 19.2 新增智能协同页签

增加：

```text
06 智能协同
```

页面包含：

- 对话区域。
- 当前用户和角色。
- 当前任务状态。
- 引用来源。
- 查询结果表格。
- 风险摘要卡片。
- Trace 查看入口。

---

## 19.3 采购详情页扩展

在楼长和采购员有权限的采购单详情中增加：

- 生成风险摘要。
- 查看相似案例。
- 生成审批意见草稿。
- 查看 Agent 执行过程。

---

## 19.4 知识库管理页面

P1 增加：

- 上传文档。
- 文档版本。
- 权限。
- 索引状态。
- 测试检索。

---

## 19.5 P1 正式 Web 身份

核心 Agent 链路完成后，再增加：

- Web 登录页面。
- 服务端 Session。
- BFF 或 Web 身份网关。
- Cookie、CSRF 和会话过期处理。
- `WEB` 平台身份与后端员工映射。

该步骤不阻塞 P0 Agent 开发。

## 19.6 完成标准

- TEST 角色可以体验全部 Agent 链路。
- 复杂查询结果不是只有聊天文字。
- 风险摘要可以从采购详情页触发。
- 用户可以看到引用和部分执行过程。
- Agent 页面不暴露身份签名密钥。
- 不接入飞书时，Web 端仍能独立完成全部第一版验收。

---

# 二十、阶段 15：Trace、可观测性和评测

## 20.1 Trace

每次请求生成一个 Trace ID。

需要记录：

- 用户问题。
- 用户角色。
- 路由结果。
- Skill 版本。
- 查询计划。
- RAG 结果。
- MCP 工具调用。
- 参数。
- 结果。
- 错误。
- 模型调用。
- Token。
- 耗时。
- Review。
- 最终结果。
- 用户反馈。

第一版可以使用：

- 结构化 JSON 日志。
- MySQL Trace 表。
- 简单 Trace 页面。

P1 接入 Langfuse。

---

## 20.2 自动评测集

建立：

```text
agent_app/evals/datasets/
├─ router.jsonl
├─ rag.jsonl
├─ tool_calling.jsonl
├─ complex_query.jsonl
├─ risk_analysis.jsonl
└─ end_to_end.jsonl
```

### Router 评测

- 分类正确率。
- 复合任务识别率。
- 子任务拆分正确率。

### RAG 评测

- Recall@K。
- 引用正确率。
- 忠实度。
- 过期文档误用率。

### Tool 评测

- 工具选择。
- 参数。
- 权限。
- 结果完整性。

### 复杂查询评测

- 条件完整率。
- SQL 标准答案一致性。
- 连续追问上下文继承。

### 风险评测

- 风险召回。
- 错误风险。
- 证据覆盖。
- 是否越权给出审批结论。

---

## 20.3 回归测试

以下内容变化时运行固定评测：

- Prompt。
- Skill。
- 模型。
- Embedding。
- 文档切分。
- Rerank。
- 工具说明。
- 工作流节点。
- 风险阈值。

## 20.4 完成标准

- 可以一条命令运行核心评测。
- 可以查看失败样例。
- 能比较两个版本的差异。
- Trace 可以定位到具体失败节点。

---

# 二十一、阶段 16：容错、安全和部署

## 21.1 超时和重试

为以下调用设置独立超时：

- 模型。
- RAG。
- MCP。
- 采购后端。
- 单个统计查询。

使用有限重试，不无限重试。

---

## 21.2 熔断和降级

### MCP 服务失败

返回部分结果，并说明缺失范围。

### RAG 失败

仅回答实时业务数据，不生成制度结论。

### 主模型失败

切换备用模型。

### Review 失败

返回初步结果时必须标记未经完整审查，或转人工。

---

## 21.3 Prompt Injection 防护

- 工具权限由代码控制。
- 用户不能通过 Prompt 开启隐藏工具。
- RAG 文档中的指令不能覆盖系统规则。
- 外部文档标记信任级别。
- 写入只走固定 Human-in-the-loop 流程。
- 任何越权数据都不能先传入模型再删除。

---

## 21.4 Docker Compose 扩展

最终 P0 Compose 至少包含：

- MySQL。
- Redis。
- 采购后端。
- Agent 服务。
- Chroma 持久化目录。
- Web 前端资源。

MCP P0 使用 stdio，由 Agent 容器或进程启动，不单独暴露端口。

P1/P2 可增加：

- 独立 Streamable HTTP MCP 服务。
- Web BFF。
- 飞书适配服务。

P1 可加入：

- Langfuse。
- 单独数据库。
- 前端服务。

---

## 21.5 完成标准

- 一条命令启动全部核心服务。
- 每个服务有健康检查。
- 配置和密钥不进入仓库。
- 工具失败不会导致 Agent 编造。
- Agent 服务停止不影响采购核心流程。

---

# 二十二、阶段 17：最终演示与交付

## 22.1 扩充测试数据

在 `seed_demo_data.py` 中补充：

- 正常历史采购。
- 价格异常采购。
- 重复申请。
- 数量异常。
- 黑名单供应商。
- 延期供应商。
- 未入库记录。
- 多楼宇采购。
- 多品牌采购。
- 多轮驳回案例。

所有新增测试数据继续使用 `TEST` 标记，支持重复重置。

---

## 22.2 三条核心演示

### 演示一：知识与业务混合问答

输入：

> 为什么当前服务器硬盘申请不能提交？

展示：

- 采购单实时字段。
- 缺失项。
- 对应规则。
- 文档引用。
- Review 结果。

### 演示二：自然语言复杂查询

输入：

> 查询过去半年一号楼和二号楼采购的服务器硬盘，排除黑名单供应商，只看单价超过 3000 元的，并按品牌统计平均价格。

继续输入：

> 再排除有延期记录的供应商。

展示：

- 查询计划。
- MCP 调用。
- 结构化结果。
- 连续记忆。
- Trace。

### 演示三：审批风险调查

楼长打开一张异常采购单。

展示：

- 后端风险信号。
- Agent 补充调查。
- 制度和历史案例。
- Review 审查。
- 风险摘要。
- 审批意见草稿。
- 人工确认。

---

## 22.3 最终文档

需要补齐：

- 项目 README。
- 本地启动指南。
- Agent 架构说明。
- MCP 工具清单。
- RAG 文档规范。
- 评测说明。
- 演示脚本。
- 常见故障。
- 简历项目说明。
- 面试问答准备。

---


## 22.4 P2 可选阶段：飞书接入

只有在网页版、Agent 主链路、Trace 和评测稳定后再开始。

具体步骤：

1. 创建飞书应用并配置事件订阅。
2. 建立飞书 `open_id` 与后端平台身份映射。
3. 实现飞书消息接收和签名校验。
4. 将消息转换为统一 `POST /api/v1/chat` 请求。
5. 将普通回答、表格、风险摘要转换为飞书卡片。
6. 将卡片按钮回调映射到 Human-in-the-loop 确认接口。
7. 复用现有 Agent 会话和 Trace，不建立另一套 Agent。
8. 增加飞书入口集成测试和故障降级。

完成标准：

- Web 与飞书调用同一 Agent 工作流。
- 飞书适配故障不影响 Web 和采购后端。
- 飞书接入不引入新的业务权限来源。

---
# 二十三、最小可用版本开发顺序

时间不足时，只完成以下 P0 链路：

## P0-1

- Agent 服务骨架。
- 身份和后端客户端。
- Router。
- 基础 LangGraph。
- 采购 MCP 工具。

## P0-2

- 基础 RAG。
- Knowledge Agent。
- 带来源知识问答。
- 业务与规则混合问答。

## P0-3

- 查询 DSL。
- 复杂查询接口。
- Analysis Agent。
- 连续追问。

## P0-4

- 后端风险检查。
- 风险补查。
- Review Agent。
- 风险摘要。

## P0-5

- Web 智能协同页签。
- Redis 会话状态。
- Trace。
- 基础评测。
- 前端 Agent 页签。
- Docker Compose。

完成以上内容后，项目已经可以作为一个完整 Agent 应用项目演示。

---

# 二十四、暂时不要做的内容

为了控制开发量，第一版不做：

- 飞书接入、飞书卡片和飞书回调。
- 正式企业级 Web 单点登录。
- 独立 HTTP MCP 网络服务，除非 stdio 已稳定。
- 十几个 Agent。
- 四个独立 MCP 服务进程。
- 自动审批。
- 自动选择最终供应商。
- 任意 Text2SQL。
- 模型微调。
- GPU 推理。
- Kafka。
- 大量微服务。
- 复杂长期用户画像。
- 没有数据依据的兼容性推荐。
- 逐字段多轮填写采购表单。
- 为展示而构造虚假的企业制度。

---

# 二十五、最终完成判定

项目完成后，应满足：

1. 现有采购后端主流程仍然正常。
2. Web 页面可以独立完成三条核心 Agent 演示。
3. 普通采购请求和智能请求分别进入采购后端与 Agent 服务。
4. Agent 服务和采购后端相互独立。
5. Agent 通过标准 MCP 使用业务能力。
6. P0 MCP 可以通过 stdio 正常运行，不要求独立端口。
7. 用户身份和权限继续由后端验证。
8. 能完成采购知识问答。
9. 能结合实时业务数据解释具体问题。
10. 能完成自然语言复杂查询。
11. 能在连续追问中保留查询条件。
12. 能完成多约束候选方案分析。
13. 后端能稳定输出风险信号。
14. Agent 能补查并生成风险摘要。
15. Review Agent 能检查证据和越权问题。
16. 正式写入需要人工确认。
17. 每次任务有完整 Trace。
18. 核心链路有自动评测。
19. 工具失败时能重试、降级或返回部分结果。
20. Redis 状态丢失后能恢复关键会话状态。
21. 整个项目可以通过 Docker Compose 启动。
22. 三条核心演示流程都能用 TEST 数据稳定运行。
23. 浏览器中不存在身份网关密钥。
24. 飞书未接入不影响项目完成判定。

---

# 二十六、建议第一批实际开发任务

开始编码时，按下面顺序建立任务：

1. 建立 `feature/intelligent-agent` 分支。
2. 跑通当前后端和 TEST 数据。
3. 创建 `agent_app` FastAPI 服务。
4. 实现后端签名客户端。
5. 调通 `/users/me`、采购详情和 Agent 会话接口。
6. 创建单进程标准 MCP Server。
7. 将采购详情和历史记录封装为 MCP 工具。
8. 创建 LangGraph State 和最小 Router。
9. 完成“查询当前采购单状态”端到端链路。
10. 建立基础知识文档和 Chroma 索引。
11. 完成“黑名单规则是什么”知识问答。
12. 完成“为什么当前申请不能提交”混合问答。
13. 新增复杂查询 DSL 和后端查询接口。
14. 完成自然语言复杂查询。
15. 增加连续追问状态。
16. 新增风险规则接口。
17. 完成审批风险调查链路。
18. 完成 Review Agent。
19. 扩展 Web 智能协同页签。
20. 增加 Trace、评测和 Docker Compose。

P1 再完成正式 Web 登录和 BFF；P2 再考虑飞书适配。

这 20 项应严格按顺序推进。前一项没有稳定通过测试，不进入后一项。

---

# 二十七、本次版本调整说明

V1.1 对开发顺序作出以下调整：

- P0 以 Web 版为唯一必须交付入口。
- P0 网络服务只要求采购后端 `8000` 和 Agent `8100`。
- MCP P0 使用 stdio，不占第三个端口。
- 正式 Web 登录、Session 和 BFF 放到 P1。
- 飞书和远程 HTTP MCP 放到 P2。
