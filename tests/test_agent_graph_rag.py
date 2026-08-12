import pytest

from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.schemas import RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.models.fake import ScriptedModelAdapter
from agent_app.models.protocols import ModelPurpose, StructuredModelResponse
from agent_app.models.roles import StructuredModelRoles
from agent_app.models.runner import StructuredModelRunner
from agent_app.rag.schemas import (
    ChildChunkPayload,
    KnowledgeCitation,
    RetrievalFilters,
    RetrievalResult,
    RetrievalTrace,
    RetrievedEvidence,
)
from agent_app.schemas.backend import ConversationStateData, UserRoleData
from tests.test_agent_graph import (
    FakeMCPClient,
    factory_for,
    request,
    requirement_response,
    settings,
)


def retrieval_result(query: str, filters: RetrievalFilters, trace_id: str) -> RetrievalResult:
    payload = ChildChunkPayload(
        child_id="child-1",
        parent_id="parent-1",
        document_id="document-1",
        title="采购业务管理与流程指引",
        section_path=["申请阶段", "驳回处理"],
        topic="处理驳回申请",
        chunk_type="step",
        version="1.0",
        status="ACTIVE",
        content="申请被驳回后，需求人应根据驳回意见修改，再重新提交。",
        source_path="knowledge/source/process.md",
        source_start_line=20,
        source_end_line=22,
        allowed_roles=["APPLICANT"],
    )
    citation = KnowledgeCitation(
        citation_id="K1",
        child_id=payload.child_id,
        parent_id=payload.parent_id,
        document_id=payload.document_id,
        document_title=payload.title,
        version=payload.version,
        section_path=payload.section_path,
        source_path=payload.source_path,
        source_start_line=payload.source_start_line,
        source_end_line=payload.source_end_line,
    )
    evidence = RetrievedEvidence(
        payload=payload,
        fusion_score=0.8,
        rerank_score=0.95,
        context_content=payload.content,
        citation=citation,
    )
    trace = RetrievalTrace(
        trace_id=trace_id,
        original_query=query,
        rewritten_query=query,
        rewrite_applied=False,
        filters=filters,
        dense_candidates=[],
        sparse_candidates=[],
        rrf_candidates=[],
        rerank_candidates=[],
        final_evidence_ids=[payload.child_id],
        parent_lookups=[],
        citations=[citation],
        duration_ms=1,
    )
    return RetrievalResult(
        original_query=query,
        rewritten_query=query,
        dense_candidates=[],
        sparse_candidates=[],
        fusion_candidates=[],
        evidences=[evidence],
        citations=[citation],
        context=payload.content,
        answerable=True,
        trace=trace,
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RetrievalFilters, str | None]] = []

    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        self.calls.append((query, filters, trace_id))
        return retrieval_result(query, filters, trace_id or "missing")


def model_response(output: dict) -> StructuredModelResponse:
    return StructuredModelResponse(
        provider="fake",
        model="fake-graph",
        output=output,
        latency_ms=1,
    )


def applicant_request(message: str):
    graph_request = request(message)
    return graph_request.model_copy(
        update={
            "current_user": graph_request.current_user.model_copy(
                update={
                    "roles": [
                        UserRoleData(
                            role_id=1,
                            role_code="APPLICANT",
                            role_name="需求人",
                        )
                    ]
                }
            )
        }
    )


@pytest.mark.asyncio
async def test_knowledge_route_retrieves_visible_citations_and_reviews_evidence() -> None:
    retriever = FakeRetriever()
    service = ProcurementGraphService(settings(), knowledge_retriever=retriever)

    result = await service.run(applicant_request("采购申请被驳回后如何处理？"))

    assert result.route is RouteType.KNOWLEDGE
    assert result.knowledge is not None
    assert result.evidence_sufficient is True
    assert result.review is not None and result.review.passed is True
    assert "重新提交" in result.reply
    assert "[K1]" not in result.reply
    assert "knowledge/source" not in result.reply
    assert retriever.calls[0][1].allowed_roles == ["APPLICANT"]
    assert retriever.calls[0][2] == "trace-graph"
    assert [event.name for event in result.trace_events] == [
        "load_context",
        "first_version_router",
        "knowledge_retrieval",
        "sufficiency_check",
        "compose_answer",
        "review",
        "confirmation",
        "finalize",
    ]


