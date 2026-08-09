import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, cast

from langgraph.graph import END, START, StateGraph

from agent_app.analysis.executor import AnalysisExecutor
from agent_app.analysis.schemas import AnalysisOutput
from agent_app.analysis.service import AnalysisAgentService
from agent_app.core.config import AgentSettings
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.router import FirstVersionRouter
from agent_app.graph.schemas import (
    Evidence,
    GraphError,
    GraphRunRequest,
    GraphRunResult,
    GraphState,
    PendingAction,
    RouteType,
    ToolExecution,
    TraceEvent,
    TraceEventType,
)
from agent_app.investigation.schemas import EvidenceStatus, RiskInvestigationOutput
from agent_app.investigation.service import RiskInvestigationService
from agent_app.mcp.client import MCPClientError, ProcurementMCPClient
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.models.role_schemas import (
    ComposeCitation,
    ComposeOutput,
    ReviewIssue,
    ReviewIssueCode,
    ReviewOutput,
    ReviewSeverity,
)
from agent_app.models.roles import StructuredModelRoles
from agent_app.models.runner import StructuredModelRunError
from agent_app.rag.schemas import RetrievalFilters, RetrievalResult
from agent_app.resilience import AsyncCircuitBreaker
from agent_app.resilience.mcp import CircuitProtectedMCPClient
from agent_app.schemas.analytics import AnalyticsQueryInput
from agent_app.schemas.backend import BackendIdentity


class MCPToolClient(Protocol):
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResponse: ...


