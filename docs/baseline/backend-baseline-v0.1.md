# procurementMind 后端基线 v0.1

## Git 基线

- 记录日期：2026-08-04
- 开发分支：`develop/agent`
- 基础提交：`73f7912494096bd04a4f52023bd535d437dd91ea`
- 工作区状态：包含 M0 阶段尚未提交的配置、文档和格式化改动

本记录中的 OpenAPI 契约由当前工作区代码生成。基础提交只用于定位远端后端起点，
不能单独代表当前工作区的完整内容。

## OpenAPI 契约

- 文件：`openapi-backend-v0.1.json`
- 标题：`Procurement Agent`
- API 版本：`0.1.0`
- 路径数量：35
- Schema 数量：96
- SHA-256：`39f2f39e7253f767783719f89a279fe4ce97b6168c5aafa76be89d6f146b03ec`
- 生成命令：

  ```powershell
  & 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\export_openapi.py
  ```

## 验证结果

- 完整后端测试：43 passed
- Ruff 规则检查：通过
- Ruff 格式检查：99 files already formatted
- `/health`：ok
- `/ready`：MySQL、Redis 均为 ok
- Swagger 和 OpenAPI：HTTP 200
- 跨角色采购主流程：通过

## 用途

后续 Agent、MCP 和分析接口开发以本契约为变更对照。修改后端路由或 Schema 时，
重新生成 OpenAPI，并在评审中说明新增、兼容和破坏性变化。
