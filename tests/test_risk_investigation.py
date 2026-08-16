import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.schemas import GraphRunRequest, RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.investigation.reviewer import ProgramEvidenceReviewer
from agent_app.investigation.schemas import (
    EvidenceStatus,
    InvestigationEvidence,
    InvestigationEvidenceKind,
    RiskSummaryItem,
)
from agent_app.investigation.service import RiskInvestigationService
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.rag.schemas import RetrievalFilters, RetrievalResult
from agent_app.schemas.backend import BackendIdentity, CurrentUserData, UserRoleData
from tests.test_agent_graph_rag import retrieval_result


def ok(name: str, data: dict) -> MCPToolResponse:
    return MCPToolResponse.ok(
        data,
        source=f"/api/v1/{name}",
        trace_id="trace-risk",
    )


def risk_response() -> MCPToolResponse:
    return ok(
        "requirements/91009/risk-signals",
        {
            "requirement_id": 91009,
            "evaluated_at": "2026-08-05T10:00:00",
            "matched_count": 1,
            "scanned_rows": 9,
            "signals": [
                {
                    "risk_code": "PRICE_DEVIATION",
                    "risk_type": "价格异常",
                    "risk_level": "MEDIUM",
                    "matched": True,
                    "facts": {"actual_unit_price": "1600.00"},
                    "metrics": {"historical_median": "950.00"},
                    "related_record_ids": [91001, 91002],
                    "threshold": {"deviation_ratio": "0.20"},
                    "time_range": {
                        "created_from": "2025-08-05",
                        "created_to": "2026-08-05",
                    },
                },
                {
                    "risk_code": "DELIVERY_DELAY",
                    "risk_type": "延期",
                    "risk_level": "LOW",
                    "matched": False,
                    "facts": {},
                    "metrics": {},
                    "related_record_ids": [],
                    "threshold": {},
                    "time_range": {},
                },
            ],
        },
    )


def requirement_response() -> MCPToolResponse:
    return ok(
        "requirements/91009",
        {
            "requirement_id": 91009,
            "requirement_no": "TEST-PR-OVER-RECEIPT",
            "applicant_fields": {
                "device_profession": "服务器",
                "device_name": "服务器",
                "brand": "TEST-BRAND",
            },
            "review_records": [{"proposed_supplier_id": 92001}],
            "purchase_execution": {"supplier_id": 92001},
        },
    )


