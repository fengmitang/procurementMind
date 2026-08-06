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

项目使用 `procurement-mind` 专属 Compose 项目、容器、网络和数据卷，不会连接或复用本机已有 MySQL、其他 Docker 网络、数据卷或 Redis。

## 初始化

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\bootstrap_env.py
docker compose --env-file .env.docker config
docker compose --env-file .env.docker up -d
```

上述 Compose 命令会依次启动 procurementMind 专属 MySQL、Redis、数据库迁移、采购后端
和 Agent；后端只映射到 `127.0.0.1:8000`，Agent 只映射到 `127.0.0.1:8100`。
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
会组合确定性风险信号、补查证据和程序 Review。尚未实现的知识库会明确返回能力边界，
不会编造制度答案。

Graph 每轮都会通过采购后端保存用户消息、Agent 回答、结构化 Redis 状态和 MySQL
快照；Redis 状态丢失时可继续使用采购后端已有的快照恢复能力。Graph 不建立第二套
数据库或 Redis 连接。

聊天响应同时返回请求级 `execution` 执行详情，汇总同一个 Trace 下的路由、Graph 步骤、
MCP 工具参数与耗时、Review、受控错误和组件状态。当前确定性链路没有调用模型，因此
模型调用数为 0，Token 和费用为 `null`；系统不会用估算值冒充真实用量。真实模型接入后
再从供应商响应采集用量和费用。

## 模型配置（暂留空）

当前不绑定模型供应商，也不安装任何供应商 SDK。实时采购状态链路和 DEV-06 的确定性
评测使用 Router、假 Planner、LangGraph 和 MCP，可以在没有模型密钥时运行。假 Planner
只用于验证 Schema、执行顺序、工具调用和标准答案，不能替代真实模型智能性验收。

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

## 标准 MCP 工具层

Agent 使用官方 Python MCP SDK 的标准 `stdio` transport 启动独立工具子进程。当前只开放
11 项 P0 只读工具：当前用户、采购申请、采购时间线、历史采购检索、产品/历史/供应商推荐，
以及受控采购分析、风险信号、相似案例和供应商履约。工具只调用采购后端公开 HTTP API，
不直接连接 MySQL 或 Redis。

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
```

确定性评测统一运行 Router、工具参数与越权、Analysis Planner 和风险契约四个套件，并与
`docs/baseline/deterministic-evaluation-baseline-v0.1.json` 只读比较。知识质量套件在真实
材料到位前标记为 `BLOCKED`，不计为通过或失败。运行器不会自动更新基线；基线变化必须
先人工确认再修改文件。

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
- 当前只为后续 RAG 预留独立持久卷；在真实知识材料和索引实现到位前不启动空壳 Chroma 服务。

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
