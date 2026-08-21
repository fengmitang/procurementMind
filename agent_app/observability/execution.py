from agent_app.graph.schemas import GraphRunResult, RouteType
from agent_app.observability.schemas import (
    ExecutionComponent,
    ExecutionDetails,
    ModelUsageSummary,
)
from agent_app.review_policy import ReviewPolicyDecision


def build_execution_details(
    result: GraphRunResult,
    *,
    model_configured: bool,
    model_provider: str | None,
    model_name: str | None,
) -> ExecutionDetails:
    status = _execution_status(result)
    review = result.review.model_dump(mode="json") if result.review else None
    if review is None and result.risk_investigation:
        review = result.risk_investigation.review.model_dump(mode="json")
    plan = result.analysis.plan.model_dump(mode="json") if result.analysis else None
    model_events = [
        event
        for event in result.trace_events
        if isinstance(event.result, dict) and event.result.get("model_used") is True
    ]
    actual_models = [
        str(event.result["actual_model"])
        for event in model_events
        if isinstance(event.result, dict) and event.result.get("actual_model")
    ]
    return ExecutionDetails(
        trace_id=result.trace_id,
        route=result.route.value,
        status=status,
        duration_ms=result.duration_ms,
        step_count=result.step_count,
        tool_call_count=result.tool_call_count,
        evidence_count=len(result.evidence),
        restored_from_snapshot=result.restored_from_snapshot,
        components=_components(result, model_configured),
        model_usage=ModelUsageSummary(
            configured=model_configured,
            provider=model_provider,
            model=actual_models[-1] if actual_models else model_name,
            call_count=len(model_events),
        ),
        trace_events=result.trace_events,
        tools=result.tool_results,
        plan=plan,
        review=review,
        review_policy=result.review_policy,
        errors=result.errors,
    )


def _execution_status(
    result: GraphRunResult,
) -> str:
    if result.route is RouteType.KNOWLEDGE and any(
        error.code == "RAG_NOT_CONFIGURED" for error in result.errors
    ):
        return "NOT_AVAILABLE"
    has_success = any(item.success for item in result.tool_results)
    if (
        result.errors
        and not has_success
        and result.analysis is None
        and result.risk_investigation is None
        and result.knowledge is None
    ):
        return "FAILED"
    if (
        result.errors
        or not result.reply.strip()
        or (
            result.review_policy is not None
            and result.review_policy.decision is ReviewPolicyDecision.BLOCK
        )
        or (
            result.review_policy is not None
            and result.review_policy.decision is ReviewPolicyDecision.REVIEW_UNAVAILABLE
            and result.pending_action is not None
        )
        or (result.analysis and result.analysis.partial_success)
        or (result.risk_investigation and not result.risk_investigation.complete)
    ):
        return "PARTIAL"
    return "COMPLETE"


def _components(
    result: GraphRunResult,
    model_configured: bool,
) -> list[ExecutionComponent]:
    graph_status = "FAILED" if result.errors and not result.tool_results else "SUCCESS"
    if result.errors and result.tool_results:
        graph_status = "PARTIAL"
    mcp_status = "SKIPPED"
    if result.tool_results:
        mcp_status = (
            "SUCCESS"
            if all(item.success for item in result.tool_results)
            else "PARTIAL"
            if any(item.success for item in result.tool_results)
            else "FAILED"
        )
    review_status = "SKIPPED"
    review_detail = "本次路由不需要 Review"
    if result.review_policy:
        review_status = {
            ReviewPolicyDecision.PASS: "SUCCESS",
            ReviewPolicyDecision.WARN: "PARTIAL",
            ReviewPolicyDecision.BLOCK: "FAILED",
            ReviewPolicyDecision.REVIEW_UNAVAILABLE: "PARTIAL",
        }[result.review_policy.decision]
        review_detail = (
            f"Review Policy {result.review_policy.decision.value}，"
            f"裁决 {len(result.review_policy.issues)} 项问题"
        )
    elif result.risk_investigation:
        review_status = "SUCCESS" if result.risk_investigation.review.passed else "FAILED"
        review_detail = f"程序审查 {result.risk_investigation.review.checked_items} 项风险"
    rag_status = "SKIPPED"
    rag_detail = "本次路由未使用知识检索"
    if result.knowledge:
        rag_status = "SUCCESS" if result.knowledge.answerable else "PARTIAL"
        rag_detail = f"检索到 {len(result.knowledge.evidences)} 条可见知识证据"
    elif result.route in {RouteType.KNOWLEDGE, RouteType.HYBRID}:
        rag_status = "FAILED"
        rag_detail = "知识检索未返回结果"
    elif result.risk_investigation and result.risk_investigation.knowledge_evidence_available:
        rag_status = "SUCCESS"
        rag_detail = "已取得制度证据"
    return [
        ExecutionComponent(
            name="GRAPH",
            status=graph_status,
            detail=f"路由 {result.route.value}，执行 {result.step_count} 个步骤",
        ),
        ExecutionComponent(
            name="MCP",
            status=mcp_status,
            detail=f"执行 {result.tool_call_count} 次受控工具调用",
        ),
        ExecutionComponent(
            name="MODEL",
            status="SKIPPED",
            detail=(
                "本次确定性链路未调用模型"
                if not model_configured
                else "模型已配置，但本次确定性链路未调用"
            ),
        ),
        ExecutionComponent(name="RAG", status=rag_status, detail=rag_detail),
        ExecutionComponent(name="REVIEW", status=review_status, detail=review_detail),
    ]
