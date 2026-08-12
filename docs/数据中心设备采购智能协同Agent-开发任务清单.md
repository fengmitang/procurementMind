# 数据中心设备采购智能协同 Agent 开发任务清单

> 版本：V1.4
> 建立日期：2026-08-04
> 最近更新：2026-08-11
> 当前阶段：阶段 23 Web 前端业务修复与 Agent 上下文协同进行中；阶段 21 交付收尾保留进行中
> 需求与设计基线：需求分析 V2.1，以及技术方案、功能模块划分、系统分析、开发计划 V1.1
> 唯一交付仓库：`fengmitang/procurementMind`

---

# 一、清单用途

本文件是项目后续开发的执行清单，用于记录：

- 开发任务和依赖关系。
- 当前状态、完成日期和验证证据。
- 影响范围、遗留问题和下一步。
- 需求、代码和文档之间需要确认的决策。

五份项目文档继续作为需求与设计基线；本清单只负责把开发计划转成可执行任务，不替代基线文档。

---

# 二、维护规则

## 2.1 状态标记

- `[ ]`：尚未开始。
- `[-]`：正在进行；同一时间原则上只保留一个开发批次。
- `[x]`：代码、测试和必要文档均已完成。
- `[!]`：存在阻塞、冲突或需要用户确认。

## 2.2 完成条件

任务只有同时满足以下条件才能标记为 `[x]`：

1. 实现已经进入当前工作树。
2. 对应自动化测试已通过。
3. 没有破坏现有采购后端测试。
4. 必要的接口、配置或启动文档已经同步。
5. 本文件记录了完成日期和验证证据。

仅创建类名、空接口、Prompt 或演示性占位代码，不算完成真实 Agent 能力。

## 2.3 每次开发后的维护动作

1. 更新当前任务状态。
2. 记录修改文件。
3. 记录执行的测试及结果。
4. 记录遗留问题和风险。
5. 汇报当前完成位置和下一个无阻塞任务。
6. 每个 Agent / RAG 阶段完成后汇报并暂停；只有用户回复“继续”才进入下一阶段。
7. 如果修改需求、边界或优先级，同步指出需要更新的基线文档。

## 2.4 用户确认门禁

- 阶段内按依赖顺序连续开发，不逐项暂停；进入新阶段前必须取得用户“继续”确认。
- 开始阶段前说明范围、影响和验证方式；阶段执行期间持续汇报重要节点。
- 阶段完成后，必须生成一份总结，至少包含：
  - 已完成内容。
  - 修改文件。
  - 关键设计决定。
  - 已运行的测试和结果。
  - 尚未完成或存在风险的部分。
  - 下一阶段。
- 完成阶段总结后暂停；只有用户回复“继续”，才进入下一阶段。
- 如果开发中遇到不确定事项、需求冲突、重要技术选择、业务口径、权限扩大、正式写入或破坏性操作，立即暂停并请求用户确认。
- 普通实现细节、可逆重构、测试修复和已确定边界内的技术选择不单独请求确认。
- 用户未确认前，不自行选择冲突方案，也不提前实现后续任务。

## 2.5 合并开发批次

原任务 ID 保留，用于依赖、验收和进度追踪；下表只调整执行与确认粒度。

| 批次 | 包含任务 | 一次性交付目标 | 预设确认门禁 | 状态 |
|---|---|---|---|---|
| DEV-01 | M1 `AGT-001` 至 `AGT-005`；M2 `CLI-001` 至 `CLI-005` | 独立 Agent 服务骨架、安全后端客户端、会话客户端和完整基础/集成测试 | 无 | `[x]` 2026-08-04 |
| DEV-02 | M3 `MCP-001` 至 `MCP-007` | 标准 stdio MCP、P0 只读工具、Trace/错误边界和契约测试 | 新增依赖与文档冲突时确认 | `[x]` 2026-08-05 |
| DEV-03 | M4 `GRF-001` 至 `GRF-004`、`RTR-001`、`MEM-001`、`TRC-001` | 最小 LangGraph 实时业务问答、会话恢复、Trace 和端到端测试 | 模型配置可留空，不阻塞模型无关链路 | `[x]` 2026-08-05 |
| DEV-04 | M5 `RAG-000` 至 `RAG-006`、`KNW-001` 至 `KNW-003` | 真实知识文档导入、权限检索、引用、知识/混合问答和评测 | 开始前必须确认真实知识材料 | `[-]` 7 份材料与本地推理模型就绪，完整 RAG 待开发 |
| DEV-05 | M6 `ANB-001` 至 `ANB-005`、`RSK-001` 至 `RSK-003`、`SUP-001`、`CAS-001` | 查询、统计、风险、履约、案例接口和后端契约 | 实现风险规则前确认延期、部分入库等统计口径 | `[x]` 2026-08-05 |
| DEV-06 | M7 `MCP-008`、`PLN-001`、`EXE-001` 至 `EXE-002`、`ANA-001` 至 `ANA-004`、`MEM-002` | Analysis Agent、Planner/Executor、连续追问、结构化结果和标准答案评测 | 真实模型联调前确认供应商、模型和密钥 | `[!]` 确定性阶段完成，等待真实模型配置 |
| DEV-07 | M8 `INV-001` 至 `INV-004`、`REV-001` 至 `REV-003` | 审批风险调查、证据校验、Review 回路和评测 | 发现新增审批业务口径时确认 | `[!]` 确定性阶段完成，等待模型和知识材料 |
| DEV-08 | M9 `WEB-001` 至 `WEB-006` | Web 智能协同入口、引用/表格/风险展示和前端安全测试 | 需要改变既有采购页面主流程时确认 | `[!]` 模型无关部分完成，WEB-003 等待知识材料 |
| DEV-09 | M10 `TRC-002` 至 `TRC-003`、`EVL-001` 至 `EVL-004`、`WEB-007` | 全链路 Trace、评测、回归基线和执行详情 | 更新评测基线前确认 | `[!]` 模型无关部分完成，RAG/真实模型指标待门禁 |
| DEV-10 | M11 `RES-001` 至 `RES-003`、`SEC-001`、`DEP-001` 至 `DEP-002`、`DEM-001` 至 `DEM-003`、`DOC-001`、`REL-001` | 容错、安全、部署、三条演示、文档和最终验收 | 破坏性资源操作或外部发布前确认 | `[!]` DEV-10A 完成，模型/RAG/最终验收待门禁 |

如果 DEV-04 因知识材料暂时阻塞，可在用户确认后先执行与其独立的 DEV-05；不会静默改变顺序。

---

# 三、固定架构边界

- `app/` 是采购业务后端和正式数据的唯一真实来源。
- `agent_app/` 是新增的独立 Agent 服务，不直接访问采购 MySQL 或采购 Redis。
- MCP Server 通过 HTTP 调用采购后端，不导入采购 Repository 或数据库 Session。
- Agent 不执行任意 SQL，只能生成受控查询 DSL 或调用固定工具。
- 权限、楼宇范围、状态机、金额、黑名单、风险数值和正式写入由采购后端校验。
- 浏览器不保存 `IDENTITY_GATEWAY_SECRET`。
- 正式业务写入必须经过人工确认，并继续使用 `expected_version` 和 `action_token`。
- EchoMind 仅作为只读参考；许可证和授权未确认前不复制其源码。

---

# 四、里程碑总览

| 里程碑 | 目标 | 主要交付物 | 状态 |
|---|---|---|---|
| M0 | 固化现有后端基线 | 可复现环境、测试结果、OpenAPI、接口权限清单 | `[x]` 2026-08-04 |
| M1 | 建立独立 Agent 服务 | `agent_app`、配置、健康检查、聊天接口骨架 | `[x]` 2026-08-04 |
| M2 | 打通安全后端调用 | 签名客户端、用户上下文、统一错误处理 | `[x]` 2026-08-04 |
| M3 | 建立标准 MCP 工具层 | stdio MCP Server、Client、首批只读工具 | `[x]` 2026-08-05 |
| M4 | 完成最小 LangGraph 链路 | Graph State、Router、实时业务问答、状态持久化 | `[x]` 2026-08-05 |
| M5 | 完成基础 RAG（历史规划） | 文档导入、Metadata、引用、Knowledge Agent；Chroma 选型已由阶段 13 的 Qdrant 决策替代 | `[-]` 由阶段 12–16 接续 |
| M6 | 补齐分析型后端接口 | 查询 DSL、风险信号、履约统计、相似案例 | `[x]` 2026-08-05 |
| M7 | 完成复杂查询分析 | Planner/Executor、多工具调用、连续追问、表格结果 | `[-]` 真实模型验收中 |
| M8 | 完成审批风险调查 | 风险补查、证据摘要、Review 回路 | `[-]` 确定性调查与程序审查完成 |
| M9 | 完成 Web 智能协同入口 | 对话、表格、引用、风险摘要和任务状态 | `[-]` 基础入口完成，知识引用待材料 |
| M10 | 完成 Trace 与评测 | 节点 Trace、评测集、回归检测 | `[-]` 确定性基线完成，RAG/模型质量待门禁 |
| M11 | 完成容错、部署和验收 | 重试、熔断、降级、Compose、三条演示 | `[-]` 模型无关容错与部署基线完成 |

