# LLM Provider 与结构化输出契约基线 v0.1

更新时间：2026-08-07

## 当前能力

- Provider SDK 与业务工作流解耦：适配器只实现 `complete_structured`，由注册表按配置选择。
- `StructuredModelRunner` 统一处理超时、可重试错误、结构化输出重试和共享熔断器。
- `StructuredModelRoles` 为 Router、Query Rewrite、Planner、Compose、Review 提供统一入口。
- 角色输入作为 JSON user message 传递，不插值到 system instruction。
- Fake Adapter 只服务自动化测试，生产注册表不会自动注册或选择 Fake。

## 结构化输出

| 角色 | Purpose | 输出 |
| --- | --- | --- |
| Router | `ROUTER` | 路由、置信度、理由、是否需要知识与实时工具 |
| Query Rewrite | `QUERY_REWRITE` | 改写问题、是否变更、保留的实体 |
| Planner | `ANALYSIS_PLAN/ANALYSIS_REPLAN` | 既有严格 `AnalysisPlan` 与白名单 Tool 参数 |
| Compose | `COMPOSE` | 答案、`K<n>` 引用、限制、是否需要人工确认 |
| Review | `REVIEW` | 是否通过、七类 Review 问题、严重度、人工确认、修订答案 |

Runner 在调用前校验请求声明的 JSON Schema 与目标 Pydantic 类型一致；输出包含额外字段、非法枚举、
不一致的路由能力、非法 Review 状态或不可见 Citation 时受控失败。

## 错误与韧性

- 身份/参数等不可重试 Provider 错误立即失败。
- 超时、上游临时错误和结构化输出不合法按配置进行有限重试。
- 连续基础设施故障达到阈值后共享熔断；熔断打开时不继续调用适配器。
- 未配置模型返回 `NOT_CONFIGURED`；配置了未知供应商返回 `PROVIDER_NOT_REGISTERED`。
- 不自动选择供应商、不联网下载 SDK、不把 Fake 调用标记为真实模型验收。

## 用量真实性

Token 仅接受 Provider 完整返回的 input/output/total，且标记 `PROVIDER_REPORTED`。任一调用没有真实
用量时，聚合 Token 保持 `null` 且 `usage_complete=false`。当前不估算 Token 或费用。

## 当前阻塞

尚未确认生成模型供应商、模型名称、有效 API Key 和额度，因此真实 Provider 适配器与线上质量验收
保持阻塞。该阻塞不影响模型无关契约和后续确定性工作流开发。

## 验收命令

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' -m pytest `
  tests\test_model_gateway.py tests\test_model_roles.py `
  tests\test_circuit_breaker.py tests\test_execution_details.py -q
```
