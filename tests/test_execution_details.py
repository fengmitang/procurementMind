from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.schemas import (
    GraphError,
    GraphRunResult,
    HITLActionType,
    PendingAction,
    RouteType,
    ToolExecution,
)
from agent_app.graph.service import ProcurementGraphService
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.models.role_schemas import (
    ReviewIssue,
    ReviewIssueCode,
    ReviewOutput,
    ReviewSeverity,
)
from agent_app.observability import build_execution_details
from agent_app.review_policy import ReviewPolicyDecision, ReviewPolicyResult
from tests.test_agent_graph import FakeMCPClient, request


def settings() -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="execution-details-test-secret",
        procurement_backend_url="http://backend.test",
    )


def execution_result(
    *,
    route: RouteType = RouteType.HYBRID,
    reply: str = "可展示的业务回答",
    review: ReviewOutput | None = None,
    review_policy: ReviewPolicyResult | None = None,
    errors: list[GraphError] | None = None,
    tool_success: bool = True,
) -> GraphRunResult:
    return GraphRunResult(
        task_id=uuid4(),
        trace_id="trace-execution-status",
        conversation_id=1,
        route=route,
        reply=reply,
        purchase_request_id=101,
        restored_from_snapshot=False,
        duration_ms=1,
        step_count=1,
        tool_call_count=1,
        evidence=[],
        tool_results=[
            ToolExecution(
                name="get_purchase_request",
                success=tool_success,
                code="OK" if tool_success else "TOOL_FAILED",
                source="/api/v1/test",
                trace_id="trace-execution-status",
                duration_ms=1,
                data={"requirement_id": 101} if tool_success else None,
            )
        ],
        errors=errors or [],
        trace_events=[],
        review=review,
        review_policy=review_policy,
    )


def execution_status(result: GraphRunResult) -> str:
    return build_execution_details(
        result,
        model_configured=False,
        model_provider=None,
        model_name=None,
    ).status


def passed_review() -> ReviewOutput:
    return ReviewOutput(
        passed=True,
        issues=[],
        requires_human_confirmation=False,
    )


def blocked_review() -> ReviewOutput:
    return ReviewOutput(
        passed=False,
        issues=[
            ReviewIssue(
                code=ReviewIssueCode.MISSING_EVIDENCE,
                severity=ReviewSeverity.BLOCKING,
                message="缺少必要证据",
            )
        ],
        requires_human_confirmation=False,
    )


def policy(decision: ReviewPolicyDecision) -> ReviewPolicyResult:
    return ReviewPolicyResult(decision=decision)


def test_successful_hybrid_execution_can_be_complete() -> None:
    result = execution_result(
        review=passed_review(),
        review_policy=policy(ReviewPolicyDecision.PASS),
    )

    assert execution_status(result) == "COMPLETE"


def test_hybrid_execution_with_blocked_review_is_partial() -> None:
    result = execution_result(
        review=blocked_review(),
        review_policy=policy(ReviewPolicyDecision.BLOCK),
    )

    assert execution_status(result) == "PARTIAL"


def test_hybrid_warning_review_can_remain_complete() -> None:
    result = execution_result(
        review=blocked_review(),
        review_policy=policy(ReviewPolicyDecision.WARN),
    )

    assert execution_status(result) == "COMPLETE"


def test_read_only_review_unavailable_fails_soft() -> None:
    result = execution_result(
        review_policy=policy(ReviewPolicyDecision.REVIEW_UNAVAILABLE),
    )

    assert execution_status(result) == "COMPLETE"


def test_write_review_unavailable_fails_safe() -> None:
    result = execution_result(
        review_policy=policy(ReviewPolicyDecision.REVIEW_UNAVAILABLE),
    ).model_copy(
        update={
            "pending_action": PendingAction(
                action_type=HITLActionType.CREATE_PURCHASE_DRAFT,
                draft={"device_name": "测试设备"},
            )
        }
    )

    assert execution_status(result) == "PARTIAL"


def test_hybrid_execution_with_unhandled_error_is_partial() -> None:
    error = GraphError(code="UNHANDLED", message="未处理错误")

    assert execution_status(execution_result(errors=[error])) == "PARTIAL"


def test_non_hybrid_successful_execution_remains_complete() -> None:
    result = execution_result(
        route=RouteType.REALTIME_BUSINESS,
        review=passed_review(),
    )

    assert execution_status(result) == "COMPLETE"


def test_empty_reply_is_partial() -> None:
    assert execution_status(execution_result(reply="", review=passed_review())) == "PARTIAL"


def test_existing_failed_condition_remains_failed() -> None:
    error = GraphError(code="TOOL_FAILED", message="工具失败")
    result = execution_result(
        errors=[error],
        tool_success=False,
    )

    assert execution_status(result) == "FAILED"


@pytest.mark.asyncio
async def test_execution_details_restore_graph_tool_and_usage_facts() -> None:
    client = FakeMCPClient(
        MCPToolResponse.ok(
            {
                "requirement_id": 91007,
                "requirement_no": "TEST-PR-91007",
                "status": "COMPLETED",
                "current_handler": None,
            },
            source="/api/v1/requirements/91007",
            trace_id="trace-graph",
        )
    )

    @asynccontextmanager
    async def factory(*_args):
        yield client

    result = await ProcurementGraphService(
        settings(),
        mcp_client_factory=factory,
    ).run(request("查询采购申请 91007 当前状态"))
    details = build_execution_details(
        result,
        model_configured=False,
        model_provider=None,
        model_name=None,
    )

    assert details.trace_id == "trace-graph"
    assert details.route == RouteType.REALTIME_BUSINESS.value
    assert details.status == "COMPLETE"
    assert details.duration_ms >= 0
    assert [event.name for event in details.trace_events] == [
        "load_context",
        "first_version_router",
        "get_purchase_request",
        "sufficiency_check",
        "compose_answer",
        "review",
        "confirmation",
        "finalize",
    ]
    assert details.tools[0].name == "get_purchase_request"
    assert details.tools[0].trace_id == details.trace_id
    assert details.model_usage.call_count == 0
    assert details.model_usage.total_tokens is None
    assert details.model_usage.estimated_cost is None
    assert {item.name: item.status for item in details.components} == {
        "GRAPH": "SUCCESS",
        "MCP": "SUCCESS",
        "MODEL": "SKIPPED",
        "RAG": "SKIPPED",
        "REVIEW": "SUCCESS",
    }


@pytest.mark.asyncio
async def test_execution_details_mark_unavailable_knowledge_route() -> None:
    client = FakeMCPClient(
        MCPToolResponse.failure(
            "UNUSED",
            "unused",
            source="unused",
            trace_id="trace-graph",
        )
    )

    @asynccontextmanager
    async def factory(*_args):
        yield client

    result = await ProcurementGraphService(
        settings(),
        mcp_client_factory=factory,
    ).run(request("采购流程有哪些规定"))
    details = build_execution_details(
        result,
        model_configured=False,
        model_provider=None,
        model_name=None,
    )

    assert details.status == "NOT_AVAILABLE"
    assert details.tool_call_count == 0
    assert details.tools == []