---

# 五、P0 开发任务

## M0：固化现有后端基线

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| BAS-001 | 将远端代码检出到当前目录，排除远端 `docs`，保留本地五份基线文档 | 无 | `origin/main` 正确；代码目录存在；本地五份文档未被覆盖 | `[x]` 2026-08-04 |
| BAS-002 | 修正仓库名和远端启动文档链接 | BAS-001 | 全仓搜索无旧仓库地址；README 链接有效 | `[x]` 2026-08-04 |
| BAS-003 | 创建 Agent 开发分支 | BAS-001 | 分支基于已记录的稳定提交；不直接在 `main` 开发 | `[x]` 2026-08-04 |
| BAS-004 | 按启动指南生成本地配置并启动独立 MySQL、Redis | BAS-003 | 使用 procurementMind 专属容器、数据卷、数据库/账号和 Redis 实例；端口不冲突；两个容器均为 healthy | `[x]` 2026-08-04 |
| BAS-005 | 执行数据库迁移和 TEST 数据初始化 | BAS-004 | Alembic 位于 head；TEST 数据校验通过 | `[x]` 2026-08-04 |
| BAS-006 | 运行现有后端完整测试与 Ruff | BAS-005 | Pytest、Ruff check、Ruff format check 全部通过 | `[x]` 2026-08-04 |
| BAS-007 | 验证 `/health`、`/ready`、Swagger 和角色全流程 | BAS-006 | 健康检查正常；采购主流程可完成 | `[x]` 2026-08-04 |
| BAS-008 | 保存 OpenAPI 和当前提交基线 | BAS-006 | `docs/baseline/openapi-backend-v0.1.json` 及 SHA 记录完成 | `[x]` 2026-08-04 |
| BAS-009 | 建立 Agent 接口复用与权限矩阵 | BAS-008 | 每个现有接口标记为只读可用、需扩展、人工写入或禁止调用 | `[x]` 2026-08-04 |

## M1：建立独立 Agent 服务

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| AGT-001 | 创建 `agent_app/` 分层目录 | BAS-009 | 目录职责符合技术方案，不导入采购 Repository | `[x]` 2026-08-04 |
| AGT-002 | 增加 Agent 配置、日志、异常和统一响应 | AGT-001 | 配置来自环境变量；敏感值不进入日志 | `[x]` 2026-08-04 |
| AGT-003 | 实现 Agent `/health` 与 `/ready` | AGT-002 | 8100 服务独立启动；依赖状态可区分 | `[x]` 2026-08-04 |
| AGT-004 | 实现结构化聊天请求/响应骨架 | AGT-002 | Pydantic 校验生效；无自由字典作为核心契约 | `[x]` 2026-08-04 |
| AGT-005 | 增加 Agent 服务基础测试 | AGT-003, AGT-004 | 健康、配置、Schema 和异常测试通过 | `[x]` 2026-08-04 |

## M2：安全调用采购后端

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| CLI-001 | 实现网关签名生成器 | AGT-005 | 签名与后端算法一致；Nonce 和时间戳符合要求 | `[x]` 2026-08-04 |
| CLI-002 | 实现异步采购后端 HTTP Client | CLI-001 | 支持连接池、超时、Trace 和结构化错误 | `[x]` 2026-08-04 |
| CLI-003 | 封装当前用户、采购详情和时间线接口 | CLI-002 | TEST 用户可访问授权数据；跨楼宇被后端拒绝 | `[x]` 2026-08-04 |
| CLI-004 | 封装 Agent 会话、消息、状态和快照接口 | CLI-002 | Redis 状态丢失后仍可通过后端恢复 | `[x]` 2026-08-04 |
| CLI-005 | 建立 Mock 与真实后端集成测试 | CLI-003, CLI-004 | 成功、401、403、404、超时和业务错误均有测试 | `[x]` 2026-08-04 |

## M3：标准 MCP 工具层

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| MCP-001 | 引入标准 MCP SDK 并建立 stdio Server/Client | CLI-005 | 存在协议握手、工具发现和标准 transport | `[x]` 2026-08-05 |
| MCP-002 | 实现 `get_current_user` 工具 | MCP-001 | Schema 固定；身份来自可信上下文 | `[x]` 2026-08-05 |
| MCP-003 | 实现 `get_purchase_request` 工具 | MCP-001 | 只能读取当前用户有权访问的申请 | `[x]` 2026-08-05 |
| MCP-004 | 实现 `get_purchase_timeline` 工具 | MCP-001 | 联系方式默认脱敏；权限由后端校验 | `[x]` 2026-08-05 |
| MCP-005 | 实现历史采购和简单推荐工具 | MCP-001 | 工具结果与后端接口一致 | `[x]` 2026-08-05 |
| MCP-006 | 增加参数校验、超时、错误分类和 Trace 传播 | MCP-002 至 MCP-005 | 失败时不猜测结果；错误结构统一 | `[x]` 2026-08-05 |
| MCP-007 | 建立 MCP 契约和故障测试 | MCP-006 | 未知工具、非法参数、超时和子进程失败均覆盖 | `[x]` 2026-08-05 |

## M4：最小 LangGraph 与实时业务问答

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| GRF-001 | 定义 Graph State 和核心 Pydantic Schema | MCP-007 | 用户、会话、路由、证据、工具结果和错误均结构化 | `[x]` 2026-08-05 |
| GRF-002 | 建立 LangGraph 最小图和边界限制 | GRF-001 | 最大步骤、循环和工具调用次数生效 | `[x]` 2026-08-05 |
| RTR-001 | 实现第一版 Router | GRF-002 | 可区分知识、实时业务、混合、复杂查询和风险调查 | `[x]` 2026-08-05 |
| GRF-003 | 完成“当前采购单状态和下一处理人”链路 | RTR-001 | Router、Graph、MCP 和真实后端均参与 | `[x]` 2026-08-05 |
| MEM-001 | 将 Graph 状态映射到现有 Agent 会话接口 | GRF-003 | 消息、状态和最终快照可恢复 | `[x]` 2026-08-05 |
| TRC-001 | 从最小链路开始记录基础 Trace | GRF-003 | 可看到路由、工具参数、结果、耗时和错误 | `[x]` 2026-08-05 |
| GRF-004 | 增加最小链路端到端测试 | MEM-001, TRC-001 | 事实与后端一致；越权和工具失败可控 | `[x]` 2026-08-05 |

## M5：基础 RAG 与 Knowledge Agent

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| RAG-000 | 配置本地 Embedding 与 Reranker 推理模型 | GRF-004 | 模型位于项目外 F 盘；仅本地加载；真实向量和重排验证通过 | `[x]` 2026-08-07 |
| RAG-001 | 确认并整理真实采购知识文档 | GRF-004 | 不使用虚构制度；文档具有来源和版本 | `[x]` 2026-08-07，7 份 Markdown 源文件 |
| RAG-002 | 定义文档 Metadata Schema | RAG-001 | 包含版本、生效时间、角色、设备、权限和过期状态 | `[ ]` |
| RAG-003 | 实现文档解析、章节切分和原文位置保留 | RAG-002 | Chunk 可追溯到文档和章节 | `[ ]` |
| RAG-004 | 建立向量索引和基础向量检索 | RAG-003 | 可重复导入、更新和重建；历史 Chroma 选型已由 Qdrant 替代 | `[ ]` 由阶段 13–15 接续 |
| RAG-005 | 实现权限过滤和结构化引用 | RAG-004 | 越权、过期文档不进入回答证据 | `[ ]` |
| KNW-001 | 实现 Knowledge Agent | RAG-005 | 无依据时明确无法确认 | `[ ]` |
| KNW-002 | 完成纯知识问答场景 | KNW-001 | 回答包含正确文档、版本和章节 | `[ ]` |
| KNW-003 | 完成“为什么当前申请不能提交”混合问答 | KNW-001, MCP-007 | 同时使用文档和实时后端数据 | `[ ]` |
| RAG-006 | 建立基础 RAG 评测集 | KNW-002, KNW-003 | Top-K、引用和忠实度可评测 | `[ ]` |

