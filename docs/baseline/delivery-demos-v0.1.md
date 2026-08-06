# 模型无关交付演示基线 v0.1

更新时间：2026-08-06

## 前置条件

1. 使用 `F:\Anaconda\envs\purchasing-agent` 环境，不在该环境中重复安装依赖。
2. `.env.docker` 已配置采购项目专属 MySQL、Redis 和身份网关密钥。
3. 已执行 `scripts/seed_demo_data.py`，TEST 数据校验通过。
4. Compose 中 MySQL、Redis、后端和 Agent 均为健康状态。

```powershell
docker compose --env-file .env.docker up -d --no-build
& 'F:\Anaconda\envs\purchasing-agent\python.exe' scripts\run_delivery_demos.py --output .tmp\delivery-demo-report.json
```

脚本退出码为 0 表示没有失败项；等待真实输入的 `BLOCKED` 项不会被伪装成失败或通过。

## DEM-002：复杂查询与连续追问

第一轮：

> 统计 2026-08-01 到 2026-08-05 算力服务器各品牌采购数量、平均单价、中位价和总金额

固定 TEST 标准答案：

| 指标 | 结果 |
|---|---:|
| 数量 | 9 |
| 平均单价 | 1112.50 |
| 中位价 | 950.00 |
| 总金额 | 34350.00 |
| 品牌分组 | TEST-BRAND |

第二轮使用同一个外部会话：

> 再排除有延期的供应商，保持刚才日期、专业和按品牌统计口径

验收要求：

- 会话编号不变。
- 日期、设备专业和品牌分组继承第一轮确认口径。
- 新增 `exclude_delayed_suppliers=true`。
- 结果不是部分成功，模型调用数为 0。
- 当前 TEST 标准答案为数量 5、平均单价 950.00、中位价 950.00、总金额 6650.00。

## DEM-003：审批风险调查

问题：

> 调查采购申请 91009 的审批风险

验收要求：

- 路由为 `RISK_INVESTIGATION`，申请编号为 91009。
- 至少命中 `PRICE_DEVIATION`。
- 每项风险带后端事实、规则阈值、来源和人工核实项。
- 成功证据带来源和同请求 Trace，程序 Review 通过。
- 回答明确声明“风险调查结果不替代人工审批结论”。
- 因真实制度材料缺失，`complete=false` 且 `knowledge_evidence_available=false`。
- 模型调用数为 0。

当前真实容器验收命中 4 项风险、执行 5 次工具调用并返回 6 项证据。风险集合会随 TEST
数据口径显式更新；`PRICE_DEVIATION`、证据完整性和非审批结论声明是固定契约。

## DEM-001：知识与业务混合问答

状态固定为 `BLOCKED`。解除条件是用户提供真实采购制度、流程或历史案例材料，并完成：

- 文档解析、版本与权限 Metadata；
- Chroma 索引及权限过滤；
- 引用章节和来源展示；
- Prompt Injection 与真实模型知识质量评测。

材料到位前不得用编造制度或通用常识把该项标记为通过。

## 2026-08-06 验收结果

- 总计：3
- 通过：2
- 失败：0
- 阻塞：1（DEM-001）
- DEM-002：两轮 Trace 独立且条件继承通过。
- DEM-003：程序 Review、证据来源、人工核实与非审批声明通过。
- 未调用真实模型，未推送镜像，未发布外部服务。
