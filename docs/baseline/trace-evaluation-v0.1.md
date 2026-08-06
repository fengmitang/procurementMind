# Trace、执行详情与确定性评测基线 v0.1

记录日期：2026-08-06

## 1. 请求级执行详情

Agent `POST /api/v1/chat` 的 `data.execution` 汇总同一个请求已经产生的执行事实：

- `trace_id`、路由、完成状态、总耗时、Graph 步骤数、工具数和证据数。
- Graph、MCP、MODEL、RAG、REVIEW 五个组件的状态与说明。
- Graph Trace 事件、MCP 工具名称、受控参数、来源、结果状态和耗时。
- Analysis 执行计划、风险程序 Review 和受控错误。
- 模型供应商、型号、调用次数、Token 和费用。

当前没有真实模型调用，模型调用数为 0，Token 和费用为 `null`。这表示“没有真实计量值”，
而不是估算为零。RAG 真实材料尚未接入时状态为 `NOT_CONFIGURED`。

执行详情由现有 Graph 结果即时汇总，不新建第二套数据库或 Trace 存储；会话状态仍由采购
后端保存。前端“智能协同”页可以展开查看路由、计划、工具、Review 和错误。

## 2. 确定性评测

运行命令：

```powershell
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\run_deterministic_evaluations.py
```

当前套件：

| 套件 | 用例数 | 当前结果 | 范围 |
|---|---:|---|---|
| router | 10 | 10/10 | 五类路由、日期/编号边界、履约和相似案例 |
| tool-security | 8 | 8/8 | 白名单参数、身份/Trace 注入、非法 ID、原始 SQL |
| analysis-planner | 4 | 4/4 | 查询、履约、相似案例和聚合计划 |
| risk-contract | 3 | 3/3 | 期望与禁止风险集合契约 |
| rag-quality | 0 | BLOCKED | 等待真实采购制度材料 |

可执行用例合计 25/25 通过。RAG 阻塞项不计入通过率，也不会由虚构文档替代。

## 3. 基线回归策略

只读基线位于 `docs/baseline/deterministic-evaluation-baseline-v0.1.json`。比较内容包括：

- 套件是否缺失或意外新增。
- 用例数量。
- 套件状态。
- 最大失败数和最低通过率。

运行器没有自动更新基线的参数。任何基线变更必须先由用户确认，再明确修改基线版本和预期。
真实模型接入后另建 MODEL 模式基线，不覆盖当前确定性基线。

## 4. TEST 数据时间边界

采购统计标准答案依赖的九条 TEST 采购记录固定创建于 2026-08-05，以保证查询结果长期为
9 笔、平均单价 1112.50、中位价 950.00、总金额 34350.00。长期未入库天数仍按当前日期
动态计算，因为这是业务风险事实，不应冻结为固定数字。