## M6：分析型后端能力

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| ANB-001 | 定义有限字段、有限聚合的查询 DSL | BAS-009 | 不支持任意 SQL；字段和操作符白名单化 | `[x]` 2026-08-05 |
| ANB-002 | 实现复杂采购查询接口 | ANB-001 | 权限、分页、范围、超时和返回上限生效 | `[x]` 2026-08-05 |
| ANB-003 | 实现 count、均价、中位价和总金额统计 | ANB-002 | 结果与直接数据库标准答案一致 | `[x]` 2026-08-05 |
| RSK-001 | 定义风险信号 Schema 和规则执行器 | ANB-002 | 风险只返回事实、阈值和记录编号 | `[x]` 2026-08-05 |
| RSK-002 | 实现重复、价格、数量、黑名单风险 | RSK-001 | 每条规则有命中和不命中测试 | `[x]` 2026-08-05 |
| RSK-003 | 实现延期、长期未入库和相似申请风险 | RSK-001 | 缺失日期和部分入库口径明确 | `[x]` 2026-08-05 |
| SUP-001 | 实现供应商履约统计接口 | RSK-003 | 比例同时返回分子、分母和时间范围 | `[x]` 2026-08-05 |
| CAS-001 | 实现相似案例接口 | RSK-001 | 第一版使用可解释的规则相似度 | `[x]` 2026-08-05 |
| ANB-004 | 扩充异常和边界 TEST 数据 | RSK-002, RSK-003 | 所有风险规则有稳定演示数据 | `[x]` 2026-08-05 |
| ANB-005 | 更新 OpenAPI 和后端联调文档 | ANB-002 至 ANB-004 | 文档和实际路由契约一致 | `[x]` 2026-08-05 |

## M7：复杂查询与 Analysis Agent

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| MCP-008 | 将查询、统计、履约和案例接口封装为 MCP 工具 | ANB-005 | MCP 不直接访问数据库 | `[x]` 2026-08-05 |
| PLN-001 | 定义 Planner 输出和步骤依赖 Schema | MCP-008 | 目标、条件、工具、依赖和终止条件结构化 | `[x]` 2026-08-05 |
| EXE-001 | 实现 Executor 顺序执行和一次计划调整 | PLN-001 | 已完成步骤不会重复执行 | `[x]` 2026-08-05 |
| EXE-002 | 支持安全的独立工具并行调用 | EXE-001 | 部分成功保留结果和失败原因 | `[x]` 2026-08-05 |
| ANA-001 | 实现 Analysis Agent | EXE-002 | 候选和结论只能来自工具结果 | `[x]` 2026-08-05 |
| ANA-002 | 完成自然语言转查询 DSL | ANA-001 | 条件提取完整；Schema 失败有限重试 | `[-]` 假模型通过，待真实模型验收 |
| MEM-002 | 实现连续追问条件继承 | ANA-002 | 保留时间、楼宇、设备和排除条件 | `[x]` 2026-08-05 |
| ANA-003 | 实现表格、聚合和候选方案结构化结果 | MEM-002 | 前端所需字段和统计口径完整 | `[x]` 2026-08-05 |
| ANA-004 | 建立复杂查询标准答案评测 | ANA-003 | 与后端直接查询结果一致 | `[x]` 2026-08-05（确定性与真实后端） |

## M8：审批风险调查与 Review

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| INV-001 | 建立审批调查 Graph 分支 | RSK-003, ANA-001 | 风险信号先于 LLM 调查执行 | `[x]` 2026-08-05 |
| INV-002 | 并行补查价格、履约、案例和制度 | INV-001, KNW-001 | 各证据保留来源和失败状态 | `[-]` 业务证据完成；制度证据等待材料 |
| INV-003 | 生成结构化风险摘要 | INV-002 | 每项包含事实、规则、可能原因和人工确认项 | `[x]` 2026-08-05（确定性摘要） |
| REV-001 | 实现程序证据与数字校验 | INV-003 | 数字和记录编号可追溯 | `[x]` 2026-08-05 |
| REV-002 | 实现 Review Agent 语义审查 | REV-001 | 检查遗漏、编造、推测和审批越权 | `[!]` 等待真实模型 |
| REV-003 | 实现一次补查或重写回路 | REV-002 | 循环次数和总预算受限 | `[!]` 等待真实模型语义审查 |
| INV-004 | 建立风险摘要评测集 | REV-003 | 风险召回、错误风险、证据覆盖和越权可评测 | `[-]` 基础指标与样例完成；待语义评测 |

## M9：Web 智能协同入口

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| WEB-001 | 设计采购工作台与智能协同页签交互 | GRF-004 | 普通业务和智能请求目标服务明确 | `[x]` 2026-08-05 |
| WEB-002 | 实现聊天、任务状态和错误状态 | WEB-001 | 处理中、失败、部分成功可展示 | `[x]` 2026-08-05 |
| WEB-003 | 实现引用和知识回答展示 | KNW-003, WEB-002 | 文档、版本和章节可见 | `[!]` 空状态完成，等待 DEV-04 知识材料 |
| WEB-004 | 实现表格、筛选条件和统计口径展示 | ANA-003, WEB-002 | 不只显示自然语言总结 | `[x]` 2026-08-05 |
| WEB-005 | 实现审批风险摘要展示 | INV-003, WEB-002 | 风险事实、规则和人工确认项可见 | `[x]` 2026-08-05 |
| WEB-006 | 建立前端身份与密钥安全测试 | WEB-002 至 WEB-005 | 浏览器资源中不存在网关密钥 | `[x]` 2026-08-05 |

## M10：Trace 与自动评测

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| TRC-002 | 完成 Graph、RAG、MCP 和 Review 全链路 Trace | REV-003 | 一个 Trace 可还原完整执行链 | `[!]` Graph/MCP/Review 完成，RAG 等待材料 |
| TRC-003 | 记录模型、Token、费用、步骤和耗时 | TRC-002 | 指标可按请求汇总 | `[!]` 步骤/耗时/未调用状态完成，真实 Token/费用等待模型 |
| EVL-001 | 建立 Router 评测集 | RTR-001 | 分类和复合任务拆分可重复评测 | `[x]` 2026-08-06 |
| EVL-002 | 建立 Tool 参数和越权评测 | MCP-008 | 错误工具及越权调用直接失败 | `[x]` 2026-08-06 |
| EVL-003 | 汇总 RAG、复杂查询和风险评测 | RAG-006, ANA-004, INV-004 | 生成统一报告 | `[!]` Analysis/风险契约完成，RAG 明确阻塞 |
| EVL-004 | 建立显式基线和回归检测 | EVL-003 | 只有人工确认后才更新基线 | `[x]` 2026-08-06 确定性基线 |
| WEB-007 | 实现基础执行详情页面 | TRC-002 | 可查看路由、计划、工具、Review 和错误 | `[x]` 2026-08-06 |

## M11：容错、部署与交付

| ID | 任务 | 依赖 | 验收方式 | 状态 |
|---|---|---|---|---|
| RES-001 | 实现模型和 MCP 超时、重试和错误分类 | TRC-002 | 重试次数和总超时受控 | `[x]` 2026-08-06 |
| RES-002 | 实现熔断和 HALF_OPEN 单探针 | RES-001 | 并发状态转换测试通过 | `[x]` 2026-08-06 |
| RES-003 | 实现 RAG、工具、模型和 Review 降级 | RES-001 | 不完整分析不会描述为完整结论 | `[!]` 工具/模型/混合链路完成，RAG 待材料 |
| SEC-001 | 完成 Prompt Injection 和工具权限测试 | RES-003 | 文档内容不能触发越权工具或泄露敏感数据 | `[!]` 确定性边界完成，真实模型注入评测待配置 |
| DEP-001 | 扩展 Docker Compose | WEB-006, RES-003 | 后端 8000、Agent 8100、stdio MCP、MySQL、Redis、Qdrant 可启动 | `[-]` Qdrant 已完成，完整交付验收由阶段 21 接续 |
| DEP-002 | 增加 Agent 镜像、健康检查和配置示例 | DEP-001 | 非 root 运行；密钥不进入镜像 | `[x]` 2026-08-06 |
| DEM-001 | 固化知识与业务混合问答演示 | DEP-002 | TEST 数据下重复运行稳定 | `[ ]` |
| DEM-002 | 固化复杂查询与连续追问演示 | DEP-002 | 结果与标准答案一致 | `[x]` 2026-08-06 |
| DEM-003 | 固化审批风险调查演示 | DEP-002 | 每条风险有证据且不替代审批 | `[x]` 2026-08-06 |
| DOC-001 | 更新 README、架构、接口、部署和演示文档 | DEM-001 至 DEM-003 | 文档与代码和 Compose 一致 | `[!]` 模型无关部署/演示文档完成，RAG 文档待材料 |
| REL-001 | 执行最终回归和验收 | DOC-001 | 三条演示、全部测试、Ruff、权限和恢复验收通过 | `[!]` 当前范围验收完成，DEM-001/真实模型待门禁 |

---

# 六、P1 与 P2 待办

