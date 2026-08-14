# 数据中心设备采购智能协同 Agent 技术方案

> 版本：V1.2
> 更新日期：2026-08-14
> 文档属性：当前实现方案；历史开发过程以开发任务清单和 `docs/baseline/` 为准

## 一、文档目的

本文描述 ProcurementMind 当前已经落地的系统架构、技术边界和可扩展方向。内容以工作区代码、配置、测试和脚本为事实来源，不把规划能力写成当前成果。

系统目标是形成一条可控制、可恢复、可评测、可观测，并能安全接入真实采购业务数据的 Agent 链路。

## 二、设计原则

1. **确定性业务留在后端**：权限、状态机、必填校验、金额、黑名单、风险阈值和正式写入由采购 Backend 执行。
2. **结论必须有依据**：实时事实来自 Tool，制度与流程来自知识库；两者冲突时以后端实时事实为准。
3. **逻辑角色而非服务膨胀**：Router、Knowledge、Analysis、Review 和 Form Prefill 是一个 Agent 服务内的逻辑职责。
4. **查询自动化、写入人工确认**：只读工具可自动执行，正式业务动作必须进入 HITL。
5. **结构化和预算约束**：路由、计划、模型输出、Tool 参数与响应均有 Schema；步骤、工具、重试和总时长有上限。
6. **全链路可诊断**：Graph、模型、检索、Tool、错误和阶段耗时进入 execution details/trace。

## 三、总体架构

```text
React Web :5173
     │
     │ /demo-api BFF（开发环境）
     ▼
Procurement Backend :8000 ── MySQL / Redis
     ▲
     │ 受签名保护的 HTTP
     │
Agent Service :8100
     ├─ LangGraph / Memory / HITL
     ├─ Model Runtime / Structured Roles
     ├─ RAG ── Qdrant
     └─ MCP Client ── stdio MCP Server ── HTTP ── Backend
```

### 服务职责

| 服务 | 负责 | 不负责 |
|---|---|---|
| Procurement Backend | 身份签名校验、权限、采购状态机、业务规则、MySQL/Redis、正式写入、BFF | 模型推理和 RAG |
| Agent Service | 问题理解、Graph 编排、模型、检索、工具调用、分析、Review、HITL 状态 | 绕过 Backend 修改采购数据 |
| React Web | 分角色 UI、SSE、HITL、上下文助手、业务表单 | 保存网关 Secret 或直接访问采购数据库 |
| MCP Server | 将固定只读能力映射为标准 MCP Tool | 任意 SQL、可信身份生成、直接访问 MySQL |

Agent 的知识同步/检索会使用知识文档状态表，但采购业务事实仍只能由 Backend API 提供。

## 四、当前技术栈

### 4.1 后端与基础设施

- Python `>=3.12,<3.13`
- FastAPI、Pydantic 2、Pydantic Settings
- SQLAlchemy 2 Async、Alembic、asyncmy
- MySQL 8.0.44、Redis 7.4、Qdrant 1.18.x
- HTTPX、MCP Python SDK
- Docker Compose
- Pytest、Ruff

### 4.2 Agent 编排

- LangGraph 是核心工作流框架。
- 项目依赖中没有 LangChain，当前实现不依赖 LangChain Retriever、Chain 或 Tool 抽象。
- 会话、消息、状态和快照复用 Backend 的 Agent Session 能力；没有第二套业务状态机。

### 4.3 Web

- React 19、TypeScript 6、Vite 8
- React Router 7（Hash Router）
- Ant Design 6、Ant Design X 2
- React Markdown、Vitest、Testing Library、ESLint

旧原生静态体验页的定位已被 React Web 替代；`/demo/` 目前是 React 构建/开发基路径，不代表项目仍是单页静态原型。

## 五、LangGraph 工作流

主流程：

```text
load_context → route
  ├─ knowledge
  ├─ realtime
  ├─ knowledge → realtime（hybrid）
  ├─ analysis
  ├─ risk
  └─ form_prefill
→ sufficiency_check → compose → review → confirmation → finalize
```

### 5.1 状态

Graph State 包含任务/Trace/会话标识、可信用户、消息、受限 `ui_context`、路由、已解析采购申请、证据、Tool 结果、错误、Trace 事件、分析结果、风险调查、知识结果、Review、待确认动作和表单草稿。

