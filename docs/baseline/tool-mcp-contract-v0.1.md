# Tool / MCP 契约基线 v0.1

更新时间：2026-08-07

## 服务边界

- MCP Server 使用官方 Python MCP SDK 的 `stdio` transport，在单进程内提供 11 项只读工具。
- 工具只调用采购后端 HTTP API，不导入业务 Repository/Session，不连接业务 MySQL/Redis。
- 模型不能提供平台身份、用户标识或 Trace；这些值由可信子进程环境注入。
- 统计工具只接受 `AnalyticsQueryInput` 白名单 DSL，不接受 SQL 或任意字段。
- 工具名称保持稳定；逻辑边界通过 MCP `_meta.procurementMind.namespace` 表达，不拆微服务。

## Namespace

| Namespace | 工具 |
| --- | --- |
| `procurement` | `get_current_user`、`get_purchase_request`、`get_purchase_timeline`、`search_purchase_records`、`recommend_purchase_history`、`get_requirement_risk_signals`、`get_similar_cases` |
| `product` | `recommend_products` |
| `supplier` | `recommend_suppliers`、`get_supplier_performance` |
| `analytics` | `query_purchase_analytics` |

所有工具发现元数据必须声明：只读、非破坏、幂等、非开放世界；业务元数据必须声明 namespace、
事实类型、`procurement_backend` 权威源、`backend_enforced` 可见性和 `not_a_knowledge_source`
RAG 边界。

## 结果与错误

成功和失败均使用 `MCPToolResponse`。结果元数据用于标识 `identity_context`、`realtime_fact` 或
`derived_analysis`。错误必须分为权限、未找到、参数校验、冲突、超时、服务不可用或一般后端错误，
并给出 `retryable`；401/403/404/400/422/409 不可重试，429/502/503/504 和本地工具超时可重试。

## RAG / Tool 事实优先级

- 制度、流程、字段规范、操作说明、风险处理规则和 FAQ：RAG 是引用来源。
- 当前状态、处理人、价格、采购记录、供应商资料、黑名单和实时统计：采购后端 Tool 是唯一事实源。
- 实时域发生冲突时采用 Tool 值并保留冲突警告。
- 实时 Tool 未返回值时结果为未解决，不允许回退到 RAG 推测。

## 验收命令

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m pytest `
  tests\test_mcp_tools.py tests\test_mcp_contract.py tests\test_mcp_catalog.py `
  tests\test_mcp_fact_resolution.py tests\test_prompt_injection_security.py -q
```