## P1

- `[ ]` 正式 Web 登录、服务端 Session 和 BFF。
- `[ ]` 完整知识库管理页面和索引管理。
- `[ ]` 混合检索和独立 Rerank 模型。
- `[ ]` 完整 LangGraph Checkpointer 和任务恢复。
- `[ ]` 审批意见草稿的 Human-in-the-loop 写入。
- `[ ]` 用户确认后调用后端写入接口。
- `[ ]` Langfuse 或完整 OpenTelemetry 集成。
- `[ ]` 更完整的成本、延迟和 Prompt 回归管理。

## P2

- `[ ]` 飞书身份映射、消息适配和卡片回调。
- `[ ]` MCP Streamable HTTP。
- `[ ]` 受控 Text2SQL 研究。
- `[ ]` 多模型路由。
- `[ ]` 长期用户记忆。
- `[ ]` 云部署和 CI/CD。
- `[ ]` 更复杂的 Agent 协作。

---

# 七、待确认决策与已知风险

| ID | 问题 | 当前建议 | 状态 |
|---|---|---|---|
| DEC-001 | 查询 DSL 在部分文档中曾被列为 P1 | 将“有限字段、有限聚合 DSL”作为 P0；通用 DSL 留到 P1/P2 | 已按最新开发优先级执行 |
| DEC-002 | Human-in-the-loop 第一版范围不完全一致 | P0 只生成和展示草稿；正式确认写入放 P1 | `[!]` 写入阶段前确认 |
| DEC-003 | 缺少真实采购制度文档 | 在 RAG 开始前由用户提供或确认可用材料 | `[!]` |
| DEC-004 | 缺少可靠产品白名单和兼容性数据 | P0 仅基于历史记录筛选，不宣称完整兼容性推荐 | 已接受边界 |
| DEC-005 | 延期与部分入库统计口径未冻结 | 延期按实际入库晚于预计日期，或预计日期已过且已采购未入库；缺少预计日期不计入延期分母；数量异常按有入库记录的申请统计 | 已按用户确认的默认口径固化 |
| DEC-006 | EchoMind 没有可确认的开源许可证 | 只参考设计；复制源码前必须获得授权或许可证 | `[!]` |
| DEC-007 | MySQL、Redis 不得与其他项目共用 | 使用 procurementMind 专属容器、数据卷、数据库/账号、Redis 实例与 Compose 项目标识；启动前检查宿主机端口冲突 | 已确认为硬性约束 |

---

# 八、执行记录

## 2026-08-04

- `[x]` 阅读 procurementMind 后端代码和五份基线文档。
- `[x]` 完成现有能力、缺口和开发边界分析。
- `[x]` 将远端代码稀疏检出到当前目录，保留本地五份文档。
- `[x]` 修正 README 和 AGENTS 中的仓库指向。
- `[x]` 完成 EchoMind 只读可复用性分析；未复制代码。
- `[x]` 创建本开发任务清单。
- `[x]` BAS-003：已从 `main@73f7912` 创建 `develop/agent` 分支；原有本地改动完整保留。
- `[x]` 记录基础设施隔离约束：procurementMind 不与其他项目共用 MySQL、Redis、数据卷或账号。
- `[x]` BAS-004：已建立 `procurement-mind` 专属 Compose 项目；MySQL 使用 `127.0.0.1:13307`、数据库 `procurement_mind`、账号 `procurement_mind_app`，Redis 使用 `127.0.0.1:16380`；容器、网络、数据卷均独立且健康。
- `[x]` BAS-005：已升级数据库至 Alembic `816575c8be0c (head)`，创建并校验全流程 TEST 数据；数据库结构专项测试通过（1 passed）。
- `[x]` BAS-006：完整后端测试通过（43 passed）；Ruff 规则检查通过；格式化 5 个文件后，99 个 Python 文件全部通过格式检查。
- `[x]` BAS-007：真实 HTTP 下 `/health`、`/ready`、Swagger、OpenAPI（35 条路径）、开发体验页和 10 项冒烟检查通过；需求人、楼长、采购员、仓管跨角色采购全流程专项测试通过；临时服务已关闭。
- `[x]` BAS-008：已保存 OpenAPI v0.1（35 条路径、96 个 Schema）、SHA-256 校验文件和 Git/验证基线说明；重复导出哈希一致。
- `[x]` BAS-009：已覆盖 OpenAPI 全部 39 个操作建立 Agent 复用与权限矩阵；分类为只读可用 10、需扩展 9、人工写入 14、禁止调用 6，并确定 P0 七项只读工具白名单。
- `[x]` M0：现有后端基线固化完成。
- `[x]` 将后续 P0 任务重组为 10 个开发批次；批次内连续执行，只在确认门禁或批次结束时暂停。
- `[x]` DEV-01：完成 M1/M2。新增独立 Agent 服务、结构化聊天骨架、安全签名后端客户端和会话封装；真实 HTTP 双进程验收通过；全仓 62 项测试、Ruff 和导入边界扫描通过。
- `[x]` DEV-02：完成 M3。引入官方 MCP Python SDK 1.x，建立标准 stdio Server/Client 和 7 项 P0 只读工具；身份通过可信子进程上下文注入，后端继续执行签名与数据权限校验；覆盖工具发现、非法参数、未知工具、超时、后端错误、Trace 和子进程故障；全仓 71 项测试、Ruff 和 134 个 Python 文件格式检查通过。
- `[x]` DEV-03：完成 M4。引入官方 LangGraph 1.x，建立五类 Router、结构化 Graph State、步骤/工具边界、实时采购状态链路、会话状态/快照映射和基础 Trace；真实链路已覆盖 Router → Graph → stdio MCP → 采购后端；模型供应商配置保持空白且不影响当前确定性链路；全仓 84 项测试、Ruff 和 143 个 Python 文件格式检查通过。
- `[-]` DEV-04：7 份 Markdown 知识源文件已到位并完成阅读；本地 RAG 推理模型已准备完成，完整 M5 尚未开发。
- `[x]` 按用户确认，在 DEV-04 等待材料期间先执行与其独立的 DEV-05。
- `[x]` DEV-05：完成 M6。新增白名单查询 DSL、查询/聚合、七类确定性风险信号、供应商履约和可解释相似案例四组只读接口；权限、范围、超时、扫描上限及非法输入边界均由后端执行；扩充稳定异常 TEST 数据并保存 OpenAPI v0.2（39 条路径、43 个操作、118 个 Schema）；全仓 94 项测试、Ruff 和 150 个 Python 文件格式检查通过。
- `[!]` DEV-06 确定性阶段：新增 4 项分析 MCP 工具（累计 11 项）、结构化 Planner、顺序/并行 Executor、一次计划调整、Analysis Agent、查询条件继承、表格/聚合/候选结构和固定评测集；真实 LangGraph → stdio MCP → 后端 → MySQL 标准答案为 9 笔、均价 1112.50、中位价 950.00、总金额 34350.00；全仓 106 项测试、Ruff 和 157 个 Python 文件格式检查通过。
- `[!]` DEV-06 当前门禁：确定模型供应商、模型名和可选兼容接口地址，并在本地 `.env` 填写密钥；随后实现供应商适配器和真实自然语言智能性评测，完成后才将 DEV-06 标记为 `[x]`。
- `[x]` DEV-06M：完成供应商无关模型网关。新增统一结构化请求/响应、适配器注册、超时、可重试错误、有限重试、工具参数白名单校验、脚本化假模型和通用评测报告；未安装或假定供应商 SDK。
- `[!]` DEV-07A：完成风险调查确定性阶段。Graph 强制风险信号先行，在工具预算内并行补查历史价格、履约和相似案例；结构化摘要区分事实、规则、待核实原因、信息缺口和人工核实项；程序 Reviewer 可发现数字篡改、来源缺失和审批越权；真实制度材料标记为不可用，真实模型语义审查仍待完成。与 DEV-06M 合并回归共 121 项测试通过，Ruff、173 个 Python 文件格式检查和 Agent/后端导入边界检查通过。
- `[!]` DEV-08A：完成 M9 模型无关 Web 入口。既有体验台新增智能协同页签，经开发 BFF 固定转发到独立 Agent；实现对话/任务状态、实际查询口径、汇总/分组/明细表格、风险事实/规则/人工核实/证据展示和知识未接入提示。真实浏览器链路验证统计标准答案与 91009 风险调查，页面无横向溢出且控制台无错误；同时修复统计日期被误持久化为采购申请 ID 的边界问题。全仓 124 项测试通过，Ruff 规则及 173 个 Python 文件格式检查通过。WEB-003 的真实文档版本、章节和引用仍等待 DEV-04 材料。
- `[!]` DEV-09A：完成 M10 模型无关部分。聊天响应新增请求级执行详情，统一还原路由、Graph、MCP、计划、Review、错误、步骤和耗时；无模型调用时明确记录 0 次调用且 Token/费用不可用。新增 Router 10 例、工具安全 8 例，并将既有 Planner 4 例和风险契约 3 例汇总为 25/25 的统一报告；RAG 质量明确标记 BLOCKED。建立只读 `deterministic-v0.1` 基线及回归差异检测，运行器不能自动更新基线。Web 可展开查看 5 个组件、Trace、工具和 Review。固定九条统计 TEST 数据的创建时间，长期未入库天数保持动态业务事实。全仓 128 项测试通过，Ruff、181 个 Python 文件格式检查、JavaScript 和真实浏览器验收通过。TRC/EVL 的 RAG 与真实 Token/费用仍等待材料和模型。
- `[!]` DEV-10A：完成模型无关的容错、安全和部署基础。模型与 MCP 接入独立异步熔断器，覆盖 `CLOSED/OPEN/HALF_OPEN`、并发单探针、恢复失败重开、超时和结构化错误；聊天任务增加总超时，模型、MCP 或混合链路失败时不再把部分结果描述为完整结论。外部知识固定作为不可信证据封装，白名单计划拒绝任意 SQL、身份/Trace 注入和越权工具参数。新增非 root 应用镜像和 MySQL、Redis、迁移、后端、Agent 专属 Compose 编排；容器内 UID 10001，镜像历史无密钥标记，四项长期服务均健康，容器内复杂查询真实链路成功。全仓 146 项测试、Ruff 和 190 个 Python 文件格式检查通过，确定性评测 25/25 且基线无差异，Compose 配置校验通过。验收后仅停止后端和 Agent，专属 MySQL/Redis 与数据卷保留。未启动空壳 Chroma、未推送镜像、未部署外部环境。
- `[!]` DEV-10B：固化模型无关交付演示和自动验收。新增统一演示报告及命令行脚本；DEM-002 真实容器下验证固定统计标准答案和同会话连续追问，第二轮正确继承日期、专业、品牌分组并新增延期供应商排除；DEM-003 验证 91009 的 4 项风险、5 次工具调用、6 项证据、程序 Review、人工核实项和“不替代人工审批结论”声明。报告结果为 2 PASSED、0 FAILED、1 BLOCKED；DEM-001 因真实知识材料缺失保持阻塞。补齐 README 和演示基线文档；全仓 148 项测试、Ruff 和 193 个 Python 文件格式检查通过，确定性评测 25/25 且基线无差异。未调用真实模型、未推送镜像、未发布服务。
- `[x]` RAG-000：在 `purchasing-agent` 环境安装 CPU 版 PyTorch、FlagEmbedding、Hugging Face Hub 及兼容的 Transformers；将 `BAAI/bge-m3` 和 `BAAI/bge-reranker-v2-m3` 下载到项目外的 `F:/AIModels`。Embedding/Reranker 使用独立封装，仅从本地路径加载并在服务启动时单例初始化；代码保留 `auto/cpu/cuda` 三种模式，当前机器 `.env` 固定 CPU，显式 CUDA 不可用时直接报错。指定“楼长驳回”样例真实 CPU 验证得到两条 1024 维归一化向量，相关/无关候选分数为 0.888307/0.000080；全仓 161 项测试、Ruff 和 201 个 Python 文件格式检查通过。未实现文档切分、索引、检索或完整 RAG。
- `[x]` 阶段 13：引入官方 `qdrant-client 1.18.0` 和单节点 `qdrant/qdrant:v1.18.2`；
  新增独立持久卷、健康检查、Qdrant 配置和幂等初始化脚本。真实 collection 状态为 green，
  包含 1024 维 Cosine `dense`、IDF `bm25` 以及 child/document/parent/chunk/version/status
  六项 Payload 索引；不兼容的已有 Schema 会拒绝静默覆盖。新增 MySQL
  `knowledge_document` / `knowledge_parent`、级联外键、Repository、结构化 Document/Parent/Child
  Schema 和 Alembic `b4f3a8c29d11`，本地数据库已无损升级到 head。知识专项与数据库测试 8 项
  通过，全仓 168 项测试通过，Ruff check、208 个 Python 文件格式检查和 Alembic check 通过。