class KnowledgeRetrieverProtocol(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult: ...


MCPClientFactory = Callable[
    [AgentSettings, BackendIdentity, str],
    AbstractAsyncContextManager[MCPToolClient],
]


def default_mcp_client_factory(
    settings: AgentSettings,
    identity: BackendIdentity,
    trace_id: str,
) -> AbstractAsyncContextManager[MCPToolClient]:
    return cast(
        AbstractAsyncContextManager[MCPToolClient],
        ProcurementMCPClient(settings, identity, trace_id),
    )


class ProcurementGraphService:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        router: FirstVersionRouter | None = None,
        mcp_client_factory: MCPClientFactory = default_mcp_client_factory,
        analysis_agent: AnalysisAgentService | None = None,
        risk_investigation: RiskInvestigationService | None = None,
        knowledge_retriever: KnowledgeRetrieverProtocol | None = None,
        model_roles: StructuredModelRoles | None = None,
    ) -> None:
        self.settings = settings
        self.router = router or FirstVersionRouter()
        self.mcp_client_factory = mcp_client_factory
        self.analysis_agent = analysis_agent or AnalysisAgentService(
            executor=AnalysisExecutor(max_tool_calls=settings.max_tool_calls)
        )
        self.risk_investigation = risk_investigation or RiskInvestigationService(
            max_tool_calls=settings.max_tool_calls
        )
        self.knowledge_retriever = knowledge_retriever
        self.model_roles = model_roles
        self.mcp_circuit_breaker = AsyncCircuitBreaker(
            failure_threshold=settings.mcp_circuit_failure_threshold,
            recovery_timeout_seconds=settings.mcp_circuit_recovery_timeout_seconds,
        )
        self.graph = self._build_graph()

    def set_knowledge_retriever(self, retriever: KnowledgeRetrieverProtocol) -> None:
        self.knowledge_retriever = retriever

    def set_model_roles(self, model_roles: StructuredModelRoles) -> None:
        self.model_roles = model_roles

    async def run(self, request: GraphRunRequest) -> GraphRunResult:
        started = time.perf_counter()
        restored_analysis_query = GraphMemoryMapper.analysis_query(request)
        restored_pending_action = GraphMemoryMapper.pending_action(request)
        initial: GraphState = {
            "task_id": str(request.task_id),
            "trace_id": request.trace_id,
            "conversation_id": request.conversation_id,
            "identity": request.identity.model_dump(mode="json"),
            "current_user": request.current_user.model_dump(mode="json"),
            "message": request.message,
            "purchase_request_id": GraphMemoryMapper.purchase_request_id(request),
            "restored_from_snapshot": bool(
                request.restored_state and request.restored_state.restored_from_snapshot
            ),
            "step_count": 0,
            "tool_call_count": 0,
            "evidence": [],
            "tool_results": [],
            "errors": [],
            "trace_events": [],
            "reply": "",
            "analysis_query_context": (
                restored_analysis_query.model_dump(mode="json") if restored_analysis_query else None
            ),
            "analysis": None,
            "risk_investigation": None,
            "knowledge": None,
            "review": None,
            "evidence_sufficient": False,
            "pending_action": (
                restored_pending_action.model_dump(mode="json") if restored_pending_action else None
            ),
            "compose_output": None,
        }
        final = await self.graph.ainvoke(
            initial,
            config={
                "recursion_limit": max(15, self.settings.max_execution_steps + 8),
                "configurable": {"thread_id": str(request.conversation_id)},
            },
        )
        return GraphRunResult(
            task_id=request.task_id,
            trace_id=request.trace_id,
            conversation_id=request.conversation_id,
            route=RouteType(final["route"]),
            reply=final["reply"],
            purchase_request_id=final.get("purchase_request_id"),
            restored_from_snapshot=final["restored_from_snapshot"],
            duration_ms=self._elapsed_ms(started),
            step_count=final["step_count"],
            tool_call_count=final["tool_call_count"],
            evidence=[Evidence.model_validate(item) for item in final["evidence"]],
            tool_results=[ToolExecution.model_validate(item) for item in final["tool_results"]],
            errors=[GraphError.model_validate(item) for item in final["errors"]],
            trace_events=[TraceEvent.model_validate(item) for item in final["trace_events"]],
            analysis=(
                AnalysisOutput.model_validate(final["analysis"]) if final.get("analysis") else None
            ),
            risk_investigation=(
                RiskInvestigationOutput.model_validate(final["risk_investigation"])
                if final.get("risk_investigation")
                else None
            ),
            knowledge=(
                RetrievalResult.model_validate(final["knowledge"])
                if final.get("knowledge")
                else None
            ),
            review=(ReviewOutput.model_validate(final["review"]) if final.get("review") else None),
            evidence_sufficient=final.get("evidence_sufficient", False),
            pending_action=(
                PendingAction.model_validate(final["pending_action"])
                if final.get("pending_action")
                else None
            ),
        )

    def _build_graph(self):
        builder = StateGraph(GraphState)
        builder.add_node("load_context", self._load_context_node)
        builder.add_node("route", self._route_node)
        builder.add_node("knowledge", self._knowledge_node)
        builder.add_node("realtime_query", self._realtime_query_node)
        builder.add_node("analysis", self._analysis_node)
        builder.add_node("risk_investigation", self._risk_investigation_node)
        builder.add_node("form_prefill", self._form_prefill_node)
        builder.add_node("sufficiency_check", self._sufficiency_node)
        builder.add_node("compose", self._answer_node)
        builder.add_node("review", self._review_node)
        builder.add_node("confirmation", self._confirmation_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "load_context")
        builder.add_edge("load_context", "route")
        builder.add_conditional_edges(
            "route",
            self._after_route,
            {
                "realtime_query": "realtime_query",
                "knowledge": "knowledge",
                "analysis": "analysis",
                "risk_investigation": "risk_investigation",
                "form_prefill": "form_prefill",
            },
        )
        builder.add_conditional_edges(
            "knowledge",
            self._after_knowledge,
            {"realtime_query": "realtime_query", "sufficiency_check": "sufficiency_check"},
        )
        builder.add_edge("realtime_query", "sufficiency_check")
        builder.add_edge("analysis", "sufficiency_check")
        builder.add_edge("risk_investigation", "sufficiency_check")
        builder.add_edge("form_prefill", "sufficiency_check")
        builder.add_edge("sufficiency_check", "compose")
        builder.add_edge("compose", "review")
        builder.add_edge("review", "confirmation")
        builder.add_edge("confirmation", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile()

    async def _load_context_node(self, state: GraphState) -> dict[str, Any]:
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="load_context",
            status="SUCCESS",
            result={
                "conversation_id": state["conversation_id"],
                "restored_from_snapshot": state["restored_from_snapshot"],
            },
        )
        return {"trace_events": [*state["trace_events"], trace.model_dump(mode="json")]}

    async def _route_node(self, state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        model_error: StructuredModelRunError | None = None
        if self.model_roles is not None:
            try:
                model_route = await self.model_roles.route(state["message"])
                route = RouteType(model_route.route.value)
            except StructuredModelRunError as exc:
                model_error = exc
                route = self.router.classify(state["message"])
        else:
            route = self.router.classify(state["message"])
        requirement_id = None
        if route in {
            RouteType.REALTIME_BUSINESS,
            RouteType.HYBRID,
            RouteType.RISK_INVESTIGATION,
        }:
            requirement_id = self.router.extract_requirement_id(state["message"])
        trace = TraceEvent(
            event_type=TraceEventType.ROUTE,
            name="model_router" if self.model_roles is not None else "first_version_router",
            status="FALLBACK" if model_error else "SUCCESS",
            duration_ms=self._elapsed_ms(started),
            arguments={"message_length": len(state["message"])},
            result={"route": route.value, "requirement_id": requirement_id},
            error_code=model_error.code if model_error else None,
        )
        updates: dict[str, Any] = {
            "route": route.value,
            "purchase_request_id": requirement_id or state.get("purchase_request_id"),
            "step_count": state["step_count"] + 1,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }
        if model_error:
            error = GraphError(
                code=model_error.code,
                message=f"模型路由失败，已使用确定性 Router：{model_error.message}",
                source="model_router",
            )
            updates["errors"] = [*state["errors"], error.model_dump(mode="json")]
        return updates

    @staticmethod
    def _after_route(state: GraphState) -> str:
        if state["route"] == RouteType.REALTIME_BUSINESS.value:
            return "realtime_query"
        if state["route"] in {RouteType.KNOWLEDGE.value, RouteType.HYBRID.value}:
            return "knowledge"
        if state["route"] == RouteType.COMPLEX_QUERY.value:
            return "analysis"
        if state["route"] == RouteType.RISK_INVESTIGATION.value:
            return "risk_investigation"
        return "form_prefill"

    @staticmethod
    def _after_knowledge(state: GraphState) -> str:
        return "realtime_query" if state["route"] == RouteType.HYBRID.value else "sufficiency_check"

    async def _knowledge_node(self, state: GraphState) -> dict[str, Any]:
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        started = time.perf_counter()
        if self.knowledge_retriever is None:
            return self._knowledge_failure(
                state,
                "RAG_NOT_CONFIGURED",
                "知识检索服务尚未配置",
                started,
            )
        current_user = state["current_user"]
        roles = [
            item["role_code"]
            for item in current_user.get("roles", [])
            if isinstance(item, dict) and isinstance(item.get("role_code"), str)
        ]
        if not roles:
            return self._knowledge_failure(
                state,
                "KNOWLEDGE_ROLE_REQUIRED",
                "当前用户没有可用于知识过滤的可信角色",
                started,
            )
        try:
            result = await self.knowledge_retriever.retrieve(
                state["message"],
                filters=RetrievalFilters(allowed_roles=roles),
                trace_id=state["trace_id"],
            )
        except Exception:
            return self._knowledge_failure(
                state,
                "RAG_RETRIEVAL_FAILURE",
                "知识检索发生受控故障",
                started,
            )
        evidence = [
            Evidence(
                evidence_type="RAG_KNOWLEDGE",
                source=item.citation.source_path,
                reference_id=item.citation.citation_id,
                data={
                    "citation": item.citation.model_dump(mode="json"),
                    "content": item.context_content,
                    "rerank_score": item.rerank_score,
                    "parent_expanded": item.parent_expanded,
                },
            )
            for item in result.evidences
        ]
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="knowledge_retrieval",
            status="SUCCESS" if result.answerable else "PARTIAL",
            duration_ms=self._elapsed_ms(started),
            result={
                "answerable": result.answerable,
                "evidence_count": len(result.evidences),
                "rewrite_applied": result.rewrite_applied,
                "retrieval_trace_id": result.trace.trace_id,
            },
        )
        updates: dict[str, Any] = {
            "step_count": state["step_count"] + 1,
            "knowledge": result.model_dump(mode="json"),
            "evidence": [
                *state["evidence"],
                *(item.model_dump(mode="json") for item in evidence),
            ],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }
        if not result.answerable:
            error = GraphError(
                code="RAG_EVIDENCE_INSUFFICIENT",
                message=result.abstention_reason or "未检索到可引用知识",
                source="rag",
            )
            updates["errors"] = [*state["errors"], error.model_dump(mode="json")]
        return updates

    async def _form_prefill_node(self, state: GraphState) -> dict[str, Any]:
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        pending = PendingAction(
            action_type="SUBMIT_PURCHASE_REQUEST",
            draft={"source_message": state["message"], "status": "DRAFT"},
        )
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="form_prefill",
            status="DRAFTED",
            result={"action_type": pending.action_type, "executed": False},
        )
        return {
            "step_count": state["step_count"] + 1,
            "pending_action": pending.model_dump(mode="json"),
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    async def _sufficiency_node(self, state: GraphState) -> dict[str, Any]:
        route = RouteType(state["route"])
        knowledge = (
            RetrievalResult.model_validate(state["knowledge"]) if state.get("knowledge") else None
        )
        knowledge_ok = bool(knowledge and knowledge.answerable)
        realtime_ok = any(
            ToolExecution.model_validate(item).success for item in state["tool_results"]
        )
        sufficient = {
            RouteType.KNOWLEDGE: knowledge_ok,
            RouteType.REALTIME_BUSINESS: realtime_ok,
            RouteType.HYBRID: knowledge_ok and realtime_ok,
            RouteType.COMPLEX_QUERY: state.get("analysis") is not None,
            RouteType.RISK_INVESTIGATION: state.get("risk_investigation") is not None,
            RouteType.FORM_PREFILL: state.get("pending_action") is not None,
        }[route]
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="sufficiency_check",
            status="SUCCESS" if sufficient else "INSUFFICIENT",
            result={
                "knowledge_available": knowledge_ok,
                "realtime_fact_available": realtime_ok,
                "sufficient": sufficient,
            },
        )
        step_count = state["step_count"]
        if step_count < self.settings.max_execution_steps:
            step_count += 1
        return {
            "step_count": step_count,
            "evidence_sufficient": sufficient,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    async def _review_node(self, state: GraphState) -> dict[str, Any]:
        issues: list[ReviewIssue] = []
        if not state.get("evidence_sufficient", False):
            issues.append(
                ReviewIssue(
                    code=ReviewIssueCode.MISSING_EVIDENCE,
                    severity=ReviewSeverity.BLOCKING,
                    message="当前回答缺少完成该问题所需的可见证据",
                )
            )
        if state.get("pending_action"):
            issues.append(
                ReviewIssue(
                    code=ReviewIssueCode.HUMAN_CONFIRMATION_REQUIRED,
                    severity=ReviewSeverity.BLOCKING,
                    message="正式业务动作只能在人工确认后由采购后端执行",
                )
            )
        deterministic_review = ReviewOutput(
            passed=not any(item.severity is ReviewSeverity.BLOCKING for item in issues),
            issues=issues,
            requires_human_confirmation=state.get("pending_action") is not None,
        )
        review = deterministic_review
        model_error: StructuredModelRunError | None = None
        if self.model_roles is not None and state.get("compose_output"):
            try:
                review = await self.model_roles.review(
                    state["message"],
                    ComposeOutput.model_validate(state["compose_output"]),
                    state["evidence"],
                )
            except StructuredModelRunError as exc:
                model_error = exc
                review = deterministic_review
        if state.get("pending_action") and not review.requires_human_confirmation:
            confirmation_issue = ReviewIssue(
                code=ReviewIssueCode.HUMAN_CONFIRMATION_REQUIRED,
                severity=ReviewSeverity.BLOCKING,
                message="正式业务动作只能在人工确认后由采购后端执行",
            )
            review = review.model_copy(
                update={
                    "passed": False,
                    "issues": [*review.issues, confirmation_issue],
                    "requires_human_confirmation": True,
                }
            )
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="review",
            status="FALLBACK" if model_error else "SUCCESS" if review.passed else "BLOCKED",
            result={
                "passed": review.passed,
                "issue_codes": [item.code.value for item in review.issues],
                "model_used": self.model_roles is not None and model_error is None,
            },
            error_code=model_error.code if model_error else None,
        )
        step_count = state["step_count"]
        if step_count < self.settings.max_execution_steps:
            step_count += 1
        updates: dict[str, Any] = {
            "step_count": step_count,
            "review": review.model_dump(mode="json"),
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }
        if model_error:
            error = GraphError(
                code=model_error.code,
                message=f"模型 Review 失败，已使用确定性证据审查：{model_error.message}",
                source="model_review",
            )
            updates["errors"] = [*state["errors"], error.model_dump(mode="json")]
        return updates

    async def _confirmation_node(self, state: GraphState) -> dict[str, Any]:
        required = state.get("pending_action") is not None
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="confirmation",
            status="REQUIRED" if required else "SKIPPED",
            result={"requires_human_confirmation": required, "executed": False},
        )
        return {"trace_events": [*state["trace_events"], trace.model_dump(mode="json")]}

    async def _finalize_node(self, state: GraphState) -> dict[str, Any]:
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="finalize",
            status="SUCCESS",
            result={
                "conversation_id": state["conversation_id"],
                "pending_confirmation": state.get("pending_action") is not None,
            },
        )
        return {"trace_events": [*state["trace_events"], trace.model_dump(mode="json")]}

    async def _risk_investigation_node(self, state: GraphState) -> dict[str, Any]:
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        requirement_id = state.get("purchase_request_id")
        if requirement_id is None:
            error = GraphError(
                code="PURCHASE_REQUEST_ID_REQUIRED",
                message="请提供需要调查的采购申请 ID",
                source="risk_investigation",
            )
            return {
                "step_count": state["step_count"] + 1,
                "errors": [*state["errors"], error.model_dump(mode="json")],
            }
        started = time.perf_counter()
        identity = BackendIdentity.model_validate(state["identity"])
        try:
            async with self.mcp_client_factory(
                self.settings,
                identity,
                state["trace_id"],
            ) as client:
                protected_client = CircuitProtectedMCPClient(
                    client,
                    self.mcp_circuit_breaker,
                )
                output = await self.risk_investigation.run(requirement_id, protected_client)
        except Exception:
            return self._analysis_failure(
                state,
                "RISK_INVESTIGATION_FAILURE",
                "审批风险调查发生未预期故障",
                started,
            )
        tool_evidence = [item for item in output.evidence if item.tool_name is not None]
        executions = [
            ToolExecution(
                name=item.tool_name or "unknown",
                arguments=item.arguments,
                success=item.status is EvidenceStatus.SUCCESS,
                code=item.code or "OK",
                source=item.source,
                trace_id=item.trace_id or state["trace_id"],
                duration_ms=item.duration_ms,
                data=item.data,
            )
            for item in tool_evidence
        ]
        graph_evidence = [
            Evidence(
                evidence_type=f"INVESTIGATION_{item.kind.value}",
                source=item.source,
                reference_id=item.evidence_id,
                data=item.model_dump(mode="json"),
            )
            for item in output.evidence
        ]
        errors = [
            GraphError(
                code=item.code or "EVIDENCE_UNAVAILABLE",
                message=item.message or "调查证据不可用",
                source=item.source,
            )
            for item in output.evidence
            if item.status is EvidenceStatus.FAILED
        ]
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="risk_investigation",
            status="SUCCESS" if output.complete else "PARTIAL",
            duration_ms=self._elapsed_ms(started),
            arguments={"requirement_id": requirement_id},
            result={
                "summary_items": len(output.summary_items),
                "evidence_items": len(output.evidence),
                "program_review_passed": output.review.passed,
                "complete": output.complete,
            },
        )
        return {
            "step_count": state["step_count"] + 1,
            "tool_call_count": state["tool_call_count"] + len(tool_evidence),
            "tool_results": [
                *state["tool_results"],
                *(item.model_dump(mode="json") for item in executions),
            ],
            "evidence": [
                *state["evidence"],
                *(item.model_dump(mode="json") for item in graph_evidence),
            ],
            "errors": [
                *state["errors"],
                *(item.model_dump(mode="json") for item in errors),
            ],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
            "risk_investigation": output.model_dump(mode="json"),
        }

    async def _analysis_node(self, state: GraphState) -> dict[str, Any]:
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        if state["tool_call_count"] >= self.settings.max_tool_calls:
            return self._boundary_failure(
                state,
                "GRAPH_TOOL_CALL_LIMIT",
                "已达到最大工具调用次数",
            )
        started = time.perf_counter()
        identity = BackendIdentity.model_validate(state["identity"])
        previous_query = state.get("analysis_query_context")
        try:
            async with self.mcp_client_factory(
                self.settings,
                identity,
                state["trace_id"],
            ) as client:
                protected_client = CircuitProtectedMCPClient(
                    client,
                    self.mcp_circuit_breaker,
                )
                output = await self.analysis_agent.run(
                    state["message"],
                    protected_client,
                    previous_query=(
                        AnalyticsQueryInput.model_validate(previous_query)
                        if previous_query
                        else None
                    ),
                )
        except MCPClientError as exc:
            return self._analysis_failure(state, exc.code, exc.message, started)
        except ValueError as exc:
            return self._analysis_failure(
                state,
                "ANALYSIS_PLAN_INVALID",
                str(exc),
                started,
            )
        except StructuredModelRunError as exc:
            return self._analysis_failure(state, exc.code, exc.message, started)
        except Exception:
            return self._analysis_failure(
                state,
                "ANALYSIS_UNEXPECTED_FAILURE",
                "分析执行发生未预期故障",
                started,
            )

        executions = [
            ToolExecution(
                name=item.tool.value,
                arguments=item.arguments,
                success=item.success,
                code=item.code,
                source=item.source,
                trace_id=item.trace_id,
                duration_ms=item.duration_ms,
                data=item.data,
            )
            for item in output.step_results
        ]
        evidence = [
            Evidence(
                evidence_type="MCP_TOOL_RESULT",
                source=item.source,
                reference_id=item.step_id,
                data=item.data,
            )
            for item in output.step_results
            if item.success and item.data is not None
        ]
        errors = [
            GraphError(code=item.code, message=item.message, source=item.source)
            for item in output.step_results
            if not item.success
        ]
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="analysis_agent",
            status="PARTIAL" if output.partial_success else "SUCCESS",
            duration_ms=self._elapsed_ms(started),
            arguments={"planned_steps": len(output.plan.steps)},
            result={
                "successful_steps": sum(item.success for item in output.step_results),
                "failed_steps": sum(not item.success for item in output.step_results),
            },
        )
        return {
            "step_count": state["step_count"] + 1,
            "tool_call_count": state["tool_call_count"] + len(output.step_results),
            "tool_results": [
                *state["tool_results"],
                *(item.model_dump(mode="json") for item in executions),
            ],
            "evidence": [
                *state["evidence"],
                *(item.model_dump(mode="json") for item in evidence),
            ],
            "errors": [
                *state["errors"],
                *(item.model_dump(mode="json") for item in errors),
            ],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
            "analysis": output.model_dump(mode="json"),
            "analysis_query_context": (
                output.effective_query.model_dump(mode="json")
                if output.effective_query
                else state.get("analysis_query_context")
            ),
        }

    async def _realtime_query_node(self, state: GraphState) -> dict[str, Any]:
        source = "mcp://get_purchase_request"
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        requirement_id = state.get("purchase_request_id")
        if requirement_id is None:
            error = GraphError(
                code="PURCHASE_REQUEST_ID_REQUIRED",
                message="请提供采购申请 ID，例如：查询采购申请 91007 的当前状态",
                source=source,
            )
            trace = TraceEvent(
                event_type=TraceEventType.ERROR,
                name="get_purchase_request",
                status="SKIPPED",
                error_code=error.code,
            )
            return {
                "step_count": state["step_count"] + 1,
                "errors": [*state["errors"], error.model_dump(mode="json")],
                "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
            }
        if state["tool_call_count"] >= self.settings.max_tool_calls:
            return self._boundary_failure(
                state,
                "GRAPH_TOOL_CALL_LIMIT",
                "已达到最大工具调用次数",
            )

        started = time.perf_counter()
        arguments = {"requirement_id": requirement_id}
        identity = BackendIdentity.model_validate(state["identity"])
        try:
            async with self.mcp_client_factory(
                self.settings,
                identity,
                state["trace_id"],
            ) as client:
                protected_client = CircuitProtectedMCPClient(
                    client,
                    self.mcp_circuit_breaker,
                )
                response = await protected_client.call_tool("get_purchase_request", arguments)
        except MCPClientError as exc:
            return self._tool_transport_failure(state, exc, arguments, started)
        except Exception:
            return self._tool_transport_failure(
                state,
                MCPClientError("MCP_UNEXPECTED_FAILURE", "MCP 工具执行发生未预期故障"),
                arguments,
                started,
            )

        duration_ms = self._elapsed_ms(started)
        execution = ToolExecution(
            name="get_purchase_request",
            arguments=arguments,
            success=response.success,
            code=response.code,
            source=response.source,
            trace_id=response.trace_id,
            duration_ms=duration_ms,
            data=response.data,
        )
        trace = TraceEvent(
            event_type=TraceEventType.TOOL,
            name="get_purchase_request",
            status="SUCCESS" if response.success else "FAILED",
            duration_ms=duration_ms,
            arguments=arguments,
            result=response.model_dump(mode="json"),
            error_code=None if response.success else response.code,
        )
        updates: dict[str, Any] = {
            "step_count": state["step_count"] + 1,
            "tool_call_count": state["tool_call_count"] + 1,
            "tool_results": [*state["tool_results"], execution.model_dump(mode="json")],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }
        if response.success:
            evidence = Evidence(
                evidence_type="MCP_TOOL_RESULT",
                source=response.source,
                reference_id=str(requirement_id),
                data=response.data,
            )
            updates["evidence"] = [*state["evidence"], evidence.model_dump(mode="json")]
        else:
            error = GraphError(
                code=response.code,
                message=response.message,
                source=response.source,
            )
            updates["errors"] = [*state["errors"], error.model_dump(mode="json")]
        return updates

    async def _answer_node(self, state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
        reply = self._compose_answer(state)
        citations: list[ComposeCitation] = []
        if state.get("knowledge"):
            knowledge = RetrievalResult.model_validate(state["knowledge"])
            citations = [
                ComposeCitation(
                    citation_id=item.citation.citation_id,
                    claim=item.context_content[:1000],
                )
                for item in knowledge.evidences
            ]
        compose_output = ComposeOutput(
            answer=reply,
            citations=citations,
            requires_human_confirmation=state.get("pending_action") is not None,
        )
        model_error: StructuredModelRunError | None = None
        if self.model_roles is not None and state["evidence"]:
            try:
                compose_output = await self.model_roles.compose(
                    state["message"],
                    state["evidence"],
                    allowed_citation_ids={item.citation_id for item in citations},
                )
                reply = compose_output.answer
            except StructuredModelRunError as exc:
                model_error = exc
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="compose_answer",
            status="FALLBACK" if model_error else "SUCCESS",
            duration_ms=self._elapsed_ms(started),
            result={
                "reply_length": len(reply),
                "model_used": self.model_roles is not None and model_error is None,
                "citation_ids": [item.citation_id for item in compose_output.citations],
            },
            error_code=model_error.code if model_error else None,
        )
        step_count = state["step_count"]
        if step_count < self.settings.max_execution_steps:
            step_count += 1
        updates: dict[str, Any] = {
            "reply": reply,
            "compose_output": compose_output.model_dump(mode="json"),
            "step_count": step_count,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }
        if model_error:
            error = GraphError(
                code=model_error.code,
                message=f"模型 Compose 失败，已使用确定性证据模板：{model_error.message}",
                source="model_compose",
            )
            updates["errors"] = [*state["errors"], error.model_dump(mode="json")]
        return updates

    def _compose_answer(self, state: GraphState) -> str:
        route = RouteType(state["route"])
        if route is RouteType.RISK_INVESTIGATION and state.get("risk_investigation"):
            return RiskInvestigationOutput.model_validate(state["risk_investigation"]).answer
        if route is RouteType.COMPLEX_QUERY and state.get("analysis"):
            return AnalysisOutput.model_validate(state["analysis"]).answer
        if route is RouteType.FORM_PREFILL:
            return (
                "已根据当前消息生成采购申请预填草稿，但尚未提交。"
                "提交采购申请属于正式业务动作，必须由你人工确认后再调用采购后端。"
            )
        knowledge_reply = self._knowledge_answer(state)
        realtime_reply = self._realtime_answer(state)
        if route is RouteType.KNOWLEDGE:
            return knowledge_reply or self._last_error_reply(
                state,
                "未检索到足够的可见制度证据，本次不生成知识结论。",
            )
        if route is RouteType.REALTIME_BUSINESS:
            if realtime_reply:
                return realtime_reply
            if state["errors"]:
                error = GraphError.model_validate(state["errors"][-1])
                return f"暂时无法确认采购申请的实时状态：{error.message}。"
            return "采购后端未返回可确认的申请数据，本次不会猜测状态。"
        if route is RouteType.HYBRID:
            parts = [part for part in (realtime_reply, knowledge_reply) if part]
            if parts:
                if not realtime_reply:
                    parts.append("实时业务事实不可用，本次不会使用知识库内容推测当前状态。")
                if not knowledge_reply:
                    parts.append("未检索到足够制度证据，本次只确认实时业务事实。")
                return "\n\n".join(parts)
            return self._last_error_reply(state, "实时事实和制度证据均不可用，本次不生成结论。")
        if state["errors"]:
            error = GraphError.model_validate(state["errors"][-1])
            if route is RouteType.COMPLEX_QUERY:
                return f"暂时无法完成采购分析：{error.message}。"
            if route is RouteType.RISK_INVESTIGATION:
                return f"暂时无法完成风险调查：{error.message}。本次不形成风险结论。"
        if route is RouteType.COMPLEX_QUERY:
            return "分析工具未返回可确认的数据，本次不会猜测结果。"
        return "请提供需要调查的采购申请 ID。"

    @staticmethod
    def _knowledge_answer(state: GraphState) -> str | None:
        if not state.get("knowledge"):
            return None
        result = RetrievalResult.model_validate(state["knowledge"])
        if not result.answerable:
            return None
        parts = ["根据当前用户可见的知识库证据："]
        for item in result.evidences:
            citation = item.citation
            parts.append(f"{item.context_content} [{citation.citation_id}]")
        parts.append("来源：")
        for citation in result.citations:
            section = " > ".join(citation.section_path)
            parts.append(
                f"[{citation.citation_id}] {citation.document_title} v{citation.version} / "
                f"{section}（{citation.source_path}:{citation.source_start_line}）"
            )
        return "\n".join(parts)

    @staticmethod
    def _realtime_answer(state: GraphState) -> str | None:
        successful = [
            ToolExecution.model_validate(item)
            for item in state["tool_results"]
            if ToolExecution.model_validate(item).success
        ]
        if not successful:
            return None
        execution = successful[-1]
        if execution.name != "get_purchase_request" or not isinstance(execution.data, dict):
            return None
        data = execution.data
        handler = data.get("current_handler")
        handler_name = handler.get("name") if isinstance(handler, dict) else None
        next_handler = handler_name or "暂无（流程可能已结束或尚未分配）"
        return (
            f"采购申请 {data.get('requirement_no', state.get('purchase_request_id'))} "
            f"当前状态为 {data.get('status', '未知')}，下一处理人为：{next_handler}。"
        )

    @staticmethod
    def _last_error_reply(state: GraphState, fallback: str) -> str:
        if not state["errors"]:
            return fallback
        error = GraphError.model_validate(state["errors"][-1])
        return f"{fallback} 原因：{error.message}"

    def _knowledge_failure(
        self,
        state: GraphState,
        code: str,
        message: str,
        started: float,
    ) -> dict[str, Any]:
        error = GraphError(code=code, message=message, source="rag")
        trace = TraceEvent(
            event_type=TraceEventType.ERROR,
            name="knowledge_retrieval",
            status="FAILED",
            duration_ms=self._elapsed_ms(started),
            error_code=code,
        )
        return {
            "step_count": state["step_count"] + 1,
            "errors": [*state["errors"], error.model_dump(mode="json")],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    def _analysis_failure(
        self,
        state: GraphState,
        code: str,
        message: str,
        started: float,
    ) -> dict[str, Any]:
        error = GraphError(code=code, message=message, source="analysis_agent")
        trace = TraceEvent(
            event_type=TraceEventType.ERROR,
            name="analysis_agent",
            status="FAILED",
            duration_ms=self._elapsed_ms(started),
            error_code=code,
        )
        return {
            "step_count": state["step_count"] + 1,
            "errors": [*state["errors"], error.model_dump(mode="json")],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    def _boundary_failure(
        self,
        state: GraphState,
        code: str,
        message: str,
    ) -> dict[str, Any]:
        error = GraphError(code=code, message=message, source="langgraph")
        trace = TraceEvent(
            event_type=TraceEventType.ERROR,
            name="execution_boundary",
            status="BLOCKED",
            error_code=code,
        )
        return {
            "errors": [*state["errors"], error.model_dump(mode="json")],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    def _tool_transport_failure(
        self,
        state: GraphState,
        exc: MCPClientError,
        arguments: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        duration_ms = self._elapsed_ms(started)
        source = "mcp://get_purchase_request"
        error = GraphError(code=exc.code, message=exc.message, source=source)
        execution = ToolExecution(
            name="get_purchase_request",
            arguments=arguments,
            success=False,
            code=exc.code,
            source=source,
            trace_id=state["trace_id"],
            duration_ms=duration_ms,
        )
        trace = TraceEvent(
            event_type=TraceEventType.TOOL,
            name="get_purchase_request",
            status="FAILED",
            duration_ms=duration_ms,
            arguments=arguments,
            error_code=exc.code,
        )
        return {
            "step_count": state["step_count"] + 1,
            "tool_call_count": state["tool_call_count"] + 1,
            "tool_results": [*state["tool_results"], execution.model_dump(mode="json")],
            "errors": [*state["errors"], error.model_dump(mode="json")],
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, round((time.perf_counter() - started) * 1000))