### 5.2 路由

当前支持：`KNOWLEDGE`、`REALTIME_BUSINESS`、`HYBRID`、`COMPLEX_QUERY`、`RISK_INVESTIGATION`、`FORM_PREFILL`。

模型 Runtime Ready 时优先使用结构化 Router；失败时回退确定性 Router。用户在页面上下文中提供的状态或草稿不是事实，Graph 必须重新调用 Tool。

### 5.3 证据充分性与 Review

- Knowledge 要求存在可回答的检索结果。
- Realtime 要求至少一个成功 Tool。
- Hybrid 同时要求知识和实时事实。
- Complex Query、Risk、Form Prefill 分别要求对应结构化结果。
- 简单 Knowledge/Realtime/Form 请求可跳过不必要的模型 Review；Hybrid、Risk 及需要模型规划的复杂查询执行语义 Review。
- 模型 Review 失败时保留错误并使用确定性证据审查，不伪造成功。

## 六、模型运行时

### 6.1 Adapter 与 Provider

模型层采用 Provider-neutral 协议和注册表。当前默认注册：

```text
MODEL_PROVIDER=openai_compatible
```

配置 `MODEL_BASE_URL`、`MODEL_API_KEY`、`PRIMARY_MODEL` 后 Runtime 进入 `READY`。`FALLBACK_MODEL` 可选，使用同一 Provider Adapter。

Runtime 状态包括 `NOT_CONFIGURED`、`READY`、`PROVIDER_NOT_REGISTERED` 和 `INITIALIZATION_FAILED`；Agent `/ready` 会反映真实初始化状态。

### 6.2 逻辑模型角色

| 角色/Purpose | 用途 | 性能设置 |
|---|---|---|
| Router | 严格分类，不回答问题 | thinking 关闭，小输出上限 |
| Query Rewrite | 生成等价检索问题 | thinking 关闭，小输出上限 |
| Analysis Plan/Replan | 受控工具计划 | 保留 Provider 默认 thinking |
| Compose | 依据可见证据生成业务回答 | thinking 关闭，结构化 Citation |
| Review | 检查证据、越权、冲突和确认要求 | thinking 关闭 |

所有模型输出通过 Pydantic Schema 校验。Runner 支持超时、有限结构化重试、共享熔断、Primary/Fallback、流式协议兼容和 Provider 报告的用量；没有完整 Provider 用量时不会估算 Token 或费用。

## 七、RAG 技术方案

### 7.1 知识来源

- 索引源：`knowledge/source/` 下 7 份 Markdown。
- 发布阅读版：`knowledge/publish/` 下对应 Word 文档，不参与索引。
- 文档、Parent 和 Child 状态由知识同步边界维护。

### 7.2 解析与索引

- Markdown 按标题层级解析并保留章节路径。
- 使用 Parent-Child 切分；Child 参与召回，Parent 用于补足回答上下文。
- Metadata 包含文档、章节、版本/状态和可见性信息。
- Qdrant Collection 同时定义命名 Dense Vector 与 BM25 Sparse Vector。

### 7.3 检索流程

```text
Query Rewrite（可选）
   ├─ Dense recall
   └─ BM25 Sparse recall
        ↓
      RRF fusion
        ↓
      Rerank
        ↓
Metadata/可见性过滤 + Parent 回查
        ↓
Citation / Retrieval Trace / Context
```

### 7.4 Provider

当前实现支持：

| Provider | Embedding | Rerank | 定位 |
|---|---|---|---|
| `aliyun_bailian` | 默认 `qwen3.7-text-embedding` | 默认 `qwen3-rerank` | 当前默认，适合规避本地 CPU 延迟 |
| `local_bge` | 本地 BGE 路径 | 本地 BGE Reranker 路径 | 可选离线模式，CPU 较慢，可配置 CUDA |

RAG 可使用独立 `RAG_API_KEY`/`RAG_BAILIAN_BASE_URL`，空值时复用生成模型配置。

### 7.5 Collection 规则

Dense 模型、Provider、维度或向量 Schema 变化时必须新建/重建 Provider-specific Collection。`.env.example` 当前使用 `procurement_knowledge_child_qwen37` 和 1024 维 Dense。Qdrant 会校验 Collection Schema，避免把不兼容向量写入已有索引。

