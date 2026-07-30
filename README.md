# Procurement Agent Backend

数据中心采购流程自动化 Agent 的 FastAPI 后端。

## 开发环境

- Python：`F:\Anaconda\envs\purchasing-agent\python.exe`
- FastAPI：本机 Conda 环境
- MySQL：独立 Docker 容器，`127.0.0.1:3307`
- Redis：独立 Docker 容器，`127.0.0.1:6380`

项目不会连接或复用本机已有 MySQL、其他 Docker 网络、数据卷或 Redis。

## 初始化

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\bootstrap_env.py
docker compose --env-file .env.docker config
docker compose --env-file .env.docker up -d
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m uvicorn app.main:app --reload
```

## 检查

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m pytest
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m ruff check .
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m ruff format --check .
```

健康检查：

- `GET /health`
- `GET /ready`

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

外部系统联调方式见
[后端接口联调说明](docs/后端接口联调说明.md)。

## 数据安全

- `.env` 和 `.env.docker` 均不提交 Git。
- 不要执行 `docker compose down -v`，除非明确需要删除本项目全部开发数据。