class FakeClient:
    def __init__(self, overrides: dict[str, MCPToolResponse] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls.append(name)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if name in self.overrides:
            return self.overrides[name]
        responses = {
            "get_requirement_risk_signals": risk_response(),
            "get_purchase_request": requirement_response(),
            "get_similar_cases": ok(
                "requirements/91009/similar-cases",
                {"requirement_id": 91009, "algorithm": "v1", "items": []},
            ),
            "query_purchase_analytics": ok(
                "analytics/purchase-query",
                {
                    "summary": {"median_unit_price": "950.00"},
                    "items": [],
                    "groups": [],
                },
            ),
            "get_supplier_performance": ok(
                "suppliers/92001/performance",
                {"supplier_id": 92001, "historical_purchase_count": 3},
            ),
        }
        return responses[name]


class FakeKnowledgeRetriever:
    def __init__(self, result: RetrievalResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, RetrievalFilters, str | None]] = []

    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        self.calls.append((query, filters, trace_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def fake_knowledge_result(*, answerable: bool = True) -> RetrievalResult:
    filters = RetrievalFilters(allowed_roles=["BUILDING_MANAGER"])
    result = retrieval_result("价格风险制度", filters, "trace-risk-rag")
    if answerable:
        return result
    return result.model_copy(
        update={
            "answerable": False,
            "evidences": [],
            "citations": [],
            "context": "",
            "abstention_reason": "未找到适用制度",
        }
    )


@pytest.mark.asyncio
async def test_risk_signal_runs_first_then_follow_ups_run_in_parallel() -> None:
    client = FakeClient()

    result = await RiskInvestigationService().run(91009, client)

    assert client.calls[:2] == ["get_requirement_risk_signals", "get_purchase_request"]
    assert set(client.calls[2:]) == {
        "get_similar_cases",
        "query_purchase_analytics",
        "get_supplier_performance",
    }
    assert client.max_active == 3
    assert len(result.summary_items) == 1
    assert result.summary_items[0].risk_code == "PRICE_DEVIATION"
    assert result.summary_items[0].facts == {"actual_unit_price": "1600.00"}
    assert result.summary_items[0].information_complete is False
    assert result.review.passed is True
    assert result.complete is False
    assert any(item.status is EvidenceStatus.UNAVAILABLE for item in result.evidence)
    assert "制度证据标记为信息不足" in result.answer


@pytest.mark.asyncio
async def test_all_business_and_knowledge_evidence_make_investigation_complete() -> None:
    retriever = FakeKnowledgeRetriever(fake_knowledge_result())

    result = await RiskInvestigationService().run(
        91009,
        FakeClient(),
        knowledge_retriever=retriever,
        allowed_roles=["BUILDING_MANAGER"],
        question="调查采购申请 91009 是否存在价格异常风险",
        trace_id="trace-risk",
    )

    knowledge = next(
        item for item in result.evidence if item.kind is InvestigationEvidenceKind.KNOWLEDGE_RULE
    )
    assert knowledge.status is EvidenceStatus.SUCCESS
    assert knowledge.data["citations"]
    assert result.knowledge_evidence_available is True
    assert result.summary_items[0].information_complete is True
    assert result.complete is True
    assert result.warnings == []
    assert retriever.calls[0][1].allowed_roles == ["BUILDING_MANAGER"]
    assert "不替代人工审批结论" in result.answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retrieval", "expected_code"),
    [
        (fake_knowledge_result(answerable=False), "RAG_EVIDENCE_INSUFFICIENT"),
        (RuntimeError("rag down"), "RAG_RETRIEVAL_FAILURE"),
    ],
)
async def test_missing_or_failed_knowledge_stays_unavailable(
    retrieval: RetrievalResult | Exception,
    expected_code: str,
) -> None:
    result = await RiskInvestigationService().run(
        91009,
        FakeClient(),
        knowledge_retriever=FakeKnowledgeRetriever(retrieval),
        allowed_roles=["BUILDING_MANAGER"],
        trace_id="trace-risk",
    )

    knowledge = next(
        item for item in result.evidence if item.kind is InvestigationEvidenceKind.KNOWLEDGE_RULE
    )
    assert knowledge.status is EvidenceStatus.UNAVAILABLE
    assert knowledge.code == expected_code
    assert result.knowledge_evidence_available is False
    assert result.complete is False


@pytest.mark.asyncio
async def test_risk_signal_failure_stops_investigation_without_guessing() -> None:
    failure = MCPToolResponse.failure(
        "PERMISSION_DENIED",
        "无权查看",
        source="/api/v1/requirements/91009/risk-signals",
        trace_id="trace-risk",
    )
    client = FakeClient({"get_requirement_risk_signals": failure})

    result = await RiskInvestigationService().run(91009, client)

    assert client.calls == ["get_requirement_risk_signals"]
    assert result.summary_items == []
    assert result.complete is False
    assert "不会猜测" in result.answer


@pytest.mark.asyncio
async def test_follow_up_failure_is_preserved_as_partial_evidence() -> None:
    failure = MCPToolResponse.failure(
        "BACKEND_UNAVAILABLE",
        "履约接口不可用",
        source="/api/v1/suppliers/92001/performance",
        trace_id="trace-risk",
    )
    client = FakeClient({"get_supplier_performance": failure})

    result = await RiskInvestigationService().run(91009, client)

    supplier = next(
        item
        for item in result.evidence
        if item.kind is InvestigationEvidenceKind.SUPPLIER_PERFORMANCE
    )
    assert supplier.status is EvidenceStatus.FAILED
    assert result.summary_items
    assert result.complete is False
    assert "履约接口不可用" in result.warnings


@pytest.mark.asyncio
async def test_investigation_respects_tool_call_budget() -> None:
    client = FakeClient()

    result = await RiskInvestigationService(max_tool_calls=2).run(91009, client)

    assert client.calls == ["get_requirement_risk_signals", "get_purchase_request"]
    skipped = [item for item in result.evidence if item.code == "GRAPH_TOOL_CALL_LIMIT"]
    assert len(skipped) == 3
    assert all(item.status is EvidenceStatus.UNAVAILABLE for item in skipped)
    assert result.complete is False


def test_program_reviewer_detects_numeric_tampering_and_approval_decision() -> None:
    risk = risk_response()
    evidence = [
        InvestigationEvidence(
            evidence_id="risk",
            kind=InvestigationEvidenceKind.RISK_SIGNALS,
            status=EvidenceStatus.SUCCESS,
            source=risk.source,
            data=risk.data,
        )
    ]
    item = RiskSummaryItem(
        risk_code="PRICE_DEVIATION",
        risk_type="价格异常",
        risk_level="MEDIUM",
        backend_rule_matched=True,
        facts={"actual_unit_price": "9999.00"},
        metrics={"historical_median": "950.00"},
        related_record_ids=[91001, 91002],
        data_sources=[risk.source],
        applicable_rule={"deviation_ratio": "0.20"},
        possible_causes=["建议通过审批"],
        information_complete=False,
        information_gaps=["缺少制度"],
        human_checks=["核对报价"],
    )

    result = ProgramEvidenceReviewer().review([item], evidence)

    assert result.passed is False
    assert {finding.code for finding in result.findings} == {
        "RISK_FACT_MISMATCH",
        "APPROVAL_DECISION_FORBIDDEN",
    }


@pytest.mark.asyncio
async def test_risk_investigation_graph_returns_structured_evidence() -> None:
    client = FakeClient()
    retriever = FakeKnowledgeRetriever(fake_knowledge_result())

    @asynccontextmanager
    async def factory(*_args):
        yield client

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="risk-graph-secret-123",
        procurement_backend_url="http://backend.test",
    )
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
    )
    result = await ProcurementGraphService(
        settings,
        mcp_client_factory=factory,
        knowledge_retriever=retriever,
    ).run(
        GraphRunRequest(
            task_id=uuid4(),
            trace_id="trace-risk",
            conversation_id=1,
            identity=identity,
            current_user=CurrentUserData(
                employee_id=1,
                employee_no="E001",
                name="楼长",
                mobile=None,
                status="ACTIVE",
                platform_type=identity.platform_type,
                platform_user_id=identity.platform_user_id,
                roles=[
                    UserRoleData(
                        role_id=1,
                        role_code="BUILDING_MANAGER",
                        role_name="楼长",
                    )
                ],
                buildings=[],
            ),
            message="调查采购申请 91009 的审批风险",
        )
    )

    assert result.route is RouteType.RISK_INVESTIGATION
    assert result.risk_investigation is not None
    assert result.risk_investigation.review.passed is True
    assert result.risk_investigation.complete is True
    assert result.risk_investigation.knowledge_evidence_available is True
    assert result.tool_call_count == 5
    assert len(result.evidence) == 6
    assert any(item.name == "risk_investigation" for item in result.trace_events)
    assert [item.name for item in result.trace_events[-3:]] == [
        "review",
        "confirmation",
        "finalize",
    ]
    assert "确定性风险" in result.reply


@pytest.mark.asyncio
async def test_risk_graph_requires_requirement_id_without_tool_call() -> None:
    client = FakeClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="risk-graph-secret-123",
        procurement_backend_url="http://backend.test",
    )
    identity = BackendIdentity(
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
    )
    result = await ProcurementGraphService(settings, mcp_client_factory=factory).run(
        GraphRunRequest(
            task_id=uuid4(),
            trace_id="trace-risk",
            conversation_id=1,
            identity=identity,
            current_user=CurrentUserData(
                employee_id=1,
                employee_no="E001",
                name="楼长",
                mobile=None,
                status="ACTIVE",
                platform_type=identity.platform_type,
                platform_user_id=identity.platform_user_id,
                roles=[],
                buildings=[],
            ),
            message="调查供应商黑名单风险",
        )
    )

    assert result.errors[0].code == "PURCHASE_REQUEST_ID_REQUIRED"
    assert client.calls == []
    assert "采购单号" in result.reply
    assert "ID" not in result.reply