@pytest.mark.asyncio
async def test_hybrid_route_combines_rag_rules_and_tool_realtime_fact() -> None:
    retriever = FakeRetriever()
    mcp = FakeMCPClient(requirement_response())
    service = ProcurementGraphService(
        settings(),
        knowledge_retriever=retriever,
        mcp_client_factory=factory_for(mcp),
    )

    result = await service.run(
        applicant_request("为什么采购申请 91007 还不能提交，当前状态是什么？")
    )

    assert result.route is RouteType.HYBRID
    assert "COMPLETED" in result.reply
    assert "重新提交" in result.reply
    assert "[K1]" not in result.reply
    assert result.evidence_sufficient is True
    assert result.tool_call_count == 1
    assert len(result.evidence) == 2


@pytest.mark.asyncio
async def test_form_prefill_creates_draft_and_never_executes_business_action() -> None:
    graph_request = applicant_request("帮我生成采购申请草稿，设备是服务器")
    result = await ProcurementGraphService(settings()).run(graph_request)
    saved = GraphMemoryMapper.to_backend_state(graph_request, result)

    assert result.route is RouteType.FORM_PREFILL
    assert result.pending_action is None
    assert result.form_draft == {
        "device_name": "服务器",
        "device_profession": "算力服务器",
    }
    assert result.form_missing_fields == [
        "building_id",
        "quantity",
        "unit",
        "application_reason",
    ]
    assert result.tool_call_count == 0
    assert result.review is not None and result.review.passed is True
    assert result.review.requires_human_confirmation is False
    assert saved.awaiting_confirmation is False
    assert saved.collected_data["form_draft"]["device_name"] == "服务器"
    assert "还需要补充" in result.reply


@pytest.mark.asyncio
async def test_natural_purchase_intent_keeps_known_fields_and_asks_only_for_missing() -> None:
    result = await ProcurementGraphService(settings()).run(
        applicant_request("我要采购一批服务器，浪潮的")
    )

    assert result.route is RouteType.FORM_PREFILL
    assert result.form_draft["device_name"] == "服务器"
    assert result.form_draft["device_profession"] == "算力服务器"
    assert result.form_draft["brand"] == "浪潮"
    assert "device_name" not in result.form_missing_fields
    assert "brand" not in result.form_missing_fields
    assert result.pending_action is None


@pytest.mark.asyncio
async def test_configured_model_roles_are_used_for_route_and_compose() -> None:
    adapter = ScriptedModelAdapter(
        [
            model_response(
                {
                    "route": "KNOWLEDGE",
                    "confidence": 0.99,
                    "reason": "制度流程问题",
                    "requires_realtime_tools": False,
                    "requires_knowledge": True,
                }
            ),
            model_response(
                {
                    "answer": "申请被驳回后，请先修改申请内容，再重新提交审批。",
                    "citations": [{"citation_id": "K1", "claim": "驳回处理流程"}],
                    "limitations": [],
                    "requires_human_confirmation": False,
                }
            ),
            model_response(
                {
                    "passed": True,
                    "issues": [],
                    "requires_human_confirmation": False,
                    "revised_answer": None,
                }
            ),
        ]
    )
    model_roles = StructuredModelRoles(
        StructuredModelRunner(adapter, timeout_seconds=1, max_retries=0),
        "trace-graph",
    )
    result = await ProcurementGraphService(
        settings(),
        knowledge_retriever=FakeRetriever(),
        model_roles=model_roles,
    ).run(applicant_request("请帮我处理这个问题"))

    assert result.reply == "申请被驳回后，请先修改申请内容，再重新提交审批。"
    assert adapter.requests[0].max_output_tokens == 256
    assert adapter.requests[0].enable_thinking is False
    assert adapter.requests[1].max_output_tokens == 1200
    assert adapter.requests[1].enable_thinking is False
    assert result.review is not None and result.review.passed is True
    assert [request.purpose for request in adapter.requests] == [
        ModelPurpose.ROUTER,
        ModelPurpose.COMPOSE,
    ]
    assert result.trace_events[1].name == "model_router"
    compose_trace = next(item for item in result.trace_events if item.name == "compose_answer")
    assert compose_trace.result["model_used"] is True


@pytest.mark.asyncio
async def test_pending_confirmation_is_restored_from_backend_conversation_state() -> None:
    restored = ConversationStateData(
        conversation_id=1,
        current_action="CHAT",
        collected_data={
            "pending_action": {
                "action_type": "SUBMIT_PURCHASE_REQUEST",
                "draft": {"status": "DRAFT"},
                "requires_confirmation": True,
            }
        },
        awaiting_confirmation=True,
        restored_from_snapshot=True,
    )
    graph_request = applicant_request("采购流程有哪些规定？").model_copy(
        update={"restored_state": restored}
    )
    result = await ProcurementGraphService(
        settings(),
        knowledge_retriever=FakeRetriever(),
    ).run(graph_request)

    assert result.pending_action is not None
    assert result.review is not None
    assert result.review.requires_human_confirmation is True
    assert result.restored_from_snapshot is True
