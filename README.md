# ProcurementMind

ProcurementMind 是面向数据中心设备采购场景的智能协同 Agent。项目把确定性的采购业务系统、独立 Agent 服务、知识检索、业务工具和 React Web 组合在一起，为需求人、楼长、采购员、仓库管理员和系统管理员提供采购问答、复杂查询、风险调查、表单辅助与人工确认能力。

本项目不把大模型当作业务事实源：权限、采购状态机、金额、黑名单、风险规则和正式写入始终由采购后端负责；Agent 负责理解问题、检索依据、调用只读工具、组织分析和生成待确认动作。

## 项目解决的问题

- 回答采购制度、角色职责、字段填写和操作流程问题，并展示知识来源。
- 查询采购单状态、处理人、采购记录、供应商和风险等实时业务事实。
- 将自然语言转换为受控分析计划，执行聚合、趋势、对比和候选分析。
- 对审批风险进行确定性信号检查、相似案例与供应商履约补查。
- 从自然语言生成采购申请草稿；任何正式写操作均等待人工确认。
- 在采购详情页通过上下文助手协同处理当前申请，同时重新查询后端权威事实。

## 当前核心能力

| 领域 | 当前实现 |
|---|---|
| 采购后端 | FastAPI、MySQL、Redis、Alembic；采购申请、审批、采购、入库、供应商、推荐、通知、会话与管理员能力 |
| Agent 服务 | 独立 FastAPI 服务（8100）、LangGraph、6 类路由、会话恢复、结构化输出与安全降级 |
| 模型运行时 | Provider-neutral Adapter；已注册 OpenAI-compatible Provider；Primary/Fallback、超时、有限重试、熔断和真实用量记录 |
| RAG | 7 份 Markdown 知识源、Qdrant、Dense + BM25 Sparse、RRF、Rerank、Parent-Child、Metadata Filter、Query Rewrite 与 Citation |
| 工具层 | 单一 stdio MCP Server；按 procurement/product/supplier/analytics namespace 逻辑隔离；工具只通过 HTTP 调用采购后端 |
| 分析与调查 | Planner/Executor、受控查询 DSL、供应商履约、相似案例、风险信号、证据充分性检查和 Review |
| HITL | 一次性确认令牌、15 分钟有效期、确认/取消/过期/重复与并发保护；写入复用后端状态机 |
| Web | React、TypeScript、Vite、React Router、Ant Design、Ant Design X；SSE、HITL、Context Assistant 与分角色业务页面 |
| 工程保障 | Trace、阶段耗时、确定性评测、RAG 评测、Agent acceptance evaluation、性能基准、Pytest、Vitest 与 Docker Compose |

## 系统架构

```text
React Web :5173 (/demo/)
        │
        │ 开发环境 BFF：/demo-api/*
        ▼
Procurement Backend :8000 ─────── MySQL / Redis
        ▲
        │ 受签名保护的 HTTP API
        │
Agent Service :8100
        │
        ├─ LangGraph / Model Runtime / Trace / HITL
        ├─ RAG Providers ───────── Qdrant
        └─ MCP Client ── stdio MCP Server ── HTTP ── Backend
```

安全边界：

- `app/` 是采购业务数据和规则的唯一事实源。
- `agent_app/` 不直接访问采购业务 MySQL；知识同步使用独立知识表边界。
- MCP 不导入采购 Repository 或数据库 Session，只调用采购后端 API。
- 浏览器不持有 `IDENTITY_GATEWAY_SECRET`、模型 Key 或 RAG Key。
- `ui_context` 只提供页面类型、申请 ID 和可选用户草稿；业务事实必须由 Tool 回查。

## Agent 工作流

当前 Graph 主流程为：

```text
load_context → route
  ├─ knowledge
  ├─ realtime_business
  ├─ hybrid
  ├─ complex_query
  ├─ risk_investigation
  └─ form_prefill
→ sufficiency_check → compose → review → confirmation（按需）→ finalize
```

当前路由类型：

- `KNOWLEDGE`：制度、流程、角色和字段规范。
- `REALTIME_BUSINESS`：采购单、处理人、价格、记录和供应商等实时事实。
- `HYBRID`：同时需要知识依据和实时业务事实。
- `COMPLEX_QUERY`：聚合、趋势、对比和多步骤分析。
- `RISK_INVESTIGATION`：风险信号、履约、相似案例与规则证据调查。
- `FORM_PREFILL`：生成采购申请草稿，不直接写入。

