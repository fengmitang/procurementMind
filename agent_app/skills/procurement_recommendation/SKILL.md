# procurement_recommendation 1.0

角色感知的采购历史推荐 Domain Skill。Graph 仅负责把 `RECOMMENDATION` 路由交给本 Skill；
本 Skill 以声明式 Profile 执行权限解析、逐级历史 Evidence 检索、去重和确定性候选聚合。

## 边界

- 只读；不创建 HITL action，不写采购业务数据。
- Backend RBAC 与 Profile Policy 同时生效。
- LLM 不选择 Profile、不判断权限、不排序候选，也不补全缺失业务字段。
- 设备名称候选复用 `agent_app/device_terms`，不维护第二套向量检索。
- 当前黑名单及历史黑名单只产生 Warning，不删除、降权或移动候选。

## Profiles

- REQUESTER：历史品牌/型号；禁止价格、供应商、合同、税率和黑名单字段。
- BUILDING_MANAGER：供应商历史依据、最近真实单价、已完成审核信息和黑名单提示。
- PURCHASER：同供应商历史税率与合同联系方式组合。
- WAREHOUSE_MANAGER：历史常用入库位置，不推断库存或库容。

每次最多保留 20 条去重 Evidence，最多输出 5 个候选。无时间要求时不增加默认日期过滤。
