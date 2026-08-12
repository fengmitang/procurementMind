# Procurement Agent Backend

数据中心采购流程自动化 Agent 的 FastAPI 后端。

第一次搭建环境请阅读远端仓库中的
[本地开发环境搭建与启动指南](https://github.com/fengmitang/procurementMind/blob/main/docs/本地开发环境搭建与启动指南.md)。

## 开发环境

- Python：`F:\Anaconda\envs\purchasing-agent\python.exe`
- FastAPI：本机 Conda 环境
- 采购后端：`http://127.0.0.1:8000`
- Agent 服务：`http://127.0.0.1:8100`
- MySQL：procurementMind 专属 Docker 容器，`127.0.0.1:13307`
- Redis：procurementMind 专属 Docker 容器，`127.0.0.1:16380`
- Qdrant：单节点持久化 Docker 容器，`127.0.0.1:6333`

项目使用 `procurement-mind` 专属 Compose 项目、容器、网络和数据卷，不会连接或复用本机已有 MySQL、其他 Docker 网络、数据卷或 Redis。

## 初始化

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\bootstrap_env.py
docker compose --env-file .env.docker config
docker compose --env-file .env.docker up -d
```

上述 Compose 命令会依次启动 procurementMind 专属 MySQL、Redis、Qdrant、数据库迁移、
采购后端和 Agent；后端只映射到 `127.0.0.1:8000`，Agent 只映射到 `127.0.0.1:8100`。
查看状态：

```powershell
docker compose --env-file .env.docker ps
```

需要调试源码时，可以只保留 MySQL 和 Redis 容器，再使用本机既有 Conda 环境分别启动
两个应用；不要在该环境中重复安装依赖：

```powershell
docker compose --env-file .env.docker stop backend agent
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

在另一个终端启动 Agent：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m uvicorn agent_app.main:app --host 127.0.0.1 --port 8100 --reload
```

当前 Agent 聊天接口已接入受限 LangGraph 工作流。它可以识别知识、实时业务、混合、
复杂查询和风险调查，并通过标准 MCP 查询当前采购申请状态和下一处理人。复杂查询已经
接入受控 Planner/Executor、分析型后端工具、跨轮条件继承和结构化结果；审批风险调查
会组合确定性风险信号、补查证据和程序 Review。RAG 索引、检索、Citation 和评测已经接入
聊天 Graph；知识、实时、混合、复杂分析、风险调查和表单预填均有受控路径。

Graph 每轮都会通过采购后端保存用户消息、Agent 回答、结构化 Redis 状态和 MySQL
快照；Redis 状态丢失时可继续使用采购后端已有的快照恢复能力。Graph 不建立第二套
数据库或 Redis 连接。

LangGraph 当前状态流为 `load_context → route → retrieve/tools/analysis → sufficiency_check →
compose → review → confirmation → finalize`，并使用现有 `conversation_id` 作为 `thread_id`。
未配置真实生成模型时，Router、Compose 和 Review 使用可测试的确定性降级；配置结构化 Provider
后可接管相应节点，失败时保留错误并回退。表单预填只保存草稿和待确认动作，不执行采购状态变更。
完整编排契约见 `docs/baseline/langgraph-orchestration-v0.1.md`。

聊天响应同时返回请求级 `execution` 执行详情，汇总同一个 Trace 下的路由、Graph 步骤、
MCP 工具参数与耗时、Review、受控错误和组件状态。当前确定性链路没有调用模型，因此
模型调用数为 0，Token 和费用为 `null`；系统不会用估算值冒充真实用量。真实模型接入后
再从供应商响应采集用量和费用。

## 生成模型配置（暂留空）

当前不绑定模型供应商，也不安装任何供应商 SDK。实时采购状态链路和 DEV-06 的确定性
评测使用 Router、假 Planner、LangGraph 和 MCP，可以在没有模型密钥时运行。假 Planner
只用于验证 Schema、执行顺序、工具调用和标准答案，不能替代真实模型智能性验收。

模型无关层已经为 Router、Query Rewrite、Planner、Compose 和 Review 定义严格结构化输出，
并统一处理 Schema 校验、超时、有限重试、熔断和受控错误。Compose 不能引用当前可见证据集之外
的 Citation；Review 只检查证据、约束、事实边界、权限、可见性、RAG/Tool 冲突和人工确认，
不重新执行确定性业务规则。Token 仅汇总供应商真实返回的完整用量，缺失时保持 `null`，不做估算。
详细契约见 `docs/baseline/llm-provider-contract-v0.1.md`。

需要启用模型时，只在不提交 Git 的 `.env` 中填写以下字段：

```dotenv
MODEL_PROVIDER=
PRIMARY_MODEL=
MODEL_API_KEY=
MODEL_BASE_URL=
FALLBACK_MODEL=
```

- `MODEL_PROVIDER`：后续确认的供应商标识。
- `PRIMARY_MODEL`：主模型名称。
- `MODEL_API_KEY`：供应商密钥，只保存在本机 `.env` 或部署密钥系统中。
- `MODEL_BASE_URL`：可选的兼容 API 地址。
- `FALLBACK_MODEL`：可选的备用模型名称。

字段定义及是否配置的判断位于 `agent_app/core/config.py`，供应商无关的运行时配置位于
`agent_app/models/configuration.py`。选择供应商后再增加对应适配器；Graph 不直接依赖
供应商 SDK。`GET /ready` 的 `data.model` 会返回 `configured` 或 `not_configured`。

供应商无关模型网关已经提供统一结构化请求/响应、适配器注册、超时、可重试错误、有限重试
和 Pydantic Schema 校验。当前没有注册真实供应商；脚本化假模型只用于故障和回归测试。

模型与 MCP 分别使用独立熔断器，默认连续 3 次基础设施失败后打开，30 秒后只允许一个
`HALF_OPEN` 探针；业务拒绝和权限拒绝不会计为基础设施故障。相关阈值可通过
`MODEL_CIRCUIT_*` 和 `MCP_CIRCUIT_*` 环境变量调整。单次 Agent 任务还受
`TASK_TIMEOUT_SECONDS` 总时限约束。失败、超时或降级时，响应会保留结构化错误和组件状态，
并明确不把不完整分析描述成完整结论。

## 本地 RAG 推理模型

RAG 的本地模型、文档切分、索引、混合检索、引用、Trace 和检索评测已经完成；Knowledge
角色将在阶段 19 接入聊天 Graph：

- Embedding：`BAAI/bge-m3`，本地目录 `F:/AIModels/bge-m3`。
- Reranker：`BAAI/bge-reranker-v2-m3`，本地目录
  `F:/AIModels/bge-reranker-v2-m3`。
- Python 环境：`F:/Anaconda/envs/purchasing-agent`。
- 当前机器固定使用 `cpu`。代码保留 `auto`、`cpu`、`cuda` 三种模式：`auto` 在 CUDA
  可用时选择 CUDA，否则使用 CPU；显式 `cuda` 在 CUDA 不可用时直接报错，不静默回退。

可提交的配置模板位于 `.env.example`；本机实际路径只写入不会提交 Git 的 `.env`：

```dotenv
EMBEDDING_MODEL_PATH=F:/AIModels/bge-m3
RERANKER_MODEL_PATH=F:/AIModels/bge-reranker-v2-m3
RAG_EMBEDDING_PROVIDER=aliyun_bailian
RAG_RERANK_PROVIDER=aliyun_bailian
RAG_EMBEDDING_MODEL=qwen3.7-text-embedding
RAG_RERANK_MODEL=qwen3-rerank
RAG_MODEL_DEVICE=cpu
QDRANT_COLLECTION=procurement_knowledge_child_qwen37
```

开发环境默认通过阿里百炼调用 Embedding 与 Rerank。RAG 默认复用 `MODEL_API_KEY` 和
`MODEL_BASE_URL`；如需单独凭证或业务空间地址，可设置 `RAG_API_KEY` 和
`RAG_BAILIAN_BASE_URL`。Key 只允许保存在本机 `.env` 或部署密钥系统中。

切回本地 BGE 时设置：

```dotenv
RAG_EMBEDDING_PROVIDER=local_bge
RAG_RERANK_PROVIDER=local_bge
QDRANT_COLLECTION=procurement_knowledge_child
RAG_EMBEDDING_BATCH_SIZE=4
RAG_RERANK_MIN_SCORE=0.2
```

切换 Embedding Provider 后必须为目标 Provider 使用独立 collection 并执行全量索引重建；即使
向量维度同为 1024，也禁止混用不同模型的 Dense 向量。旧 BGE collection 会保留，可在切回本地
Provider 后复用并按需重建。

重新下载或校验模型时运行：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\download_rag_models.py
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\verify_rag_models.py
```

下载脚本使用 `huggingface_hub.snapshot_download()`，模型和 Hugging Face 下载缓存都限制在
`F:/AIModels`，并拒绝把目标目录设在项目内部。Agent 服务只从本地路径加载；配置完整时在
本地 Provider 在服务启动阶段初始化一次，后续请求复用同一组模型实例。Embedding 和 Reranker
使用独立 Provider 封装，
上层不直接依赖 FlagEmbedding API。缺少任一模型路径、本地模型文件不完整或加载失败时，服务会
明确失败，不会静默联网下载或切换远程模型。本机 `.env` 明确设置为 `cpu`，因此当前验证和
运行不会使用 GPU。离线交付时可直接复制两个模型目录到目标服务器，并通过环境变量改为目标
服务器的绝对路径。

Qdrant 固定使用单节点持久化部署，不使用 Cloud 或集群。Child Chunk collection 同时配置
1024 维 Cosine Dense 向量和带 IDF modifier 的 Sparse/BM25 向量；首次启动基础设施后可幂等
创建或校验 collection：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\initialize_qdrant.py
```

脚本发现已有 collection 的向量名称、维度、距离或 Sparse 配置不兼容时会明确失败，不会删除
或静默重建现有索引。

知识库以 `knowledge/source/` 下 7 份独立 Markdown 为唯一源文件。同步程序优先按文档元数据、
Markdown 标题层级和业务语义边界生成 Parent-Child；Child 的 Embedding 文本包含文档标题、章节
路径、主题和正文，并同时写入当前 Provider 的 Dense 向量及 Qdrant 原生多语言 BM25 Sparse 向量。
全量构建和单文档增量同步分别执行：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\rebuild_knowledge.py --all
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\rebuild_knowledge.py --document 'knowledge\source\01-数据中心设备采购业务管理与流程指引（试行）.md'
```

同步先比较内容哈希，未变化且索引为 `READY` 的文档直接跳过。变更时只替换该文档对应的
MySQL Parent 和 Qdrant Child，不删除整个数据库或 collection；异常会记录为 `ERROR`，再次执行
即可重试。`--all` 还会将源目录中已删除的文档标记为 `RETIRED` 并清理其索引。

知识检索使用 Qdrant 当前 Query API：Dense 与多语言 BM25 各自召回后由服务端 RRF 融合，再由
配置选择的 `qwen3-rerank` 或本地 `bge-reranker-v2-m3` 精排。默认召回数量、RRF 参数、精排数量、Parent 和总上下文预算均由
`RAG_DENSE_TOP_K`、`RAG_SPARSE_TOP_K`、`RAG_FUSION_TOP_K`、`RAG_RERANK_TOP_K`、
`RAG_RRF_K`、`RAG_PARENT_MAX_CHARS` 和 `RAG_CONTEXT_MAX_CHARS` 配置。检索调用必须提供角色，
并始终只读取 `ACTIVE` Child 和 `READY` Parent；设备范围为空时只允许全局知识。可用真实本地模型
执行单问题验收：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\verify_rag_retrieval.py `
  --query '采购申请被楼长驳回后应该怎么处理？' `
  --role APPLICANT
```

Query Rewrite 是可选能力；未配置生成模型或 Rewrite 失败时会保留错误原因并使用原 Query，
不会阻塞 Dense/BM25/RRF/Reranker 链路。Parent 只在 Chunk 类型和问题语义需要、内容确有扩展且
不超预算时回查，不会把所有完整 Parent 无条件塞入上下文。

## 标准 MCP 工具层

Agent 使用官方 Python MCP SDK 的标准 `stdio` transport 启动独立工具子进程。当前只开放
11 项 P0 只读工具：当前用户、采购申请、采购时间线、历史采购检索、产品/历史/供应商推荐，
以及受控采购分析、风险信号、相似案例和供应商履约。工具只调用采购后端公开 HTTP API，
不直接连接 MySQL 或 Redis。

11 项工具在同一进程内按 `procurement`、`product`、`supplier`、`analytics` 元数据 namespace
逻辑隔离，保持原有工具名兼容客户端。工具发现结果声明只读、非破坏、幂等和封闭后端边界；
每次结果同时返回事实类型、采购后端权威性、后端可见性约束，以及权限/参数/冲突/超时/不可用
错误是否可重试。RAG 只提供稳定规则；实时状态、处理人、价格、采购记录、供应商资料、黑名单
和统计只能使用 Tool。二者冲突时实时事实以采购后端为准，Tool 不可用时不会用 RAG 猜测。

平台身份和 Trace 由 Agent 进程通过可信运行时上下文注入，不出现在模型可填写的工具参数
中；采购后端仍会执行签名、角色、楼宇范围和数据权限校验。单工具默认超时 15 秒，冷启动
握手默认超时 60 秒，可通过 `.env` 中的 `MCP_TOOL_TIMEOUT_SECONDS` 和
`MCP_STARTUP_TIMEOUT_SECONDS` 调整。

直接启动 MCP Server（通常由 Agent MCP Client 自动启动）：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m agent_app.mcp.server
```

## 检查

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m pytest
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m ruff check .
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m ruff format --check .
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\run_deterministic_evaluations.py
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\run_rag_evaluations.py
```

确定性评测统一运行 Router、工具参数与越权、Analysis Planner 和风险契约四个套件，并与
`docs/baseline/deterministic-evaluation-baseline-v0.2.json` 只读比较。RAG 评测独立运行 12 个
真实本地模型用例，对比 Dense、Sparse、Hybrid、Hybrid+Reranker，并与
`docs/baseline/rag-evaluation-baseline-v0.1.json` 只读比较；完整检索 Trace 写入被 Git 忽略的
`.artifacts/rag-evaluation/`。两个运行器都不会自动更新基线。

采购后端健康检查：

- `GET /health`
- `GET /ready`

Agent 服务健康检查和接口：

- `GET http://127.0.0.1:8100/health`
- `GET http://127.0.0.1:8100/ready`
- `POST http://127.0.0.1:8100/api/v1/chat`

## 容器安全边界

- 应用镜像以固定 UID `10001` 的 `procurement` 用户运行，不使用 root。
- `.env`、本机数据、测试、文档和 Git 历史不会进入镜像构建上下文。
- 数据库、Redis、身份网关和模型密钥只在 Compose 运行时注入，不写入 Dockerfile。
- Agent 只通过采购后端 HTTP 接口和 stdio MCP 访问业务能力，不直接连接采购 MySQL/Redis。
- Qdrant 使用独立持久卷；当前 7 份知识文档已按 Parent-Child 结构写入 Dense + Sparse/BM25
  collection，索引更新按文档增量执行。

本地镜像与 Compose 验证步骤见
`docs/baseline/resilience-deployment-v0.1.md`。

## 本地功能体验界面

开发环境启动 FastAPI 后，浏览器打开：

- `http://127.0.0.1:8000/demo/`

界面可以切换需求人、楼长、采购员、仓库管理员和系统管理员等 TEST 身份，
按角色完成以下业务：

- 需求人：新建申请、保存不完整草稿、补齐资料后提交、查看状态和历史申请。
- 楼长：查看待审批及管辖楼宇申请、修订员工需求、填写审核资料、驳回或通过。
- 采购员：查看待采购任务、登记供应商和成交信息、提交仓库及查看历史采购。
- 仓管：查看待入库任务、登记库位和实收数量、完成采购及查看历史入库。

此外还可体验供应商与推荐、采购历史与时间线、Agent 数据存储及通知 Outbox。
页面调用真实后端接口并执行正常的身份、角色和楼宇权限校验；网关签名密钥只在
后端使用，不会发送到浏览器。

“智能协同”页签可以直接调用独立 Agent 服务，展示对话状态、实际统计口径、汇总指标、
明细表格、风险事实、规则阈值、人工核实项和证据完整性。浏览器只调用开发环境的固定
`/demo-api/agent-chat` 入口，由采购后端转发到 `AGENT_SERVICE_URL`；浏览器不能指定
目标地址，也不会获得身份网关或模型密钥。该开发入口不会进入生产 OpenAPI。

每次回答下方的“执行详情”可以展开查看组件状态、模型用量、执行计划、Trace 时间线、
工具调用、程序 Review 和受控错误。它只展示当前请求已经产生的事实；RAG 未配置、模型
未调用或结果部分完成时均会单独标记。

申请详情和历史记录会按流程依次显示提交、审批、采购、入库和完成时间，并保留
已完成步骤的经办人、角色和联系方式。手机号默认脱敏；有权查看该申请的用户
点击脱敏号码后，页面才会单独请求并显示完整号码。

业务时间按北京时间保存和展示。需求人详情不显示“缺失字段”和采购执行快照，
采购相关进度通过流程履历查看；采购员、楼长、仓管等办理角色仍可查看工作所需资料。

该入口仅在 `APP_ENV=development` 时开放，并会修改开发数据库中的 TEST 数据。

采购申请的设备类型固定为：电气、暖通、弱电、机房环境、工器具、算力服务器、
IDC网络、其他。

## 全流程虚拟数据

填充或重置带 `TEST` 标识的开发数据：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\seed_demo_data.py
```

脚本只重建自身维护的测试记录，可重复执行。它覆盖采购全部状态、审核驳回与重提、
三种入库数量关系、供应商快照与黑名单、Agent 会话及通知状态。

仅清理这批测试数据：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\seed_demo_data.py --clean
```

## 身份网关

飞书适配层或内部网关先验证平台用户，再向后端发送以下身份头：

- `X-Platform-Type`
- `X-Platform-User-Id`
- `X-Gateway-Timestamp`
- `X-Gateway-Nonce`
- `X-Gateway-Signature`

签名使用本地 `IDENTITY_GATEWAY_SECRET` 生成 HMAC-SHA256 摘要。后端校验签名
有效期，并通过 Redis 拒绝随机数重放。客户端不得自行传入员工编号、姓名、手机号
或角色作为操作者身份。

## 流程一致性

采购状态只能按照后端状态机定义的方向流转。所有关键流转必须同时提供：

- `expected_version`：防止旧页面或并发请求覆盖最新数据。
- `action_token`：防止重复点击或消息重试重复执行业务。

状态更新和操作日志使用同一个数据库事务；任一环节失败时全部回滚。

## 采购主流程接口

已实现 `/api/v1/requirements` 下的以下能力：

- 创建草稿、保存需求字段、查询详情和个人相关列表。
- 提交楼长、驳回、重新提交、保存审核方案和提交采购员。
- 开始采购、保存供应商快照、提交仓库、保存入库信息和完成流程。
- 查询符合角色及楼宇范围的下一处理人。

完整流程使用统一身份签名、角色权限、楼宇范围、版本号和幂等令牌校验。

## 供应商与推荐接口

已实现以下能力：

- `/api/v1/suppliers`：按名称或统一社会信用代码搜索，以及采购员/管理员新增供应商。
- `/api/v1/suppliers/{supplier_id}`：查询供应商主档、脱敏财务资料和黑名单状态。
- `/api/v1/suppliers/{supplier_id}/blacklist`：楼长基于已完成采购登记永久或限时黑名单。
- `/api/v1/suppliers/{supplier_id}/blacklists/{blacklist_id}/release`：原登记楼长或管理员提前解除黑名单。
- `/api/v1/recommendations/products`：按设备类型、名称和关键词推荐历史品牌型号。
- `/api/v1/recommendations/purchase-history`：查询相似采购历史并标注供应商风险。
- `/api/v1/recommendations/suppliers`：按历史采购推荐供应商，并排除有效黑名单供应商。

采购执行资料始终保存为本次采购快照；只有采购员明确提交
`update_supplier_profile=true` 时，才同步更新供应商主档。

## Agent 后端支撑接口

采购后端不实现大模型推理、提示词、意图识别或工具编排，只向外部 Agent
提供以下接口和存储能力：

- `POST /api/v1/agent/conversations/active`：获取或创建当前业务动作的活动会话。
- `POST/GET /api/v1/agent/conversations/{id}/messages`：幂等写入及分页读取会话消息。
- `GET/PUT /api/v1/agent/conversations/{id}/state`：读取或更新 Redis 短期结构化状态。
- `POST /api/v1/agent/conversations/{id}/snapshot`：将当前状态保存到 MySQL 快照。
- `POST /api/v1/agent/conversations/{id}/complete`：保存最终快照并完成会话。

Redis 状态默认保留 72 小时。Redis Key 丢失时，后端会从
`agent_session_state` 恢复关键状态；完整消息始终保存在 MySQL。

## 分析型后端接口

已增加以下只读接口，并已接入 Analysis Agent 和 MCP 工具：

- `POST /api/v1/analytics/purchase-query`：执行受控查询 DSL、有限聚合和分组。
- `GET /api/v1/requirements/{id}/risk-signals`：计算七类确定性风险信号。
- `GET /api/v1/requirements/{id}/similar-cases`：返回规则加权的相似案例。
- `GET /api/v1/suppliers/{id}/performance`：返回履约、延期和数量异常统计。

Agent 不能提交任意 SQL。查询字段、状态、设备专业、聚合、分组和排序均使用白名单，
并执行签名身份、行级权限、日期范围、超时、扫描上限和分页上限。统计口径和 v0.2
OpenAPI 变更见 `docs/baseline/analytics-backend-interface-v0.2.md`。

Analysis Agent 的计划、步骤依赖、工具结果、表格、聚合、候选项、部分成功状态及跨轮查询
上下文均为结构化数据。模型只能生成白名单计划和 DSL；权限、数据范围、数值和风险事实仍由
采购后端裁决。详细契约见 `docs/baseline/analysis-agent-interface-v0.1.md`。

## 审批风险调查

风险调查 Graph 已实现确定性阶段：先读取后端风险信号，再读取采购详情，并在工具预算内并行
补查历史价格、供应商履约和相似案例。每项证据保留来源、参数、Trace、成功/失败/不可用状态；
真实制度材料未提供时明确标记信息不足。

结构化风险摘要直接复制后端风险事实、指标、阈值和记录编号，并将可能原因标记为待核实。
程序 Reviewer 会检查数字、风险代码、来源映射和审批越权用语。真实模型语义 Reviewer 与制度
证据仍待后续接入，详见 `docs/baseline/risk-investigation-interface-v0.1.md`。

## 交付演示与验收

启动 Compose 并确认 TEST 数据已填充后，可重复执行模型无关交付演示：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\run_delivery_demos.py
```

脚本通过后端固定开发入口调用真实 Agent 服务，不直接访问 MySQL 或 Redis。报告包含：

- `DEM-002`：固定日期范围的品牌采购统计，以及同一会话中“再排除延期供应商”的条件继承。
- `DEM-003`：采购申请 91009 风险调查，验证风险代码、证据来源、程序审查、人工核实项和非审批结论声明。
- `DEM-001`：真实知识材料未提供时固定返回 `BLOCKED`，不以虚构制度作为通过结果。

成功标准是 `passed=2`、`failed=0`、`blocked=1`。可以使用 `--output` 保存 JSON 报告；
完整步骤和标准答案见 `docs/baseline/delivery-demos-v0.1.md`。

## 通知 Outbox

采购业务事务只负责将通知写入 `notification_outbox`。后台任务再调用平台无关的
HTTP 通知网关，发送失败不会回滚采购业务。

- `GET /api/v1/notifications`：管理员查询通知状态、失败原因和重试信息。
- `POST /api/v1/notifications/dispatch-due`：管理员手动处理一批到期通知。
- `POST /api/v1/notifications/{id}/resend`：管理员将失败通知重新入队。

后台单次处理命令：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m app.workers.notifications
```

部署时需要配置 `NOTIFICATION_GATEWAY_URL`，鉴权令牌通过
`NOTIFICATION_GATEWAY_TOKEN` 写入本地环境变量。未配置网关时会记录真实失败，
不会将通知误标记为发送成功。

外部系统联调方式见远端仓库中的
[后端接口联调说明](https://github.com/fengmitang/procurementMind/blob/main/docs/后端接口联调说明.md)。

## 数据安全

- `.env` 和 `.env.docker` 均不提交 Git。
- 不要执行 `docker compose down -v`，除非明确需要删除本项目全部开发数据。
