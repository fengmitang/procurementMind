# 容错、安全与本地部署基线 v0.1

更新时间：2026-08-06

## 已实现范围

- 模型调用：单次超时、有限重试、结构化错误、独立熔断器。
- MCP：启动、发现、调用和传输错误分类；调用超时；独立熔断器。
- 熔断状态：`CLOSED`、`OPEN`、`HALF_OPEN`，恢复窗口只放行一个探针。
- 任务边界：聊天任务受总超时控制，超时不会保存虚构的 Agent 结论。
- 降级表达：模型、MCP 或混合链路不完整时保留错误与组件状态，不声称形成完整结论。
- Prompt 边界：外部知识片段只能作为不可信证据进入 user 消息，不能成为 system/tool 指令。
- 工具边界：模型计划只能使用白名单工具和结构化参数，拒绝 SQL、身份注入和 Trace 注入。
- 容器：MySQL、Redis、迁移、采购后端和 Agent 使用同一个专属 Compose 项目；应用镜像非 root 运行。

## 配置项

```dotenv
MCP_STARTUP_TIMEOUT_SECONDS=60
MCP_TOOL_TIMEOUT_SECONDS=15
MCP_CIRCUIT_FAILURE_THRESHOLD=3
MCP_CIRCUIT_RECOVERY_TIMEOUT_SECONDS=30
MODEL_TIMEOUT_SECONDS=60
MODEL_STRUCTURED_OUTPUT_RETRIES=1
MODEL_CIRCUIT_FAILURE_THRESHOLD=3
MODEL_CIRCUIT_RECOVERY_TIMEOUT_SECONDS=30
TASK_TIMEOUT_SECONDS=120
```

模型供应商、模型名和密钥仍可留空。密钥只填写在不提交 Git 的本机 `.env` 或
`.env.docker` 中，不能写入 Dockerfile、Compose 默认值或仓库文档。

## 本地验证

```powershell
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker build agent
docker compose --env-file .env.docker up -d --no-build
docker compose --env-file .env.docker ps
```

验收结果：

- 镜像运行用户：`procurement`，容器内 UID `10001`。
- 镜像构建历史：未发现数据库、Redis、身份网关或模型密钥配置项。
- MySQL、Redis、采购后端和 Agent：健康。
- 数据库迁移：成功执行并退出。
- 复杂查询冒烟：容器内链路成功调用 1 次 stdio MCP 工具并形成完整确定性结果；模型调用 0 次。

本地验证结束后，只停止应用容器，保留采购项目专属基础设施：

```powershell
docker compose --env-file .env.docker stop backend agent
```

不要执行会删除专属数据卷的命令，除非已确认需要清空采购开发数据。

## 尚未完成

- 未配置真实模型，因此未执行供应商模型质量、真实 Token 和费用验收。
- 未提供真实知识材料，因此 RAG、知识引用和知识注入的真实模型评测保持阻塞。
- Chroma 仅预留 Agent 独立数据卷和配置位置；实际索引代码完成前不启动独立服务。
- 未推送镜像、未部署外部环境、未执行生产发布。
