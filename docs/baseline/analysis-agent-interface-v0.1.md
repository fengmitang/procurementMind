# Analysis Agent 接口与执行契约 v0.1

> 日期：2026-08-05  
> 范围：DEV-06 确定性开发与假模型评测阶段

## 1. 调用链与边界

复杂查询沿用统一聊天入口 `POST /api/v1/chat`，执行链为：

`Router → Analysis Planner → Executor → stdio MCP → 采购后端 HTTP API`

Agent 和 MCP 均不访问采购 MySQL 或 Redis。模型不能提交 SQL、URL、身份字段或未注册工具名；
采购后端继续执行签名、角色、楼宇、日期范围、超时、扫描上限和分页限制。

## 2. MCP 分析工具

| 工具 | 后端接口 | 用途 |
|---|---|---|
| `query_purchase_analytics` | `POST /api/v1/analytics/purchase-query` | 白名单查询、聚合和分组 |
| `get_requirement_risk_signals` | `GET /api/v1/requirements/{id}/risk-signals` | 后端确定性风险事实 |
| `get_similar_cases` | `GET /api/v1/requirements/{id}/similar-cases` | 可解释相似案例 |
| `get_supplier_performance` | `GET /api/v1/suppliers/{id}/performance` | 履约和异常比例 |

所有工具都使用 MCP 标准结构化响应；工具参数不包含平台身份和 Trace，这些值由可信子进程
上下文注入。

## 3. Planner 和 Executor

Planner 输出固定包含目标、步骤 ID、步骤目标、工具枚举、参数、前置依赖、独立执行标记和
终止条件。计划最多 8 步，只允许一次计划调整。

Executor 保证：

- 只执行枚举中的只读分析工具。
- 依赖步骤按顺序执行，互不依赖的安全步骤可并行。
- 部分失败保留成功结果和失败原因。
- 计划调整后不会重复已经成功的步骤。
- 工具调用数继续受 `MAX_TOOL_CALLS` 限制。

## 4. 结构化结果

聊天响应的 `data.analysis` 包含：

- `answer`：只依据工具结果生成的简要说明。
- `plan`：最终结构化计划和调整次数。
- `effective_query`：后端确认后用于连续追问的查询条件。
- `datasets`：按步骤保存的原始结构化工具结果。
- `summary`、`groups`：统计和分组。
- `table`、`candidates`：表格和候选案例。
- `step_results`：每个工具的参数、结果、来源、Trace 和耗时。
- `warnings`、`partial_success`：失败和降级状态。

连续追问只继承 `effective_query`，不继承自然语言结论。新查询默认不继承旧条件；以“再、
另外、改为、只看、排除”等明确追问标记开头时才合并上一轮条件，并将页码重置为 1。

## 5. 当前假模型与真实模型门禁

`DeterministicAnalysisPlanner` 是可重复的假 Planner，只负责自动化测试中的固定语言样例，
不是正式智能能力。模型供应商适配器将实现同一 `AnalysisPlanner` 协议，因此不会改变 Graph、
Executor、MCP 或后端查询结构。

真实模型接入前保持以下配置为空：

```dotenv
MODEL_PROVIDER=
PRIMARY_MODEL=
MODEL_API_KEY=
MODEL_BASE_URL=
FALLBACK_MODEL=
```

真实模型阶段必须验证自然语言条件提取、复合步骤拆分、连续追问、结构化输出失败重试、延迟
和成本；完成前不将 DEV-06 标记为最终完成。

## 6. 评测基线

固定语言样例位于 `tests/fixtures/analysis_evaluation_v0.1.json`。真实后端标准答案使用 TEST
数据验证 2026-08-01 至 2026-08-05 的算力服务器采购：9 笔、平均单价 1112.50、中位价
950.00、总金额 34350.00，并验证分组、Trace 和权限链路。
