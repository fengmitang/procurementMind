import json
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from datetime import date, timedelta
from typing import Any, Protocol, cast

from langgraph.graph import END, START, StateGraph

from agent_app.analysis.executor import AnalysisExecutor
from agent_app.analysis.planner import DeterministicAnalysisPlanner
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
from agent_app.models.protocols import ModelPurpose
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
GraphStreamHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


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
        self._stream_handler: ContextVar[GraphStreamHandler | None] = ContextVar(
            f"graph_stream_handler_{id(self)}", default=None
        )
        self.mcp_circuit_breaker = AsyncCircuitBreaker(
            failure_threshold=settings.mcp_circuit_failure_threshold,
            recovery_timeout_seconds=settings.mcp_circuit_recovery_timeout_seconds,
        )
        self.graph = self._build_graph()

    def set_knowledge_retriever(self, retriever: KnowledgeRetrieverProtocol) -> None:
        self.knowledge_retriever = retriever

    def set_model_roles(self, model_roles: StructuredModelRoles) -> None:
        self.model_roles = model_roles

    async def run(
        self,
        request: GraphRunRequest,
        *,
        stream_handler: GraphStreamHandler | None = None,
    ) -> GraphRunResult:
        started = time.perf_counter()
        restored_analysis_query = GraphMemoryMapper.analysis_query(request)
        restored_pending_action = GraphMemoryMapper.pending_action(request)
        restored_form_draft = GraphMemoryMapper.form_draft(request)
        initial: GraphState = {
            "task_id": str(request.task_id),
            "trace_id": request.trace_id,
            "conversation_id": request.conversation_id,
            "identity": request.identity.model_dump(mode="json"),
            "current_user": request.current_user.model_dump(mode="json"),
            "message": request.message,
            "ui_context": (
                request.ui_context.model_dump(mode="json") if request.ui_context else None
            ),
            "purchase_request_id": (
                request.ui_context.requirement_id
                if request.ui_context
                else GraphMemoryMapper.purchase_request_id(request)
            ),
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
            "form_draft": restored_form_draft or None,
            "form_missing_fields": list(
                request.restored_state.collected_data.get("form_missing_fields", [])
                if request.restored_state
                else []
            ),
        }
        invoke_config = {
            "recursion_limit": max(15, self.settings.max_execution_steps + 8),
            "configurable": {"thread_id": str(request.conversation_id)},
        }
        stream_token = self._stream_handler.set(stream_handler)
        try:
            if self.model_roles is None:
                final = await self.graph.ainvoke(initial, config=invoke_config)
            else:
                with self.model_roles.bind_trace_id(request.trace_id):
                    final = await self.graph.ainvoke(initial, config=invoke_config)
        finally:
            self._stream_handler.reset(stream_token)
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
            form_draft=final.get("form_draft"),
            form_missing_fields=final.get("form_missing_fields", []),
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
                "ui_context_used": state.get("ui_context") is not None,
                "context_requirement_id": state.get("purchase_request_id"),
                "context_is_authoritative": False,
            },
        )
        return {"trace_events": [*state["trace_events"], trace.model_dump(mode="json")]}

    async def _route_node(self, state: GraphState) -> dict[str, Any]:
        await self._emit_stream("thinking", {"message": "正在理解你的问题"})
        started = time.perf_counter()
        model_error: StructuredModelRunError | None = None
        model_router_used = self.model_roles is not None and self.router.should_use_model(
            state["message"]
        )
        if model_router_used:
            try:
                assert self.model_roles is not None
                model_route = await self.model_roles.route(state["message"])
                route = RouteType(model_route.route.value)
            except StructuredModelRunError as exc:
                model_error = exc
                route = self.router.classify(state["message"])
        else:
            route = self.router.classify(state["message"])
        if state.get("form_draft") and state.get("form_missing_fields"):
            route = RouteType.FORM_PREFILL
        requirement_id = None
        if route in {
            RouteType.REALTIME_BUSINESS,
            RouteType.HYBRID,
            RouteType.RISK_INVESTIGATION,
        }:
            requirement_id = self.router.extract_requirement_id(state["message"])
        model_metadata = (
            self.model_roles.trace_metadata(ModelPurpose.ROUTER)
            if model_router_used and self.model_roles is not None and model_error is None
            else self._model_error_metadata(model_error)
        )
        trace = TraceEvent(
            event_type=TraceEventType.ROUTE,
            name="model_router" if model_router_used else "first_version_router",
            status="FALLBACK" if model_error else "SUCCESS",
            duration_ms=self._elapsed_ms(started),
            arguments={"message_length": len(state["message"])},
            result={
                "route": route.value,
                "requirement_id": requirement_id,
                "model_used": model_router_used and model_error is None,
                "planner_required": route is RouteType.COMPLEX_QUERY,
                **model_metadata,
            },
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
        await self._emit_stream("retrieving_knowledge", {"message": "正在检索采购制度与业务规则"})
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
            retrieval_filters = RetrievalFilters(allowed_roles=roles)
            if getattr(self.knowledge_retriever, "supports_rewrite_context", False):
                result = await self.knowledge_retriever.retrieve(
                    state["message"],
                    filters=retrieval_filters,
                    trace_id=state["trace_id"],
                    rewrite_context=self._rewrite_context(state),  # type: ignore[call-arg]
                )
            else:
                result = await self.knowledge_retriever.retrieve(
                    state["message"],
                    filters=retrieval_filters,
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
                "rewrite_skipped": result.trace.rewrite_skipped,
                "rewrite_cache_hit": result.trace.rewrite_cache_hit,
                "embedding_cache_hit": result.trace.embedding_cache_hit,
                "retrieval_cache_hit": result.trace.retrieval_cache_hit,
                "rag_timings": result.trace.timings.model_dump(mode="json"),
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

    @staticmethod
    def _rewrite_context(state: GraphState) -> str:
        value = {
            "purchase_request_id": state.get("purchase_request_id"),
            "analysis_query_context": state.get("analysis_query_context"),
            "restored_from_snapshot": state.get("restored_from_snapshot", False),
        }
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    async def _form_prefill_node(self, state: GraphState) -> dict[str, Any]:
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        draft = dict(state.get("form_draft") or {})
        draft.update(self._extract_form_fields(state["message"]))
        current_user = state["current_user"]
        buildings = current_user.get("buildings", [])
        if "building_id" not in draft and isinstance(buildings, list) and len(buildings) == 1:
            building = buildings[0]
            if isinstance(building, dict) and isinstance(building.get("building_id"), int):
                draft["building_id"] = building["building_id"]
                draft["building_name"] = building.get("building_name")
        required = (
            "building_id",
            "device_profession",
            "device_name",
            "quantity",
            "unit",
            "application_reason",
        )
        missing = [field for field in required if draft.get(field) in (None, "")]
        pending = (
            PendingAction(action_type="CREATE_PURCHASE_DRAFT", draft=draft) if not missing else None
        )
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="form_prefill",
            status="DRAFTED",
            result={
                "action_type": pending.action_type if pending else None,
                "missing_fields": missing,
                "executed": False,
            },
        )
        return {
            "step_count": state["step_count"] + 1,
            "pending_action": pending.model_dump(mode="json") if pending else None,
            "form_draft": draft,
            "form_missing_fields": missing,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    @staticmethod
    def _extract_form_fields(message: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        normalized = re.sub(r"\s+", "", message)
        device_map = {
            "服务器": "算力服务器",
            "交换机": "IDC网络",
            "路由器": "IDC网络",
            "防火墙": "IDC网络",
            "UPS": "电气",
        }
        for device_name, profession in device_map.items():
            if device_name.lower() in normalized.lower():
                fields["device_name"] = device_name
                fields["device_profession"] = profession
                break
        brand_match = re.search(r"(浪潮|华为|联想|戴尔|惠普|新华三|H3C)", normalized, re.IGNORECASE)
        if brand_match:
            fields["brand"] = brand_match.group(1)
        quantity_match = re.search(r"(\d+(?:\.\d+)?)\s*(台|套|个|批|件)", message)
        if quantity_match:
            fields["quantity"] = float(quantity_match.group(1))
            fields["unit"] = quantity_match.group(2)
        reason_match = re.search(r"(?:原因|用途|用于|因为)[：:，,]?(.{2,200})", message)
        if reason_match:
            fields["application_reason"] = (
                reason_match.group(1).lstrip("是为：:，, ").strip("。；; ")
            )
        return fields

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
            RouteType.FORM_PREFILL: bool(state.get("form_draft")),
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
        await self._emit_stream("analyzing", {"message": "正在核对回答依据与业务边界"})
        started = time.perf_counter()
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
        route = RouteType(state["route"])
        review_needs_model = route in {
            RouteType.HYBRID,
            RouteType.RISK_INVESTIGATION,
        } or (route is RouteType.COMPLEX_QUERY and self._should_use_model_planner(state["message"]))
        model_review_used = (
            self.model_roles is not None
            and state.get("compose_output") is not None
            and review_needs_model
        )
        if model_review_used:
            try:
                assert self.model_roles is not None
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
        model_metadata = (
            self.model_roles.trace_metadata(ModelPurpose.REVIEW)
            if model_review_used and self.model_roles is not None and model_error is None
            else self._model_error_metadata(model_error)
        )
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="review",
            status="FALLBACK" if model_error else "SUCCESS" if review.passed else "BLOCKED",
            duration_ms=self._elapsed_ms(started),
            result={
                "passed": review.passed,
                "issue_codes": [item.code.value for item in review.issues],
                "model_used": model_review_used and model_error is None,
                **model_metadata,
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
        non_confirmation_blockers = [
            item
            for item in review.issues
            if item.severity is ReviewSeverity.BLOCKING
            and item.code is not ReviewIssueCode.HUMAN_CONFIRMATION_REQUIRED
        ]
        if non_confirmation_blockers and model_review_used and model_error is None:
            updates["reply"] = review.revised_answer or (
                "当前结论未通过证据与权限审查，暂不向你提供可能误导的分析结果。"
                "请补充问题范围或稍后重试。"
            )
            trace.result["review_output_enforced"] = True
            trace.result["revised_answer_used"] = review.revised_answer is not None
            updates["trace_events"][-1] = trace.model_dump(mode="json")
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
        await self._emit_stream("querying_business_data", {"message": "正在核查采购风险"})
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        requirement_id = state.get("purchase_request_id")
        if requirement_id is None:
            error = GraphError(
                code="PURCHASE_REQUEST_ID_REQUIRED",
                message="请提供采购单号，或用设备、时间和状态描述需要调查的申请",
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
                roles = [
                    item["role_code"]
                    for item in state["current_user"].get("roles", [])
                    if isinstance(item, dict) and isinstance(item.get("role_code"), str)
                ]
                output = await self.risk_investigation.run(
                    requirement_id,
                    protected_client,
                    knowledge_retriever=self.knowledge_retriever,
                    allowed_roles=roles,
                    question=state["message"],
                    trace_id=state["trace_id"],
                )
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
        await self._emit_stream("analyzing", {"message": "正在分析采购数据"})
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
        analysis_message = state["message"]
        if state.get("ui_context") and state.get("purchase_request_id"):
            analysis_message = (
                f"{analysis_message}\n当前页面采购申请 {state['purchase_request_id']}。"
                "该编号仅用于定位，所有业务事实必须通过工具重新查询。"
            )
        previous_query = state.get("analysis_query_context")
        prepared_plan = None
        planner_trace: TraceEvent | None = None
        planner_error: StructuredModelRunError | None = None
        model_planner_requested = self.model_roles is not None and self._should_use_model_planner(
            analysis_message
        )
        if model_planner_requested:
            planner_started = time.perf_counter()
            try:
                prepared_plan = await self.model_roles.plan(
                    analysis_message,
                    previous_query if isinstance(previous_query, dict) else None,
                )
            except StructuredModelRunError as exc:
                planner_error = exc
            planner_metadata = (
                self.model_roles.trace_metadata(ModelPurpose.ANALYSIS_PLAN)
                if planner_error is None
                else self._model_error_metadata(planner_error)
            )
            planner_trace = TraceEvent(
                event_type=TraceEventType.GRAPH,
                name="model_planner",
                status="FALLBACK" if planner_error else "SUCCESS",
                duration_ms=self._elapsed_ms(planner_started),
                result={
                    "planner_called": True,
                    "plan": (
                        prepared_plan.model_dump(mode="json") if prepared_plan is not None else None
                    ),
                    "model_used": planner_error is None,
                    **planner_metadata,
                },
                error_code=planner_error.code if planner_error else None,
            )
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
                    analysis_message,
                    protected_client,
                    previous_query=(
                        AnalyticsQueryInput.model_validate(previous_query)
                        if previous_query
                        else None
                    ),
                    prepared_plan=prepared_plan,
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
                "planner_called": model_planner_requested,
                "planner_model_used": prepared_plan is not None,
                "planner_mode": "model" if model_planner_requested else "deterministic",
                "plan": output.plan.model_dump(mode="json"),
            },
        )
        trace_events = [*state["trace_events"]]
        if planner_trace is not None:
            trace_events.append(planner_trace.model_dump(mode="json"))
        trace_events.append(trace.model_dump(mode="json"))
        graph_errors = [*state["errors"]]
        if planner_error is not None:
            graph_errors.append(
                GraphError(
                    code=planner_error.code,
                    message=(f"模型 Planner 失败，已使用确定性 Planner：{planner_error.message}"),
                    source="model_planner",
                ).model_dump(mode="json")
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
                *graph_errors,
                *(item.model_dump(mode="json") for item in errors),
            ],
            "trace_events": trace_events,
            "analysis": output.model_dump(mode="json"),
            "analysis_query_context": (
                output.effective_query.model_dump(mode="json")
                if output.effective_query
                else state.get("analysis_query_context")
            ),
        }

    @staticmethod
    def _should_use_model_planner(message: str) -> bool:
        """Use the model only when a request needs genuine multi-step planning.

        Context shortcuts that map to one controlled read-only tool keep the
        deterministic planner. This avoids spending a full model round trip
        before users see the first business result while preserving the model
        planner for aggregations, comparisons, and open-ended analysis.
        """
        normalized = "".join(message.lower().split())
        single_tool_intents = (
            "推荐供应商",
            "相似案例",
            "供应商风险",
            "历史采购情况",
        )
        if any(intent in normalized for intent in single_tool_intents):
            return False
        return not DeterministicAnalysisPlanner.supports_single_tool_query(message)

    async def _realtime_query_node(self, state: GraphState) -> dict[str, Any]:
        await self._emit_stream("querying_business_data", {"message": "正在查询采购业务记录"})
        if state["step_count"] >= self.settings.max_execution_steps:
            return self._boundary_failure(state, "GRAPH_STEP_LIMIT", "已达到最大执行步骤")
        requirement_id = state.get("purchase_request_id")
        if requirement_id is None:
            resolution_arguments = self._requirement_search_arguments(state["message"])
            if not resolution_arguments:
                error = GraphError(
                    code="PURCHASE_REQUEST_ID_REQUIRED",
                    message="请提供采购单号，或用设备、时间和状态描述这张申请",
                    source="mcp://search_purchase_records",
                )
                trace = TraceEvent(
                    event_type=TraceEventType.ERROR,
                    name="resolve_purchase_reference",
                    status="SKIPPED",
                    error_code=error.code,
                )
                return {
                    "step_count": state["step_count"] + 1,
                    "errors": [*state["errors"], error.model_dump(mode="json")],
                    "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
                }
            identity = BackendIdentity.model_validate(state["identity"])
            resolution_started = time.perf_counter()
            try:
                async with self.mcp_client_factory(
                    self.settings, identity, state["trace_id"]
                ) as client:
                    protected_client = CircuitProtectedMCPClient(client, self.mcp_circuit_breaker)
                    resolved = await protected_client.call_tool(
                        "search_purchase_records", resolution_arguments
                    )
            except MCPClientError as exc:
                return self._tool_transport_failure(
                    state, exc, resolution_arguments, resolution_started
                )
            resolution_execution = ToolExecution(
                name="search_purchase_records",
                arguments=resolution_arguments,
                success=resolved.success,
                code=resolved.code,
                source=resolved.source,
                trace_id=resolved.trace_id,
                duration_ms=self._elapsed_ms(resolution_started),
                data=resolved.data,
            )
            items = (
                resolved.data.get("items", [])
                if resolved.success and isinstance(resolved.data, dict)
                else []
            )
            resolution_trace = TraceEvent(
                event_type=TraceEventType.TOOL,
                name="search_purchase_records",
                status="SUCCESS" if resolved.success else "FAILED",
                duration_ms=resolution_execution.duration_ms,
                arguments=resolution_arguments,
                result={"match_count": len(items)},
                error_code=None if resolved.success else resolved.code,
            )
            resolution_evidence = Evidence(
                evidence_type="MCP_TOOL_RESULT",
                source=resolved.source,
                reference_id="purchase_candidates",
                data=resolved.data,
            )
            state = {
                **state,
                "tool_call_count": state["tool_call_count"] + 1,
                "tool_results": [
                    *state["tool_results"],
                    resolution_execution.model_dump(mode="json"),
                ],
                "trace_events": [*state["trace_events"], resolution_trace.model_dump(mode="json")],
                "evidence": [*state["evidence"], resolution_evidence.model_dump(mode="json")],
            }
            if len(items) != 1:
                return {
                    "step_count": state["step_count"] + 1,
                    "tool_call_count": state["tool_call_count"],
                    "tool_results": state["tool_results"],
                    "trace_events": state["trace_events"],
                    "evidence": state["evidence"],
                }
            requirement_id = int(items[0]["requirement_id"])
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

    @staticmethod
    def _requirement_search_arguments(message: str) -> dict[str, Any]:
        arguments: dict[str, Any] = {"page": 1, "page_size": 10}
        requirement_no = re.search(
            r"(?<![A-Z0-9])((?:TEST-)?PR-[A-Z0-9-]{2,}|TEST-PR-[A-Z0-9-]+)",
            message.upper(),
        )
        if requirement_no:
            arguments["requirement_no"] = requirement_no.group(1)
        for device in ("服务器", "交换机", "路由器", "存储", "防火墙", "机柜", "UPS"):
            if device.lower() in message.lower():
                arguments["device_name"] = device
                break
        status_map = {
            "草稿": "DRAFT",
            "待审批": "PENDING_REVIEW",
            "已驳回": "REJECTED",
            "待采购": "PENDING_PURCHASE",
            "采购中": "PURCHASING",
            "待入库": "PENDING_WAREHOUSE",
            "已完成": "COMPLETED",
        }
        for label, status in status_map.items():
            if label in message:
                arguments["status"] = status
                break
        if "昨天" in message:
            target = date.today() - timedelta(days=1)
            arguments["created_from"] = target.isoformat()
            arguments["created_to"] = target.isoformat()
        return arguments if len(arguments) > 2 else {}

    async def _answer_node(self, state: GraphState) -> dict[str, Any]:
        await self._emit_stream("analyzing", {"message": "正在整理查询结果"})
        started = time.perf_counter()
        deterministic_reply = self._compose_answer(state)
        reply = deterministic_reply
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
        deterministic_completion_applied = False
        model_error: StructuredModelRunError | None = None
        if self.model_roles is not None and state["evidence"]:
            try:
                if self._stream_handler.get() is None:
                    compose_output = await self.model_roles.compose(
                        state["message"],
                        state["evidence"],
                        allowed_citation_ids={item.citation_id for item in citations},
                    )
                else:
                    compose_output = await self.model_roles.compose_stream(
                        state["message"],
                        state["evidence"],
                        allowed_citation_ids={item.citation_id for item in citations},
                        answer_delta_handler=self._emit_answer_delta,
                    )
                reply = compose_output.answer
                if self._answer_looks_incomplete(reply):
                    reply = f"{reply}\n\n{deterministic_reply}"
                    compose_output = compose_output.model_copy(update={"answer": reply})
                    deterministic_completion_applied = True
            except StructuredModelRunError as exc:
                model_error = exc
        model_metadata = (
            self.model_roles.trace_metadata(ModelPurpose.COMPOSE)
            if self.model_roles is not None and model_error is None and state["evidence"]
            else self._model_error_metadata(model_error)
        )
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="compose_answer",
            status="FALLBACK" if model_error else "SUCCESS",
            duration_ms=self._elapsed_ms(started),
            result={
                "reply_length": len(reply),
                "model_used": (
                    self.model_roles is not None and bool(state["evidence"]) and model_error is None
                ),
                "citation_ids": [item.citation_id for item in compose_output.citations],
                "deterministic_completion_applied": deterministic_completion_applied,
                **model_metadata,
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
        if self.model_roles is None or not state["evidence"] or model_error is not None:
            await self._emit_answer_delta(reply)
        return updates

    async def _emit_answer_delta(self, value: str) -> None:
        await self._emit_stream("answer_delta", {"delta": value})

    @staticmethod
    def _answer_looks_incomplete(value: str) -> bool:
        normalized = value.rstrip()
        return not normalized or normalized.endswith(("：", ":"))

    async def _emit_stream(self, event: str, data: dict[str, Any]) -> None:
        handler = self._stream_handler.get()
        if handler is not None:
            await handler(event, data)

    @staticmethod
    def _model_error_metadata(error: StructuredModelRunError | None) -> dict[str, Any]:
        if error is None:
            return {}
        return {
            "primary_model": error.primary_model,
            "actual_model": error.actual_model,
            "fallback_used": error.fallback_used,
            "fallback_reason": error.fallback_reason,
        }

    def _compose_answer(self, state: GraphState) -> str:
        route = RouteType(state["route"])
        if route is RouteType.RISK_INVESTIGATION and state.get("risk_investigation"):
            return RiskInvestigationOutput.model_validate(state["risk_investigation"]).answer
        if route is RouteType.COMPLEX_QUERY and state.get("analysis"):
            return AnalysisOutput.model_validate(state["analysis"]).answer
        if route is RouteType.FORM_PREFILL:
            missing = state.get("form_missing_fields", [])
            if missing:
                labels = {
                    "building_id": "所属楼宇",
                    "device_profession": "设备类型",
                    "device_name": "设备名称",
                    "quantity": "数量",
                    "unit": "单位",
                    "application_reason": "采购原因",
                }
                names = "、".join(labels.get(item, item) for item in missing)
                return (
                    "我已记录你提供的采购信息，并建立了未提交的申请草稿。\n\n"
                    f"**还需要补充：{names}。**\n\n"
                    "请直接告诉我缺少的信息；已记录的内容无需重复填写。"
                )
            return (
                "采购申请草稿已经整理完成。请先核对下方字段；如需修改，直接告诉我。\n\n"
                "**确认无误后再点击“创建草稿”。这一步只会在业务系统中创建草稿，不会提交审批。**"
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
        return "请提供采购单号，或描述设备、时间和当前状态，我会帮你定位。"

    @staticmethod
    def _knowledge_answer(state: GraphState) -> str | None:
        if not state.get("knowledge"):
            return None
        result = RetrievalResult.model_validate(state["knowledge"])
        if not result.answerable:
            return None
        statements = [item.context_content.strip() for item in result.evidences]
        return "\n\n".join(item for item in statements if item)

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
        if execution.name == "search_purchase_records" and isinstance(execution.data, dict):
            total = int(execution.data.get("total", 0))
            if total == 0:
                return "没有找到符合描述的采购申请。请补充设备、时间或当前状态后再试。"
            return f"找到 {total} 条可能匹配的采购申请，请从下方结果中选择要查看的一条。"
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