Router、Query Rewrite、Planner、Compose 和 Review 是同一 Agent 服务内的逻辑模型角色，不是多个独立服务。简单请求会跳过不必要的 Planner 或模型 Review；模型不可用或单次调用失败时，Graph 按节点契约回退到确定性链路，并在 Trace 中记录原因。

## 技术栈

- Python `>=3.12,<3.13`
- FastAPI、Pydantic、SQLAlchemy Async、Alembic
- LangGraph（项目未依赖 LangChain）
- MySQL 8.0、Redis 7.4、Qdrant 1.18
- MCP Python SDK（stdio transport）
- React 19、TypeScript 6、Vite 8、React Router 7
- Ant Design 6、Ant Design X 2
- Pytest、Ruff、Vitest、ESLint

## RAG

知识源位于 `knowledge/source/`，当前共有 7 份 Markdown 文件；`knowledge/publish/` 中的 Word 文件用于阅读和交付，不是索引源。

检索链路：

1. 可选模型 Query Rewrite；失败时保留原问题。
2. Dense 向量与 BM25 Sparse 分别召回。
3. 使用 RRF 融合候选。
4. Reranker 重排并应用最低分阈值。
5. 回查 Parent 内容，执行 Metadata 与可见性过滤。
6. 返回结构化 Citation 和检索 Trace。

默认配置使用阿里云百炼兼容接口：

- Embedding Provider：`aliyun_bailian`
- Embedding Model：`qwen3.7-text-embedding`
- Rerank Provider：`aliyun_bailian`
- Rerank Model：`qwen3-rerank`
- 默认 Collection：`procurement_knowledge_child_qwen37`

`local_bge` 仍是可选 Provider，需要配置 `EMBEDDING_MODEL_PATH`、`RERANKER_MODEL_PATH` 和运行设备。Embedding Provider、模型、向量维度或向量 Schema 变化后，应使用新的 Provider-specific collection 名称并重新构建索引，不能把不同向量空间混入现有 Collection。

## MCP 与工具

当前部署只有一个由 Agent 按调用上下文启动的 stdio MCP Server，不存在多个独立 MCP 服务进程，也没有当前可用的 HTTP MCP 服务。工具通过 catalog metadata 按 namespace 逻辑隔离。

主要只读能力包括当前用户、采购单、履历、历史采购、产品/供应商推荐、采购分析、风险信号、相似案例和供应商履约。模型不能控制可信身份或 Trace 参数，不能生成任意 SQL，也不能绕过后端权限。

## HITL

Agent 可生成 `pending_action`，但不会在 Graph 中直接执行采购写入。React Web 展示确认卡片后，用户可以确认或取消；确认请求由 Agent 校验会话、身份、一次性令牌、有效期和重复状态，再调用后端既有写接口。后端继续校验角色权限、`expected_version`、`action_token` 和状态机。

## Web

正式 Web 第一版位于 `frontend/`，通过 Hash Router 运行在 `/demo/` 基路径。当前包含：

- 分角色工作台、动态菜单和岗位待办 Badge。
- 智能助手：SSE 状态事件、正文增量、Citation、Tool 摘要、取消和重试。
- 我的采购、新建/编辑、采购详情、审批、采购、入库和历史记录。
- 供应商分页查询、远程名称选择和楼宇供应商风险。
- 采购详情 Context Assistant Drawer 与 `ui_context`。
- ADMIN 独立信息架构、员工管理、全局采购与供应商只读查询。
- 统一中文业务枚举和 Backend 错误映射。

开发环境下，浏览器只调用 Backend 的 `/demo-api/*` BFF；Backend 负责签名业务请求和转发 Agent SSE/HITL。Compose 当前不包含独立 frontend 服务，详见[本地开发环境搭建与启动指南](docs/本地开发环境搭建与启动指南.md)。

## Trace 与评测

每次 Agent 执行可记录路由、Graph 节点、检索、工具、模型、错误、证据、主/回退模型以及阶段耗时。响应中的 execution details 和 performance 字段用于定位问题；这不是 Langfuse 或 OpenTelemetry 的当前集成。

当前评测与验证入口：

```powershell
python scripts\run_deterministic_evaluations.py
python scripts\run_rag_evaluations.py
python scripts\run_agent_acceptance_evaluation.py
python scripts\benchmark_agent_latency.py
```

- Deterministic evaluation：Router、Tool Security、Analysis 和 Risk 固定契约。
- RAG evaluation：召回、排序、路由、引用与负例拒答，可比较检索阶段。
- Agent acceptance evaluation：25 条固定用例，覆盖 Knowledge、Realtime、Complex Query、Risk Investigation、Form Prefill 各 5 条；输出任务成功率、路由准确率、工具准确率、耗时分位数、模型/工具调用数、错误与阶段耗时。
- 可选轻量 RAG acceptance：10 条知识规则用例。

