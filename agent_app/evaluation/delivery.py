from __future__ import annotations

from typing import Literal
from uuid import uuid4

from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_app.investigation.schemas import EvidenceStatus
from agent_app.schemas.chat import ChatData
from agent_app.schemas.common import AgentApiResponse


class DeliveryDemoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demo_id: str
    title: str
    status: Literal["PASSED", "FAILED", "BLOCKED"]
    checks: dict[str, bool] = Field(default_factory=dict)
    trace_ids: list[str] = Field(default_factory=list)
    details: dict[str, JsonValue] = Field(default_factory=dict)
    reason: str | None = None


class DeliveryDemoReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: str = "1.0"
    mode: Literal["MODEL_INDEPENDENT"] = "MODEL_INDEPENDENT"
    total: int
    passed: int
    failed: int
    blocked: int
    results: list[DeliveryDemoResult]


class DeliveryDemoRunner:
    """Exercise delivery demos through the development BFF and real Agent service."""

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def run(self) -> DeliveryDemoReport:
        results = [
            await self._complex_query_demo(),
            await self._risk_investigation_demo(),
            self._knowledge_hybrid_gate(),
        ]
        return DeliveryDemoReport(
            total=len(results),
            passed=sum(item.status == "PASSED" for item in results),
            failed=sum(item.status == "FAILED" for item in results),
            blocked=sum(item.status == "BLOCKED" for item in results),
            results=results,
        )

    async def _complex_query_demo(self) -> DeliveryDemoResult:
        demo_id = "DEM-002"
        conversation = f"delivery-complex-{uuid4().hex}"
        try:
            first = await self._chat(
                "统计 2026-08-01 到 2026-08-05 设备类型为服务器的各品牌采购数量、"
                "平均单价、中位价和总金额",
                conversation,
                f"{conversation}-1",
            )
            second = await self._chat(
                "再排除有延期的供应商，保持刚才日期、专业和按品牌统计口径",
                conversation,
                f"{conversation}-2",
            )
        except Exception as exc:
            return self._failed(demo_id, "复杂查询与连续追问", exc)

        first_analysis = first.data.analysis
        second_analysis = second.data.analysis
        first_summary = first_analysis.summary if first_analysis else {}
        second_query = second_analysis.effective_query if second_analysis else None
        checks = {
            "first_route": first.data.route == "COMPLEX_QUERY",
            "first_complete": first.data.execution.status == "COMPLETE",
            "first_standard_answer": first_summary
            == {
                "count": 9,
                "average_unit_price": "1112.50",
                "median_unit_price": "950.00",
                "total_amount": "34350.00",
            },
            "first_brand_group": bool(
                first_analysis
                and first_analysis.groups
                and first_analysis.groups[0].get("key") == "TEST-BRAND"
            ),
            "same_conversation": first.data.conversation_id == second.data.conversation_id,
            "follow_up_route": second.data.route == "COMPLEX_QUERY",
            "follow_up_not_partial": bool(
                second_analysis and second_analysis.partial_success is False
            ),
            "follow_up_inherited_dates": bool(
                second_query
                and str(second_query.created_from) == "2026-08-01"
                and str(second_query.created_to) == "2026-08-05"
            ),
            "follow_up_inherited_profession": bool(
                second_query and second_query.device_professions == ["服务器"]
            ),
            "follow_up_kept_brand_group": bool(second_query and second_query.group_by == "BRAND"),
            "follow_up_added_delay_exclusion": bool(
                second_query and second_query.exclude_delayed_suppliers is True
            ),
            "model_not_required": (
                first.data.execution.model_usage.call_count == 0
                and second.data.execution.model_usage.call_count == 0
            ),
        }
        return DeliveryDemoResult(
            demo_id=demo_id,
            title="复杂查询与连续追问",
            status="PASSED" if all(checks.values()) else "FAILED",
            checks=checks,
            trace_ids=[first.data.execution.trace_id, second.data.execution.trace_id],
            details={
                "first_summary": first_summary,
                "follow_up_summary": second_analysis.summary if second_analysis else {},
                "tool_calls": first.data.tool_call_count + second.data.tool_call_count,
            },
            reason=None if all(checks.values()) else "复杂查询演示契约不匹配",
        )

    async def _risk_investigation_demo(self) -> DeliveryDemoResult:
        demo_id = "DEM-003"
        conversation = f"delivery-risk-{uuid4().hex}"
        try:
            response = await self._chat(
                "调查采购申请 91009 的审批风险",
                conversation,
                f"{conversation}-1",
            )
        except Exception as exc:
            return self._failed(demo_id, "审批风险调查", exc)

        output = response.data.risk_investigation
        risk_codes = {item.risk_code for item in output.summary_items} if output else set()
        successful_evidence = (
            [item for item in output.evidence if item.status is EvidenceStatus.SUCCESS]
            if output
            else []
        )
        checks = {
            "route": response.data.route == "RISK_INVESTIGATION",
            "requirement": bool(output and output.requirement_id == 91009),
            "price_risk": "PRICE_DEVIATION" in risk_codes,
            "review_passed": bool(output and output.review.passed),
            "evidence_sources": bool(
                successful_evidence
                and all(item.source and item.trace_id for item in successful_evidence)
            ),
            "human_checks": bool(
                output
                and output.summary_items
                and all(item.human_checks for item in output.summary_items)
            ),
            "knowledge_gap_explicit": bool(
                output and output.complete is False and output.knowledge_evidence_available is False
            ),
            "not_approval_decision": bool(output and "不替代人工审批结论" in output.answer),
            "model_not_required": response.data.execution.model_usage.call_count == 0,
        }
        return DeliveryDemoResult(
            demo_id=demo_id,
            title="审批风险调查",
            status="PASSED" if all(checks.values()) else "FAILED",
            checks=checks,
            trace_ids=[response.data.execution.trace_id],
            details={
                "risk_codes": sorted(risk_codes),
                "evidence_count": len(output.evidence) if output else 0,
                "tool_calls": response.data.tool_call_count,
                "complete": output.complete if output else False,
            },
            reason=None if all(checks.values()) else "风险调查演示契约不匹配",
        )

    @staticmethod
    def _knowledge_hybrid_gate() -> DeliveryDemoResult:
        return DeliveryDemoResult(
            demo_id="DEM-001",
            title="知识与业务混合问答",
            status="BLOCKED",
            checks={"real_materials_available": False},
            reason="等待真实采购制度、流程或历史案例材料，未使用虚构知识代替验收",
        )

    async def _chat(
        self,
        message: str,
        conversation_id: str,
        message_id: str,
    ) -> AgentApiResponse[ChatData]:
        response = await self.client.post(
            "/demo-api/agent-chat",
            json={
                "platform_user_id": "test-user-05",
                "message": message,
                "external_conversation_id": conversation_id,
                "external_message_id": message_id,
            },
        )
        response.raise_for_status()
        return AgentApiResponse[ChatData].model_validate(response.json())

    @staticmethod
    def _failed(demo_id: str, title: str, exc: Exception) -> DeliveryDemoResult:
        return DeliveryDemoResult(
            demo_id=demo_id,
            title=title,
            status="FAILED",
            reason=f"{type(exc).__name__}: {exc}",
        )