- `[x]` 阶段 14：新增 7 份 Markdown 元数据及标题层级解析、稳定 Document/Parent/Child ID、
  语义优先 Parent-Child 切片和完整来源行号；字段、FAQ、风险等完整业务单元不会按机械字符边界
  拆散。新增索引状态迁移 `c9a17e6d42f0`、按文档 content hash 增量同步、全量重建、已删除源文档
  退役和失败可重试状态；Child 同时写入本地 BGE-M3 Dense 向量与 Qdrant 原生多语言 BM25 Sparse
  向量。真实 CPU 全量构建 7 个 Document、284 个 Parent 和 284 个 Child，MySQL/Qdrant 数量一致，
  所有文档均为 `ACTIVE/READY` 且无索引错误；未变化单文档复跑正确跳过。
- `[x]` 阶段 15：已实现配置化 Dense/BM25 双路召回、Qdrant Query API 服务端 RRF、本地 BGE
  Reranker、强制角色与 ACTIVE 状态 Metadata Filter、全局/设备范围过滤、可选 Query Rewrite
  降级、只读 READY Parent 回查和上下文预算。真实需求人问题已得到 15/15/12/5 级联候选，首条
  命中系统操作手册“处理驳回申请”，精排分数 `0.996599`；需求人/采购员真实可见 Child 分别为
  203/284。阶段专项 29 项、全仓 186 项测试通过，Ruff check、217 个 Python 文件格式检查和
  Alembic check 均通过。
- `[x]` 阶段 16：新增正式 `K1...Kn` Citation、来源文件/版本/章节/行号映射、无证据拒答阈值，
  以及包含原 Query、改写、Dense、Sparse、RRF、Rerank、最终证据、Parent 回查和 Citation 的
  请求级检索 Trace。建立 12 例真实固定集及只读基线，覆盖直接、口语、同义、多条款、FAQ、权限、
  负例、实时、Hybrid 和 RAG+Tool。真实 Recall@5/MRR：Dense `0.80/0.90`、Sparse
  `0.5833/0.67`、Hybrid `0.80/0.7833`、Hybrid+Reranker `0.80/0.95`；Route、Citation 和负例
  准确率均为 `1.0`。同时修复退役集成测试误影响正式知识数据的问题，重建并复验 7/284/284，
  完整测试后仍保持一致。

---

# 九、Agent / RAG 连续开发阶段（2026-08-07 审计后基线）

本节是阶段 12 起的当前执行基线。M0–M11 的已完成记录全部保留；其中尚未完成的 RAG、
Knowledge、模型、Web、Trace 和交付事项由下列阶段接续。当前明确决策优先于旧文档：向量库
固定为单节点持久化 Qdrant，不再实现 Chroma；知识源固定为 `knowledge/source/` 下 7 份独立
Markdown，不合并成长文档；业务实时事实继续只由采购后端 Tool/MCP 提供。

## 阶段 12：RAG 模型运行基线

- **主要工作**：封装本地 `BAAI/bge-m3` Embedding 与 `BAAI/bge-reranker-v2-m3` Reranker；
  支持 `cpu/cuda/auto`；模型只从项目外本地路径加载并在进程内复用。
- **依赖**：`purchasing-agent` Conda 环境；`F:/AIModels` 下两套完整权重。
- **完成标准**：CPU 生成 1024 维归一化向量；相关候选重排分数显著高于无关候选；缺失模型、
  不完整目录或不可用 CUDA 明确失败且不联网降级。
- **测试方式**：`tests/test_rag_local_models.py`、`scripts/verify_rag_models.py`、Pytest 与 Ruff。
- **当前状态**：`[x]` 2026-08-07；实测维度 1024、范数 `[1.0, 1.0]`、候选分数
  `0.888307 / 0.000080`。现有未提交实现属于本阶段成果，后续不得重复实现。

## 阶段 13：Qdrant 与知识库数据模型

- **主要工作**：增加单节点 Qdrant Compose 持久化服务；配置官方 Python Client；建立 MySQL
  `knowledge_document`、`knowledge_parent` 模型、Repository 与迁移；定义稳定 ID、版本、状态、
  来源、Hash、生效时间和完整 Parent 内容；创建同时包含 1024 维 Dense 与 IDF Sparse/BM25
  命名向量的 Child collection，以及必要 Payload 索引和健康检查。
- **依赖**：阶段 12；现有 MySQL/Redis/Compose；Qdrant 当前稳定 Query API。
- **完成标准**：迁移可升级；模型约束与级联关系正确；Qdrant 数据卷独立且服务健康；Collection
  Schema 幂等创建；Child Payload 至少包含 `child_id/parent_id/document_id/title/section_path/`
  `topic/chunk_type/version/status/content`；不引入 Chroma、Cloud 或集群。