评测结果写入 `.artifacts/`，该目录不提交。历史 baseline 记录的是当时的验收事实，不能被当前临时结果覆盖。

## 项目目录

```text
app/                 采购业务后端、API、Service、Repository 与数据模型
agent_app/           Agent API、Graph、模型、RAG、MCP、HITL、评测与 Trace
frontend/            React Web
knowledge/source/    RAG Markdown 知识源
knowledge/publish/   阅读/交付版 Word 文档
migrations/          Alembic 迁移
scripts/             启动、初始化、知识重建、验证、评测与性能脚本
tests/               后端、Agent、RAG、MCP、评测和集成测试
docs/                当前说明、设计记录与历史 baseline
```

## 环境配置

从 `.env.example` 创建本地 `.env` 和/或 Compose 使用的 `.env.docker`，不要提交真实密钥。

关键配置组：

- 基础设施：`MYSQL_*`、`REDIS_*`、`QDRANT_URL`、`QDRANT_COLLECTION`
- 身份边界：`IDENTITY_GATEWAY_SECRET`
- 生成模型：`MODEL_PROVIDER=openai_compatible`、`PRIMARY_MODEL`、`FALLBACK_MODEL`、`MODEL_API_KEY`、`MODEL_BASE_URL`
- RAG：`RAG_EMBEDDING_PROVIDER`、`RAG_RERANK_PROVIDER`、`RAG_*_MODEL`、`RAG_API_KEY`、`RAG_BAILIAN_BASE_URL`
- 执行限制：`MAX_TOOL_CALLS`、`MAX_EXECUTION_STEPS`、`TASK_TIMEOUT_SECONDS`
- 质量与诊断：`REVIEW_ENABLED`、`TRACE_ENABLED`、`PERFORMANCE_OPTIMIZATIONS_ENABLED`

RAG Key/Base URL 为空时会复用模型配置。模板中的空值只表示密钥由部署环境提供，不表示项目没有真实模型能力。

## 启动方式

请先激活满足 Python `>=3.12,<3.13` 的项目虚拟环境；本项目维护者使用的具体 Conda 路径见本地开发指南。

推荐开发启动：

```powershell
cd frontend
npm.cmd install
cd ..
.\scripts\start_dev.ps1
```

脚本会启动 MySQL、Redis、Qdrant 容器，执行迁移，并在本地启动 Backend、Agent 和 Vite。停止：

```powershell
.\scripts\stop_dev.ps1
```

完整 Compose（基础设施、迁移、Backend、Agent，不含独立 React frontend 服务）：

```powershell
docker compose --env-file .env.docker up -d --build
```

详细首次配置、手工调试、知识索引和常见错误见[本地开发环境搭建与启动指南](docs/本地开发环境搭建与启动指南.md)。

## 测试

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .

cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run test
npm.cmd run build
```

需要真实模型、Qdrant、MySQL 或完整服务的脚本属于集成/验收流程；普通单元测试不应依赖私有 Key。

## 当前限制

- Compose 当前不构建或启动 React frontend；生产静态托管/反向代理需要单独补齐。
- 当前模型注册表实现的是 OpenAI-compatible Adapter；其他 Provider 需要新增适配器。
- 本地 BGE 可运行但 CPU 延迟较高，默认开发配置使用远程 Embedding/Rerank API。
- HTTP MCP、独立动态 Skill 系统、知识库管理页面、评测结果页面、Langfuse 与 OpenTelemetry 尚未实现。
- 开发 BFF 和 `TEST_PLATFORM` 身份仅用于本地联调；正式身份接入需要部署侧适配。
- 固定评测框架已具备，但单次评测数值受数据、模型和运行环境影响，不构成永久质量保证。

## 文档索引

- [本地开发环境搭建与启动指南](docs/本地开发环境搭建与启动指南.md)
- [技术方案](docs/数据中心设备采购智能协同Agent-技术方案.md)
- [开发任务清单](docs/数据中心设备采购智能协同Agent-开发任务清单.md)
- [后端与 Agent 接口联调说明](docs/后端接口联调说明.md)
- [前端设计文档](docs/数据中心设备采购智能协同Agent-前端设计文档.md)
- [功能模块划分](docs/数据中心设备采购智能协同Agent-功能模块划分.md)
- [需求分析](docs/数据中心设备采购智能协同Agent-需求分析.md)
- [系统分析](docs/数据中心设备采购智能协同Agent-系统分析.md)
- [历史文档说明](docs/archive/README.md)
- [阶段验收 baseline](docs/baseline/)
