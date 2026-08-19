# Full Synthetic Demo Dataset

`scripts/seed_demo_dataset.py` 为开发 MySQL 构造一套固定、完全虚拟的采购业务环境。它用于页面人工验收、权限检查、推荐、复杂查询与风险调查，不替代 `TEST-*` fixture 或固定 Acceptance Dataset。

## 数据规模与命名空间

- 28 名员工，账号编号 `DEMO-E*`，平台身份 `WEB / demo_user_*`
- 9 栋楼宇（复用系统的“一号楼”至“六号楼”，以固定 DEMO ID 补齐“七号楼”至“九号楼”）
- 36 家供应商，以 `DEMO-CREDIT-*` 社会信用代码识别，其中 32 家启用、4 家停用
- 210 张采购申请，编号 `DEMO-PR-*`
- 12 条黑名单、25 条通知、12 个 Agent 会话、4 份未向量化的知识文档
- 会话、消息、通知和知识分别使用 `demo_conversation_*`、`demo_message_*`、`demo_notification_*`、`demo_doc_*` 命名空间

`--reset` 只按这些稳定标识删除 DEMO 数据；不会删除 `TEST-*`、非 DEMO 业务数据或 migration 元数据。旧 `DEMO-HIST-*` 推荐样本也会由统一入口清理。

## 状态与设备分布

状态固定为：DRAFT 20、PENDING_REVIEW 25、REJECTED 15、PENDING_PURCHASE 25、PURCHASING 25、PENDING_WAREHOUSE 35、COMPLETED 65。

数据覆盖 `DEVICE_PROFESSIONS` 的全部 17 类，每类 8 条以上；服务器、UPS、传输、运维工具、冷水机组和列间空调更密集。全部数量为正整数，时间覆盖此前约 12 个月。

## Demo 账号

| 名称 | 平台用户 ID | 角色/范围 |
|---|---|---|
所有账号的平台类型均为网关合法值 `WEB`。

| 演示需求人 | `demo_user_001` | APPLICANT，1号楼 |
| 演示楼长A | `demo_user_002` | BUILDING_MANAGER，1–2号楼 |
| 演示采购员 | `demo_user_003` | PURCHASER |
| 演示仓管员 | `demo_user_004` | WAREHOUSE_MANAGER |
| 演示管理员 | `demo_user_005` | ADMIN |
| 演示需求人兼楼长 | `demo_user_006` | APPLICANT + BUILDING_MANAGER，1–2号楼 |
| 演示楼长兼采购员 | `demo_user_007` | BUILDING_MANAGER + PURCHASER，3–4号楼 |
| 演示采购员兼仓管 | `demo_user_008` | PURCHASER + WAREHOUSE_MANAGER |

楼长 B/C/D 分别覆盖 3–4、5–6、7–9 号楼；普通业务员工分散在九栋楼中。

## 推荐验收场景

- 需求人：服务器全历史的浪潮 `NF5180M6` 频次最高；近两个月华为 `FusionServer 2288H V6` 最高。
- 楼长：服务器历史供应商刻意形成集中度；排名第一的供应商有当前有效黑名单，排序保持证据频次并显示警告。
- 采购员：`DEMO-CREDIT-0005` 的税率/合同联系方式形成 6/2/1 组合。
- 仓管员：服务器以“1号楼一层设备仓”为主，“中心公共备件仓”和“4号楼设备暂存区”为辅。

## Complex Query 与 Risk 场景

可验证各楼宇数量、最近半年服务器金额、品牌平均单价、按月趋势、供应商排名。少量记录包含高单价、大批量、延期、入库数量差异、黑名单供应商及短期集中采购，用于风险信号验证；数据生成不会修改风险阈值。

## Knowledge 与通知安全

4 份 Synthetic Policy 文档只写入 MySQL，`index_status=PENDING`，不会调用公网 Embedding 或写入 Qdrant。PENDING/FAILED 通知的重试时间设置在远期，避免开发环境立即产生外部副作用。

## 命令

在仓库根目录、`purchasing-agent` Conda 环境中执行：

```powershell
python scripts/seed_demo_dataset.py --reset
python scripts/seed_demo_dataset.py
python scripts/seed_demo_dataset.py --verify
```

无参数执行会先安全清理 DEMO namespace 再重新生成，因此重复执行不会使行数翻倍。终端会输出主要表、状态、设备专业、推荐检查点和账号摘要。

后端运行在 `127.0.0.1:8000` 时，可执行
`python scripts/verify_demo_capabilities.py`，通过现有 MCP/Backend 真实调用四类推荐、五类分析查询和风险信号；该脚本不调用公网 LLM。