Chroma 是历史早期选型，当前运行链路已由 Qdrant 替代。配置类和 Dockerfile 中仍有兼容性遗留字段/目录，但不代表 Chroma 是当前 RAG 存储。

## 八、MCP 与 Tool

### 8.1 当前部署

当前只有一个 `agent_app.mcp.server` stdio MCP Server。Agent Client 为每次可信调用注入平台身份与 Trace，启动标准 MCP 会话并调用固定工具。

`procurement`、`product`、`supplier`、`analytics` 是 catalog namespace，不是四个服务进程。HTTP MCP 尚未实现，只能作为未来扩展。

### 8.2 工具边界

工具覆盖当前用户、采购申请、履历、历史采购、产品/供应商推荐、受控采购分析、风险信号、相似案例和供应商履约。

- 参数由 Pydantic/JSON Schema 限制。
- 身份和 Trace 不允许模型传入。
- MCP 只通过 Backend HTTP Client 获取事实。
- 分析使用白名单 DSL，不接受 SQL。
- 工具调用有超时、重试分类、熔断和最大次数。

## 九、Planner / Executor

复杂查询使用结构化 `AnalysisPlan`。Planner 只能选择固定只读工具枚举，并只能生成允许的 Query DSL 字段、分组、聚合、排序和分页。

Executor 按依赖执行步骤，支持安全独立步骤并行、部分成功保留和一次受控重规划。简单单记录查询不会为了展示复杂度而强制经过 Planner。

## 十、Memory 与状态恢复

- MySQL 保存 Agent Conversation、Message、State 和 Snapshot。
- Redis 用于会话状态缓存和 TTL。
- Graph 使用既有 `conversation_id` 作为线程标识。
- 每轮结束保存 Agent 消息、结构化 message data、状态和快照。
- Redis 状态不可用时可由 Backend 持久化状态恢复。

## 十一、领域规则与 Skills 状态

当前代码没有独立 `skills/` 目录、动态 Skill Loader、Skill 版本管理或管理页面。因此 Skills 不是已实现核心技术。

领域规则目前由以下机制承载：

- 结构化 Role Prompt 与输出 Schema。
- MCP Tool Contract 和 catalog metadata。
- LangGraph 节点、路由与证据规则。
- Procurement Backend 的确定性权限、风险和状态机。
- 知识源文档与 Metadata。

独立、可版本化、可动态加载的 Skill 系统属于后续可选扩展；引入前必须明确规则所有权、审计、灰度和回滚机制。

## 十二、结构化输出

必须结构化的内容包括路由、Query Rewrite、分析计划、Compose/Citation、Review、检索结果、Tool 响应、风险调查、待确认动作和表单草稿。Schema 校验失败会有限重试或进入受控降级，不把自由文本解析为正式业务动作。

## 十三、Human-in-the-loop

可能产生的动作包括创建草稿、提交申请、审批通过/驳回、选择最终供应商、登记采购结果、提交入库、记录入库和完成采购。

Graph 只生成 `pending_action`。确认流程校验用户身份、会话、action ID、一次性 token、15 分钟有效期、重复/并发状态，再调用 Backend 原有 API。取消、过期或已消费 token 不会执行写入。

## 十四、权限与安全

- Backend HMAC 身份网关绑定平台类型、用户、时间戳、Nonce 和请求。
- 浏览器只走 BFF，不持有 Secret。
- Backend 根据角色和楼宇范围裁剪数据。
- Prompt Boundary 标记知识与用户输入，阻止注入内容成为系统指令。
- Agent 不公开数据库主键、内部 Prompt、Chunk、Graph、Tool 或原始技术异常。
- 正式写入继续使用 `expected_version` 和 `action_token`。
- 管理员有独立信息架构；采购与供应商全局查询为只读，员工变更记录操作审计。

## 十五、稳定性与性能

- 模型：超时、结构化重试、Primary/Fallback、熔断。
- MCP：启动/工具超时、后端重试、熔断、结构化错误。
- Graph：最大步骤、最大工具调用、总任务超时、证据充分性和安全降级。
- RAG：Embedding、Rewrite、Retrieval Cache；远程 API 重试；批量 embedding/upsert。
- 性能优化：按 Role 限制输出 token、关闭不必要 thinking、简单请求跳过 Planner/Review、记录模型/检索/重排/Tool 与持久化阶段耗时。

