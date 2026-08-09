# LangGraph Agent 编排基线 v0.1

更新时间：2026-08-07

## 状态流

当前采购协同 Graph 使用以下显式节点：

`load_context → route → knowledge/realtime_query/analysis/risk_investigation/form_prefill →
sufficiency_check → compose → review → confirmation → finalize`

- Knowledge：本地 BGE + Qdrant Dense/BM25/RRF/Reranker/Parent 回查和 Citation。
- Realtime：只通过 MCP 调用采购后端事实接口。
- Hybrid：先检索稳定规则，再查询实时事实；任一侧缺失时明确部分回答，不互相猜测。
- Analysis：复用现有受控 Planner/Executor 和白名单 Query DSL。
- Risk：复用确定性风险信号、证据补查与程序审查。
- Form Prefill：只创建 `DRAFT` 与 `pending_action`，不调用采购写接口。

## 模型与降级

未配置真实 Provider 时使用确定性 Router、证据模板 Compose 和通用证据 Review。注入结构化模型
角色后，Router、Compose、Review 使用阶段 18 Schema；模型失败会留下 Trace/错误并回退确定性链路。
Query Rewrite 可通过相同角色适配器接入 Retriever。Fake 仅用于验证节点契约，不代表真实质量。

## 状态与 HITL 边界

- LangGraph `thread_id` 使用现有 `conversation_id`。
- Graph 不配置第二套 Checkpointer；对话状态、Redis 状态和 MySQL 快照继续由采购后端管理。
- `pending_action` 与 `awaiting_confirmation` 写入现有 Conversation State，快照恢复后继续保留。
- 提交申请等正式动作在本阶段只生成草稿；`confirmation` 节点只标记需要确认，`executed=false`。
- LangGraph 不修改采购状态机，也不重新实现权限、金额、黑名单、幂等和并发控制。

## Review 范围

通用 Review 检查证据是否充分及是否需要人工确认；模型启用后还按结构化契约检查遗漏约束、分析
冒充事实、越权、不可见证据和 RAG/Tool 冲突。确定性业务规则仍由采购后端负责。

## 验收

- Graph/RAG/Analysis/Risk/Session 专项测试：47 项通过。
- 全仓 Pytest：218 项通过。
- 确定性评测：25/25，通过 v0.2 基线比较。
- 真实本地 RAG→LangGraph：`KNOWLEDGE` 路由、5 条 Citation、充分性检查和 Review 全部通过。

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\verify_agent_graph.py `
  --query '采购申请被楼长驳回后应该怎么处理？' --role APPLICANT
```