- **测试方式**：模型/迁移/配置/Client 单元测试，Compose 配置校验，Qdrant 真实健康与 Collection
  契约测试，阶段相关 Pytest、`ruff check`、`ruff format --check`。
- **当前状态**：`[x]` 2026-08-07；MySQL 迁移、Qdrant 真实容器与 collection 契约、配置、
  Repository、Schema、专项和全量回归均通过。

## 阶段 14：Markdown 解析、Parent-Child 切片与索引同步

- **主要工作**：逐份解析 7 份 Markdown 的元数据表、标题层级和正文位置；按业务语义生成
  完整 Parent，并将规则、字段说明、步骤、FAQ、风险核实事项切成可独立回答的 Child；Embedding
  输入固定包含文档标题、章节路径、主题与正文；实现 `scripts/rebuild_knowledge.py`、单文档增量和
  全量同步，按 content hash 删除该文档旧 Parent/Child 后原子式重建，不以清库作为正常更新。
- **依赖**：阶段 13；7 份 Markdown；阶段 12 Embedding。
- **完成标准**：所有 Parent/Child 可追溯到源文件和标题路径；字段的用途/必填/要求/示例不被
  无上下文拆散；重复执行幂等；未变化文档跳过；变更文档只替换自身数据；MySQL 与 Qdrant
  失败时有一致性补偿或可重试状态。
- **测试方式**：解析/语义边界/稳定 ID/Hash/幂等/增量/全量/失败恢复测试，真实 7 文档构建验收，
  Pytest 与 Ruff。
- **当前状态**：`[x]` 2026-08-07；7 份文档真实构建得到 284 个 Parent/284 个 Child，MySQL
  与 Qdrant 精确计数一致；所有文档为 `ACTIVE/READY` 且无错误。单文档未变更复跑返回
  `skipped=1`；解析、语义边界、稳定 ID、失败恢复及退役流程均有自动化测试。阶段专项 18 项、
  全仓 179 项测试通过，Ruff check、214 个 Python 文件格式检查和 Alembic check 均通过。

## 阶段 15：混合检索、RRF、Reranker 与 Parent 回查

- **主要工作**：实现可选 Query Rewrite、Metadata Filter、Dense 与 Sparse/BM25 召回、Qdrant
  Query API RRF 融合、本地 Reranker 精排、按问题与 chunk type 决定的 Parent 扩展和上下文预算；
  Dense/Sparse/Fusion/Rerank TopK 全部配置化。
- **依赖**：阶段 14；阶段 12 模型；阶段 13 Qdrant。
- **完成标准**：默认约 15+15 召回、10–15 融合、4–6 精排但无业务代码硬编码；状态/版本/权限
  过滤有效；并非所有 Child 无条件扩展整段 Parent；模型不可用时有明确能力状态，不伪造结果。
- **测试方式**：Dense/Sparse/RRF/重排/过滤/Parent 扩展/配置边界测试及真实检索冒烟，Pytest 与 Ruff。
- **当前状态**：`[x]` 2026-08-07；所有 TopK、RRF k、批次与上下文预算均配置化；角色范围
  必填且只允许 ACTIVE 知识，无设备范围时只匹配全局知识。真实 CPU 链路得到 Dense 15、BM25
  15、RRF 12、精排 5 条，首条为“处理驳回申请”，分数 `0.996599`，上下文 755 字且未截断；
  Query Rewrite 未配置时如实使用原 Query。阶段专项 29 项、全仓 186 项测试及 Ruff/Alembic
  门禁全部通过。

## 阶段 16：RAG 引用、评测与检索 Trace

- **主要工作**：定义 Citation 与证据上下文；保存原 Query、改写 Query、Dense/Sparse 候选、RRF、
  Rerank、最终证据、Parent 扩展和 Citation Trace；建立覆盖直接问法、口语改写、同义表达、多条款、
  FAQ、权限、负例、实时问题及 RAG+Tool 混合问题的评测集；比较 Dense、Sparse、Hybrid、
  Hybrid+Reranker。
- **依赖**：阶段 15；现有 Trace/评测框架。
- **完成标准**：实现并报告 Recall@K、MRR、Route Accuracy、Citation Accuracy；回答引用包含文档、
  版本、章节和稳定证据 ID；无证据时明确无法确认；评测报告可重复运行且不自动篡改基线。
- **测试方式**：指标单测、固定检索集回归、引用映射与不可见证据测试、Trace 完整性测试、Pytest/Ruff。
- **当前状态**：`[x]` 2026-08-07；正式 Citation 与完整 Trace 已随检索结果返回并保存到本地评测
  工件。12 例真实 CPU 评测的 Recall@5/MRR 为 Dense `0.80/0.90`、Sparse `0.5833/0.67`、
  Hybrid `0.80/0.7833`、Hybrid+Reranker `0.80/0.95`；Route Accuracy、Citation Accuracy、
  Negative Accuracy 均为 `1.0`，只读 RAG 基线比较无差异。确定性评测 v0.2 为 25/25 且不再
  错误标记 RAG 阻塞；阶段专项 14 项、全仓 189 项测试通过，Ruff check、220 个 Python 文件
  格式检查与 Alembic check 均通过。测试后知识数据仍为 7 Document/284 Parent/284 Child。

## 阶段 17：业务 Tool / MCP 层收口

- **主要工作**：审计并按采购、产品、供应商、统计 namespace 收口现有 11 项只读工具；补齐 RAG
  与实时事实边界、结构化错误和可见性元数据；复杂统计继续使用受控 DSL；正式写操作只生成草稿或
  确认请求，复用业务 Service/HTTP API，不直接访问数据库。
- **依赖**：现有 M3/M6/M7；阶段 16 混合证据契约。
- **完成标准**：无任意 SQL、无 Repository/Session 导入、无模型可控身份/Trace 参数；实时状态、
  处理人、价格、采购记录、供应商和黑名单全部来自 Tool；RAG 与 Tool 冲突可识别并以业务后端为准。
- **测试方式**：工具发现/namespace/权限/注入/超时/混合冲突契约与真实后端集成测试、Pytest/Ruff。
- **当前状态**：`[x]` 2026-08-07；保留既有 11 项工具名称和单进程部署，通过 MCP 元数据完成
  `procurement/product/supplier/analytics` 逻辑隔离；所有工具继续只调用采购后端 HTTP API，
  身份与 Trace 仅由可信运行时注入。结果契约新增事实类型、后端权威性、可见性及结构化错误/
  可重试分类；新增稳定规则与实时事实冲突解析，实时 Tool 缺失时禁止以 RAG 推测。协议、权限、
  注入、超时、namespace 和冲突测试通过；契约基线见 `docs/baseline/tool-mcp-contract-v0.1.md`。

## 阶段 18：LLM Provider 与结构化输出

- **主要工作**：在现有 Provider 无关网关上补齐面向 Router/Rewrite/Planner/Compose/Review 的结构化
  Schema、超时、重试、熔断、用量采集和 Fake Provider；真实适配器仅在供应商、模型和 Key 可用后接入。
- **依赖**：现有 `agent_app/models`；阶段 16/17 输出契约。
- **完成标准**：无 Key 时全部模型无关路径可测试；Schema 非法输出受控失败；不以估算 Token/费用冒充
  真实用量；真实调用未执行时不得标记成功。
- **测试方式**：Fake Provider、结构化校验、超时/错误/重试/熔断/用量测试及 Pytest/Ruff；真实模型
  质量验收在缺少有效 Key/额度时标记 `[!]`，不阻塞后续确定性开发。
- **当前状态**：`[x]` 2026-08-07；保留现有 Provider 注册表、Fake Adapter、有限重试和共享熔断，
  新增 Router/Query Rewrite/Planner/Compose/Review 五类严格 Schema 与统一角色入口；请求 Schema
  与输出类型不一致、路由能力矛盾、Rewrite 标记矛盾、Review 状态非法及 Citation 越界均受控失败。
  新增运行时 `NOT_CONFIGURED/PROVIDER_NOT_REGISTERED/READY` 状态，Fake 不会自动进入生产注册表；
  Token 账本仅接受 `PROVIDER_REPORTED` 的完整 input/output/total，缺失时聚合值保持 `null`。
  模型专项 22 项、全仓 213 项测试通过，Ruff check 和 229 个 Python 文件格式检查通过；完整契约见
  `docs/baseline/llm-provider-contract-v0.1.md`。