缓存不替代权限检查或后端权威事实。

## 十六、Trace 与可观测性

当前使用项目自研 execution details 和 trace events，记录：

- 路由、Graph 节点、状态和耗时。
- Tool 名称、参数、结果、来源、错误与耗时。
- Retrieval 候选、融合、Rerank、Citation 和阶段耗时。
- 模型 Purpose、主模型/实际模型、Fallback、重试、首 token、解析与校验耗时。
- 整体 Graph、准备身份/会话、消息持久化和请求总耗时。

Langfuse 和 OpenTelemetry 当前未集成，可作为未来集中观测方案，不应写成当前能力。

## 十七、评测方案

### 17.1 已实现评测

- Deterministic：Router、Tool Security、Analysis、Risk。
- RAG：Dense、Sparse、Hybrid、Rerank、路由、引用、负例与 baseline 比较。
- Agent Acceptance：25 条固定 Agent API 用例，覆盖五类主业务场景。
- Lightweight RAG Acceptance：10 条固定规则/权限/拒答用例。
- Delivery Demo：知识、复杂查询和风险等演示链路。
- Performance Benchmark：本地 CPU/API RAG、Agent 阶段耗时与优化前后比较。

### 17.2 指标

路由准确率、任务成功率、工具准确率、召回/排序指标、Citation、负例拒答、工具与模型调用数、平均/P50/P95 耗时、错误分布和模型/检索/重排/工具阶段耗时。

评测结果写入 `.artifacts/`。历史 baseline 只记录生成时的可验证事实；新模型、索引或数据环境的结果应生成新工件/新版本，不能改写旧 baseline。

## 十八、受控自然语言查询

第一版不是 Text2SQL。模型只能生成 `PurchaseQueryRequest` 允许的过滤、分组、聚合、排序和分页字段；Backend 再执行权限裁剪、范围限制、扫描上限和超时。任意 SQL 与模型直接访问数据库均不在当前范围。

## 十九、Web 与 BFF

React Web 包含工作台、智能助手、采购申请、岗位流程、供应商、上下文助手和 Admin 页面。Agent SSE 事件通过 Backend BFF 转发，包含 conversation、thinking/analyzing、Citation、Tool 摘要、确认请求、正文与 completed/error。

当前 `compose.yaml` 没有 frontend service，Dockerfile 也没有 Node build stage。开发态由 Vite 5173 提供；生产静态托管或独立 Web 容器属于尚待补齐的部署工作。

## 二十、部署

当前 Compose 已实现 MySQL、Redis、Qdrant、migration、Backend 和 Agent，包含健康检查、网络与数据卷。Agent 数据卷用于本地运行数据，Qdrant/MySQL/Redis 各自持久化。

当前未完成或不应误报为已完成：

- 独立 frontend 容器/生产反向代理。
- HTTP MCP。
- 完整外部平台身份适配。
- 独立 Skills 系统。
- Langfuse/OpenTelemetry 集成。
- 知识库管理、Skill 管理和评测结果管理页面。

## 二十一、当前技术亮点

1. 采购 Backend 与 Agent 服务职责清晰，确定性规则不交给模型。
2. LangGraph 六类路由统一编排知识、实时、分析、风险和表单场景。
3. Provider-neutral 结构化模型 Runtime 支持 Primary/Fallback 和受控降级。
4. Qdrant Dense + BM25、RRF、Rerank、Parent-Child 与 Citation 形成完整 RAG。
5. 单一标准 stdio MCP 通过 namespace 管理只读工具，并保持数据库安全边界。
6. SSE、HITL 和 Context Assistant 把 Agent 能力嵌入真实采购页面。
7. Trace、固定评测集和阶段耗时让质量与性能可回归。

## 二十二、版本调整说明

V1.2 将原“规划方案”同步为当前实现：固定 Python 3.12，移除未使用的 LangChain，使用 Qdrant 替代 Chroma，明确百炼/本地 BGE Provider、React Web、单一 stdio MCP、非独立 Skills 现状、自研 Trace 和已实现评测；未来扩展与当前能力分开表述。
