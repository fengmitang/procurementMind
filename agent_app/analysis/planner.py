import json
import re
from datetime import date
from typing import Protocol

from agent_app.analysis.schemas import (
    AnalysisPlan,
    AnalysisPlanStep,
    AnalysisStepResult,
    AnalysisToolName,
)
from agent_app.models.protocols import ModelMessage, ModelPurpose, StructuredModelRequest
from agent_app.models.runner import StructuredModelRunner
from agent_app.schemas.analytics import (
    AnalyticsAggregation,
    AnalyticsGroupBy,
    AnalyticsQueryInput,
)


class AnalysisPlanner(Protocol):
    async def create_plan(
        self,
        message: str,
        previous_query: AnalyticsQueryInput | None = None,
    ) -> AnalysisPlan: ...

    async def revise_plan(
        self,
        plan: AnalysisPlan,
        completed: list[AnalysisStepResult],
    ) -> AnalysisPlan | None: ...


class DeterministicAnalysisPlanner:
    """Stable fake planner for contract tests; it is not the production language model."""

    _follow_up_markers = ("再", "另外", "并且", "改为", "只看", "排除", "还是", "那么")
    _device_names = ("服务器", "交换机", "路由器", "存储", "防火墙", "机柜", "UPS")
    _device_professions = (
        "电气",
        "暖通",
        "弱电",
        "机房环境",
        "工器具",
        "算力服务器",
        "IDC网络",
        "其他",
    )

    async def create_plan(
        self,
        message: str,
        previous_query: AnalyticsQueryInput | None = None,
    ) -> AnalysisPlan:
        supplier_id = self._first_id(message, r"供应商\s*(?:ID)?\s*[：:#]?\s*(\d+)")
        requirement_id = self._first_id(message, r"(?:采购申请|采购单|申请)\s*[：:#]?\s*(\d{4,})")
        special_steps: list[AnalysisPlanStep] = []
        if supplier_id and any(word in message for word in ("履约", "延期率", "表现")):
            special_steps.append(
                AnalysisPlanStep(
                    step_id="supplier_performance",
                    objective="查询供应商履约统计",
                    tool=AnalysisToolName.GET_SUPPLIER_PERFORMANCE,
                    arguments={"supplier_id": supplier_id},
                    independent=True,
                )
            )
        if requirement_id and "相似" in message:
            special_steps.append(
                AnalysisPlanStep(
                    step_id="similar_cases",
                    objective="查询可解释相似采购案例",
                    tool=AnalysisToolName.GET_SIMILAR_CASES,
                    arguments={"requirement_id": requirement_id, "limit": 10},
                    independent=True,
                )
            )
        if requirement_id and "风险" in message:
            special_steps.append(
                AnalysisPlanStep(
                    step_id="risk_signals",
                    objective="查询后端确定性风险信号",
                    tool=AnalysisToolName.GET_REQUIREMENT_RISK_SIGNALS,
                    arguments={"requirement_id": requirement_id},
                    independent=True,
                )
            )
        if requirement_id and "推荐供应商" in message:
            special_steps.append(
                AnalysisPlanStep(
                    step_id="supplier_recommendations",
                    objective="查询适合当前采购申请且不在有效黑名单中的供应商",
                    tool=AnalysisToolName.RECOMMEND_SUPPLIERS,
                    arguments={"requirement_id": requirement_id, "limit": 10},
                    independent=True,
                )
            )
        if special_steps:
            return self._plan(message, special_steps)

        query = self._parse_query(message)
        if previous_query and message.strip().startswith(self._follow_up_markers):
            query = self._inherit(previous_query, query, message)
        step = AnalysisPlanStep(
            step_id="purchase_query",
            objective="执行受控采购查询与聚合",
            tool=AnalysisToolName.QUERY_PURCHASE_ANALYTICS,
            arguments={"query": query.model_dump(mode="json")},
        )
        return self._plan(message, [step], query=query)

    async def revise_plan(
        self,
        plan: AnalysisPlan,
        completed: list[AnalysisStepResult],
    ) -> AnalysisPlan | None:
        if plan.revision_count >= 1 or not completed:
            return None
        failed = [item for item in completed if not item.success]
        if not failed or any(
            item.code not in {"MCP_TOOL_TIMEOUT", "BACKEND_UNAVAILABLE"} for item in failed
        ):
            return None
        completed_ids = {item.step_id for item in completed if item.success}
        remaining = [step for step in plan.steps if step.step_id not in completed_ids]
        if not remaining:
            return None
        return plan.model_copy(update={"revision_count": 1})

    def _parse_query(self, message: str) -> AnalyticsQueryInput:
        values: dict = {}
        dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", message)
        if dates:
            values["created_from"] = date.fromisoformat(dates[0])
        if len(dates) > 1:
            values["created_to"] = date.fromisoformat(dates[1])
        building_ids = [int(value) for value in re.findall(r"(?:楼宇|机房)\s*(\d+)", message)]
        if building_ids:
            values["building_ids"] = list(dict.fromkeys(building_ids))
        supplier_ids = [int(value) for value in re.findall(r"供应商\s*(\d+)", message)]
        if supplier_ids:
            values["supplier_ids"] = list(dict.fromkeys(supplier_ids))
        profession = next(
            (item for item in self._device_professions if item.lower() in message.lower()),
            None,
        )
        if profession:
            values["device_professions"] = [profession]
        remaining = message.replace(profession, "") if profession else message
        for device_name in self._device_names:
            if device_name.lower() in remaining.lower():
                values["device_name"] = device_name
                break
        brand = re.search(
            r"品牌(?:是|为|=|：|:)\s*([A-Za-z0-9\u4e00-\u9fff_-]{1,30})",
            message,
        )
        if brand:
            values["brands"] = [brand.group(1)]
        minimum = re.search(r"单价(?:不低于|至少|大于等于)\s*(\d+(?:\.\d+)?)", message)
        maximum = re.search(r"单价(?:不高于|至多|小于等于)\s*(\d+(?:\.\d+)?)", message)
        if minimum:
            values["min_unit_price"] = minimum.group(1)
        if maximum:
            values["max_unit_price"] = maximum.group(1)
        if "排除" in message and "黑名单" in message:
            values["exclude_blacklisted"] = True
        if ("排除" in message and "延期供应商" in message) or "排除有延期的供应商" in message:
            values["exclude_delayed_suppliers"] = True
        group_mapping = {
            AnalyticsGroupBy.BUILDING: ("按楼宇", "各楼宇"),
            AnalyticsGroupBy.SUPPLIER: ("按供应商", "各供应商"),
            AnalyticsGroupBy.BRAND: ("按品牌", "各品牌"),
            AnalyticsGroupBy.DEVICE_NAME: ("按设备", "各设备"),
        }
        for group, markers in group_mapping.items():
            if any(marker in message for marker in markers):
                values["group_by"] = group
                break
        aggregations: list[AnalyticsAggregation] = []
        if any(word in message for word in ("数量", "多少", "几笔", "次数")):
            aggregations.append(AnalyticsAggregation.COUNT)
        if "平均单价" in message or "均价" in message:
            aggregations.append(AnalyticsAggregation.AVERAGE_UNIT_PRICE)
        if "中位价" in message or "中位数" in message:
            aggregations.append(AnalyticsAggregation.MEDIAN_UNIT_PRICE)
        if any(word in message for word in ("总金额", "采购金额", "合计金额")):
            aggregations.append(AnalyticsAggregation.TOTAL_AMOUNT)
        if aggregations:
            values["aggregations"] = list(dict.fromkeys(aggregations))
        return AnalyticsQueryInput.model_validate(values)

    @staticmethod
    def _inherit(
        previous: AnalyticsQueryInput,
        current: AnalyticsQueryInput,
        message: str,
    ) -> AnalyticsQueryInput:
        base = previous.model_dump(mode="python")
        explicit = current.model_fields_set
        for field in explicit:
            base[field] = getattr(current, field)
        if "取消排除黑名单" in message:
            base["exclude_blacklisted"] = False
        if "取消排除延期" in message:
            base["exclude_delayed_suppliers"] = False
        base["page"] = 1
        return AnalyticsQueryInput.model_validate(base)

    @staticmethod
    def _first_id(message: str, pattern: str) -> int | None:
        match = re.search(pattern, message, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _plan(
        message: str,
        steps: list[AnalysisPlanStep],
        *,
        query: AnalyticsQueryInput | None = None,
    ) -> AnalysisPlan:
        return AnalysisPlan(
            goal=message,
            steps=steps,
            termination_condition="所有必需工具步骤完成或返回可解释失败",
            query_context=query,
        )


class ModelBackedAnalysisPlanner:
    """Provider-neutral planner. The runner owns the selected provider adapter."""

    def __init__(self, runner: StructuredModelRunner, trace_id: str) -> None:
        self.runner = runner
        self.trace_id = trace_id

    async def create_plan(
        self,
        message: str,
        previous_query: AnalyticsQueryInput | None = None,
    ) -> AnalysisPlan:
        context = previous_query.model_dump(mode="json") if previous_query else None
        request = StructuredModelRequest(
            purpose=ModelPurpose.ANALYSIS_PLAN,
            trace_id=self.trace_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "你是采购分析 Planner。只能输出给定 Schema，且只能选择 Schema 中的"
                        "只读工具枚举。不得生成 SQL、URL、身份字段或审批结论。工具参数必须"
                        "来自用户问题；连续追问只能继承提供的已确认查询上下文。"
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {"message": message, "confirmed_previous_query": context},
                        ensure_ascii=False,
                    ),
                ),
            ],
            response_schema=AnalysisPlan.model_json_schema(mode="serialization"),
        )
        plan, _, _ = await self.runner.run(request, AnalysisPlan)
        return plan

    async def revise_plan(
        self,
        plan: AnalysisPlan,
        completed: list[AnalysisStepResult],
    ) -> AnalysisPlan | None:
        if plan.revision_count >= 1:
            return None
        request = StructuredModelRequest(
            purpose=ModelPurpose.ANALYSIS_REPLAN,
            trace_id=self.trace_id,
            messages=[
                ModelMessage(
                    role="system",
                    content=(
                        "根据失败步骤调整一次计划。保留所有已成功步骤及其 ID，不得改变已完成"
                        "结果，不得增加非白名单工具。输出完整 AnalysisPlan。"
                    ),
                ),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "plan": plan.model_dump(mode="json"),
                            "completed": [item.model_dump(mode="json") for item in completed],
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
            response_schema=AnalysisPlan.model_json_schema(mode="serialization"),
        )
        revised, _, _ = await self.runner.run(request, AnalysisPlan)
        return revised.model_copy(update={"revision_count": 1})