- **真实模型补充验收**：`[x]` 2026-08-10；正式启动已按“配置 → OpenAI-compatible Adapter →
  Provider 注册 → ModelRuntime → StructuredModelRoles → LangGraph”自动组装，同时保留 Fake/Mock 注入。
  `qwen3.8-max` 已通过正式 Router、Compose、Review 与 Planner 调用，`glm-5.2` 已在 Primary 无效和
  Primary 超时场景由 Runtime 统一接管；Trace 记录 `primary_model/actual_model/fallback_used/
  fallback_reason`。`/ready` 改为反映 Runtime 初始化状态，不再以环境变量存在冒充就绪。正式验证脚本
  为 `scripts/verify_agent_llm_flow.py`，Provider 单项验证脚本为 `scripts/verify_llm_provider.py`。

## 阶段 19：LangGraph Agent 编排

- **主要工作**：在现有 LangGraph 上形成 `load_context → route → plan/retrieve/tools →
  sufficiency_check → compose → review → confirmation(按需) → save/finalize`；逻辑角色限定为 Router、
  Knowledge、Analysis、Review 和轻量 Form Prefill；使用现有 `conversation_id` 作为 thread_id，并复用
  MySQL/Redis Agent Session，不建立第二套业务状态。
- **依赖**：阶段 16–18；现有 Graph/Session。
- **完成标准**：知识、实时、混合、复杂查询、风险和预填均可路由；LangGraph 不替代采购状态机；
  Review 只审查证据、遗漏、事实/分析边界、越权、可见性、RAG/Tool 冲突和人工确认，不重复确定性规则。
- **测试方式**：节点/条件边/循环与预算/恢复/混合路径/降级/Review 契约和端到端测试、Pytest/Ruff。
- **当前状态**：`[x]` 2026-08-07；现有 Graph 已扩展为 `load_context → route → knowledge/
  realtime/analysis/risk/form_prefill → sufficiency_check → compose → review → confirmation → finalize`。
  Knowledge 和 Hybrid 正式接入本地 RAG Citation，实时事实仍只来自 MCP；模型角色可接管 Router/
  Rewrite/Compose/Review，失败时记录受控错误并回退确定性链路。`conversation_id` 已作为 thread_id，
  不新增 Checkpointer；`pending_action` 和 `awaiting_confirmation` 复用采购后端 Conversation State 与
  快照。预填只生成草稿，confirmation 明确 `executed=false`。专项 47 项、全仓 218 项测试、Ruff
  check、231 个 Python 文件格式检查及确定性评测 25/25 通过；真实本地 RAG→Graph 得到 5 条引用、
  充分性与 Review 均通过。基线见 `docs/baseline/langgraph-orchestration-v0.1.md`。
- **真实编排补充验收**：`[x]` 2026-08-10；正式 LangGraph 已通过真实模型完成知识问答、Model
  Router、Tool 后 Compose 和复杂分析。Planner 仅在 `COMPLEX_QUERY` 调用，简单知识问答直接 RAG，
  简单实时查询直接 Tool；Planner 调用和完整计划进入 Graph Trace。复杂分析 Trace 已确认
  `model_planner.model_used=true`、`actual_model=qwen3.8-max`，故意配置无效 Primary 时 Router、Compose、
  Review 均自动使用 `glm-5.2`。单次复杂回归中曾出现 Primary Review 超时且 Fallback 返回空结构化
  正文，Graph 按安全策略使用确定性 Review 并保留错误，未伪造模型成功。

## 阶段 20：Web Agent 交互与 HITL

- **主要工作**：扩展现有 Web 智能协同页展示知识引用、检索 Trace 摘要、混合证据、预填草稿、
  确认卡片和任务恢复；浏览器只走后端 BFF，不保存身份网关 Secret；平台适配保持解耦。
- **依赖**：阶段 19；现有 Web/BFF。
- **完成标准**：提交申请、审批通过/驳回、最终供应商、正式采购结果、入库及其他状态变更均在明确
  人工确认后由现有后端接口执行；Agent 只能查询、分析、推荐、预填和生成草稿；取消/过期/重复确认安全。
- **测试方式**：前端交互与可见性测试、身份 Secret 扫描、HITL 状态/幂等/并发/取消测试、真实浏览器
  冒烟及后端/Agent Pytest、Ruff。
- **当前状态**：`[x]` 2026-08-09；Web 已展示 Citation、RAG Trace 摘要、Review、混合结果、
  预填草稿和确认卡片；BFF 仅转发白名单测试身份且浏览器不保存网关 Secret。Agent 新增身份/会话绑定、
  一次性 Token、15 分钟有效期、确认/取消/过期/重复/并发安全契约，确认后仅通过现有采购后端受控
  API 执行，处理结果复用 Agent Session 与 MySQL 快照。HITL/BFF/UI 定向 26 项、全量 226 项
  Pytest、Ruff、格式检查、前端语法及真实浏览器冒烟均通过；契约见
  `docs/baseline/web-hitl-contract-v0.1.md`。真实 Provider 未配置，不影响本阶段确定性验收。

## 阶段 21：端到端测试、安全、部署与项目交付

- **主要工作**：完成 Qdrant/MySQL/Redis/Backend:8000/Agent:8100 Compose 部署、健康与就绪检查、
  数据持久化、备份/恢复说明、端到端评测、安全扫描、故障降级、README/设计文档/OpenAPI/验收演示；
  清理旧 Chroma 配置和陈述；模型权重、`.env` 与密钥不进入 Git。
- **依赖**：阶段 12–20。
- **完成标准**：全量测试、Ruff、确定性评测、RAG 评测和三类核心演示通过；Qdrant 重启后索引保留；
  RAG 与实时事实严格分离；无高风险权限/提示注入/任意 SQL/Secret 泄漏；阻塞的真实模型验收单独列明。
- **测试方式**：全量 Pytest、`ruff check .`、`ruff format --check .`、Compose config/health、真实 7 文档
  索引与检索、Web 端到端、故障注入和交付脚本。
- **当前状态**：`[-]` 2026-08-10；已完成最小真实 Agent 端到端闭环：通过正式 `/api/v1/chat`
  使用同一 `conversation_id=93028` 跑通知识问答、实时采购单查询和 RAG + Tool 混合查询。知识场景
  检索 7 文档 Qdrant 正式索引并返回 5 条 Citation；实时场景通过 MCP `get_purchase_request(91003)`
  读取 `REJECTED`、当前处理人和“预算说明不足”；混合场景从会话状态恢复 `requirement_id=91003`，
  同时完成 `knowledge_retrieval` 与 Tool 调用。Router/Compose/Review 已由真实 Provider 执行，Trace
  保留 route、retrieval、tool、模型和错误信息。CPU RAG + 远程模型的混合链路实测超过 120 秒，当前
  开发机通过既有 `TASK_TIMEOUT_SECONDS=300` 配置验收。验证脚本为 `scripts/verify_agent_e2e.py`。
  阶段 21 其余 Compose 全栈交付、安全扫描、备份恢复和最终文档仍待完成。

## 阶段 22：React Web 前端第一版

- **主要工作**：以《数据中心设备采购智能协同 Agent—前端设计文档》V0.1 为基线，将既有原生
  JavaScript 开发体验台升级为 React + TypeScript + Vite + React Router + Ant Design +
  Ant Design X 的正式 Web 第一版；实现统一 Layout/Theme、动态角色菜单、工作台、智能助手、
  我的采购、新建与详情、楼长/采购员/仓管岗位页面和个人信息；统一 Backend/Agent Client、身份状态、
  Loading/Empty/Error 与开发环境 BFF 安全边界。
- **依赖**：阶段 19–20 的 LangGraph、Agent API、HITL 与现有 Backend API；开发 BFF
  `/demo-api/proxy`、`/demo-api/agent-chat`、`/demo-api/agent-actions/*`。
- **完成标准**：角色菜单与页面完整；Agent 真实对话、RAG 引用、Tool 结果和 HITL 可交互；采购列表、
  新建/保存/提交、详情、岗位任务和供应商数据按真实权限联调；Mock 集中且显式标记；浏览器不包含
  API Key 或 Gateway Secret；TypeScript、Lint、Build、基础测试和关键浏览器流程通过。
- **测试方式**：`npm run typecheck`、`npm run lint`、`npm run test`、`npm run build`；分别切换
  APPLICANT、BUILDING_MANAGER、PURCHASER、WAREHOUSE_MANAGER 验证菜单与岗位页；在真实 Backend
  8000 / Agent 8100 上验证 Agent、申请列表、创建/保存/提交、详情和错误状态；检查构建产物 Secret。
- **当前状态**：`[x]` 2026-08-10；完成 React 正式第一版及蓝白企业 Theme，交付工作台、Ant Design X
  智能助手、我的采购、新建/编辑/详情、楼长/采购员/仓管岗位页、供应商和个人信息；角色菜单由真实
  `/api/v1/users/me` 动态生成，所有业务请求经统一 BFF Client，浏览器不持有 Gateway Secret。
  浏览器实测 APPLICANT、BUILDING_MANAGER、PURCHASER、WAREHOUSE_MANAGER 菜单与真实待办数据；
  Agent 真实查询 91003 后展示 Tool 结果和业务回答；从 Web 创建并提交测试申请 91041，详情正确显示
  `PENDING_REVIEW`、当前楼长和操作历史。TypeScript、ESLint、Vitest 1/1、生产 Build、Demo/BFF
  Pytest 8/8、Ruff 与格式检查均通过；构建产物 Secret 扫描通过，干净浏览器控制台 0 warning/error，
  1280px 无横向溢出。当前后端仍只有 `APPLICANT` + 楼宇归属可发起申请，供应商风险也缺少楼宇范围
  列表 API；前端对两处均显式说明且未伪造 Mock。构建仅保留 1.45 MB 单 chunk 优化提示。

## 阶段 23：Web 前端业务修复与 Agent 上下文协同

- **主要工作**：恢复 Agent、楼长审批、采购登记和仓库入库等真实业务闭环；建立 Agent SSE 流式事件、
  统一业务错误映射、岗位待办 Badge、供应商列表与楼宇风险正式 API、业务字段/枚举中文化、ADMIN 独立
  信息架构，以及采购详情中的上下文智能辅助 Drawer。所有写操作继续通过 Backend 状态机、权限、
  `expected_version`、`action_token` 与 HITL 执行，不以 Mock 冒充缺失能力。
- **依赖**：阶段 22 Web 第一版；阶段 19–20 的 LangGraph、会话、Tool/RAG、HITL；现有采购、身份、
  供应商、黑名单、楼宇和操作记录模型；真实 MySQL/Redis/Qdrant、Backend 8000、Agent 8100。
- **完成标准**：14 项问题均有根因、正式实现和回归证据；Agent 四类请求有实时业务化状态且连接正确
  结束；审批/采购/入库可按真实 Schema 完成；ADMIN 仅拥有管理视角和只读采购/供应商能力；上下文
  Assistant 只传页面类型与业务 ID，权威事实仍由 Tool 获取；全站无 raw snake_case、英文状态和技术
  异常直出；无 Secret 泄漏、重复提交或越权。
- **测试方式**：Backend/Agent Pytest、`ruff check .`、`ruff format --check .`；Frontend TypeScript、
  ESLint、Vitest、Production Build；真实服务下验证 Agent 知识/实时/Hybrid/复杂/错误/超时/流式，四类
  岗位流程、供应商和 ADMIN 权限；最终使用真实浏览器检查 Network、SSE 关闭、控制台、表单和全流程。
- **当前状态**：`[x]` 2026-08-11；阶段 23 已完成并通过全栈回归。初始审计中真实 Web BFF 知识问答耗时
  97.1 秒后成功，Trace `3c9f9275-e932-4920-8df1-f495bf38716b`：Router 11.1 秒、CPU RAG 42.9 秒、
  Compose 15.3 秒、Review 26.5 秒；当前为单次 JSON 响应且期间无状态事件。配置同时存在 Agent 总任务
  300 秒、BFF 130 秒的反向超时风险。该请求被模型误路由为 HYBRID、缺少采购单 ID 后 Tool 跳过，
  进一步增加了无效链路。尚未将阶段或任一实现任务提前标记完成。

| ID | 可验收任务 | 依赖 | 验收重点 | 状态 |
|---|---|---|---|---|
| WEBFIX-001 | Agent 无响应全链路定位、耗时 Trace 与 timeout 层级修复 | 阶段 19–22 | 四类请求均结束；Trace 可定位节点；下游时限不短于 Agent 总时限 | `[x]` 2026-08-11 |
| WEBFIX-002 | Agent SSE 状态与最终文本流式契约、BFF 转发、前端取消/重试 | WEBFIX-001 | 真实事件、连接关闭、页面卸载取消、error/timeout 测试 | `[x]` 2026-08-11 |
| WEBFIX-003 | 楼长审批 Schema/条件表单/通过与驳回闭环 | WEBFIX-001 | 所有必填字段对齐；合同条件校验；写入保留版本与幂等 | `[x]` 2026-08-11 |
| WEBFIX-004 | 仓库入库数量边界与业务提示修复 | WEBFIX-001 | requested-1、requested、requested+1 前后端一致 | `[x]` 2026-08-11 |
| WEBFIX-005 | 统一 Backend field errors 与前端中文业务错误映射 | WEBFIX-003–004 | 全站技术字段、异常和 HTTP body 不直出 | `[x]` 2026-08-11 |
| WEBFIX-006 | 供应商默认分页列表与名称远程选择器 | WEBFIX-005 | 无 keyword 可分页；采购登记不要求用户输入 ID | `[x]` 2026-08-11 |
| WEBFIX-007 | 楼宇范围供应商风险正式只读 API 与页面 | WEBFIX-006 | 楼宇/角色权限、有效状态、原因、时间与来源均来自真实数据 | `[x]` 2026-08-11 |
| WEBFIX-008 | 楼长/采购员快捷入口与三岗位真实 Badge 集中刷新 | WEBFIX-003–007 | total 驱动、0 隐藏、操作后刷新、无高频重复请求 | `[x]` 2026-08-11 |
| WEBFIX-009 | 详情、列表、历史、供应商字段和枚举集中中文化 | WEBFIX-005 | 无 raw snake_case、英文业务枚举和数据库 ID 输入 | `[x]` 2026-08-11 |
| WEBFIX-010 | ADMIN 独立菜单、真实工作台和员工管理正式 API | WEBFIX-006 | Employee CRUD/停用、楼宇/角色、真实统计、权限测试；不伪造密码体系 | `[x]` 2026-08-11 |
| WEBFIX-011 | ADMIN 全部采购清单与供应商只读查询 | WEBFIX-010 | 全局分页/搜索/筛选/详情；无审批、采购、入库写入口 | `[x]` 2026-08-11 |
| WEBFIX-012 | Agent 受控 `ui_context` 契约与权威事实回查 | WEBFIX-002 | 仅 page_type/requirement_id；Tool 重新查询；draft 明确非权威 | `[x]` 2026-08-11 |
| WEBFIX-013 | 通用 Context Assistant Drawer、快捷问题和建议应用表单 | WEBFIX-012 | 详情/审批/采购按角色复用；应用只改草稿；提交仍由用户确认 | `[x]` 2026-08-11 |
| WEBFIX-014 | 全站业务 UI 审计与真实浏览器完整 E2E | WEBFIX-001–013 | 需求列出的 Agent、岗位、供应商、ADMIN、权限、控制台全部通过 | `[x]` 2026-08-11 |

**完成结果（2026-08-11）**：Agent 已使用真实 SSE 契约贯通 Agent Service、Backend BFF 与 React，浏览器知识问答可持续展示检索状态并在 CPU RAG 完成后返回正文及 5 条来源；实时、Hybrid、复杂分析与 Primary/Fallback 均已通过正式 Graph Trace 验证。审批、驳回、采购、入库三类岗位写操作均继续携带 `expected_version`/`action_token` 并由 Backend 状态机校验；入库数量 `< / = / >` 三个边界已回归。供应商默认分页、远程名称选择、楼宇风险和 ADMIN 员工管理/全局只读查询均使用正式 API。上下文助手只传 `page_type`、`requirement_id` 和明确标记的 `user_draft`，事实由 Tool 回查；结构化候选只预填当前表单，不自动写业务状态。新增 Alembic `ef82a4d11c73` 管理管理员操作审计日志；当前身份仍为平台身份/HMAC，不伪造本地密码。全量 Pytest、Ruff、TypeScript、ESLint、Vitest、Production Build 和真实浏览器回归通过；全新浏览器页面控制台 warning/error 为 0。当前演示库没有非 TEST 历史采购，供应商推荐会如实返回空候选，未使用 Mock 填充。

---

# 十、当前下一步

当前应按批次执行：

1. 阶段 23 的 WEBFIX-001 → WEBFIX-014 已全部完成；后续回到阶段 21 的 Compose 全栈部署、安全、备份恢复与最终交付，不进入办公平台接入。
2. 阶段 21 的 Compose 全栈部署、安全与故障降级、备份恢复、评测汇总和最终交付文档继续保留，
   不在本次前端阶段扩展处理。
3. 真实主 LLM Provider、Embedding、Reranker、7 文档 Qdrant 索引和三类核心 Agent 路径均已完成
   实际调用验收；仍需持续观察远程模型超时及 Fallback 偶发空结构化正文。

当前 7 份 Markdown 作为知识库唯一源文件，Word 文件仅用于阅读、汇报和展示。不得跳过 Metadata、
权限和可追溯性约束。知识库 MySQL 表由知识同步边界管理；Agent 的业务 Tool/MCP 仍不得直接访问
采购业务 MySQL 或 Redis。
