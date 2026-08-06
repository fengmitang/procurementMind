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
    RouteType,
    ToolExecution,
    TraceEvent,
    TraceEventType,
)
from agent_app.investigation.schemas import EvidenceStatus, RiskInvestigationOutput
from agent_app.investigation.service import RiskInvestigationService
from agent_app.mcp.client import MCPClientError, ProcurementMCPClient
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.models.runner import StructuredModelRunError
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
        self.mcp_circuit_breaker = AsyncCircuitBreaker(
            failure_threshold=settings.mcp_circuit_failure_threshold,
            recovery_timeout_seconds=settings.mcp_circuit_recovery_timeout_seconds,
        )
        self.graph = self._build_graph()

    async def run(self, request: GraphRunRequest) -> GraphRunResult:
        started = time.perf_counter()
        restored_analysis_query = GraphMemoryMapper.analysis_query(request)
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
        }
        final = await self.graph.ainvoke(
            initial,
            config={"recursion_limit": max(10, self.settings.max_execution_steps + 5)},
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
        )

    def _build_graph(self):
        builder = StateGraph(GraphState)
        builder.add_node("route", self._route_node)
        builder.add_node("realtime_query", self._realtime_query_node)
        builder.add_node("analysis", self._analysis_node)
        builder.add_node("risk_investigation", self._risk_investigation_node)
        builder.add_node("answer", self._answer_node)
        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            self._after_route,
            {
                "realtime_query": "realtime_query",
                "analysis": "analysis",
                "risk_investigation": "risk_investigation",
                "answer": "answer",
            },
        )
        builder.add_edge("realtime_query", "answer")
        builder.add_edge("analysis", "answer")
        builder.add_edge("risk_investigation", "answer")
        builder.add_edge("answer", END)
        return builder.compile()

    async def _route_node(self, state: GraphState) -> dict[str, Any]:
        started = time.perf_counter()
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
            name="first_version_router",
            status="SUCCESS",
            duration_ms=self._elapsed_ms(started),
            arguments={"message_length": len(state["message"])},
            result={"route": route.value, "requirement_id": requirement_id},
        )
        return {
            "route": route.value,
            "purchase_request_id": requirement_id or state.get("purchase_request_id"),
            "step_count": state["step_count"] + 1,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    @staticmethod
    def _after_route(state: GraphState) -> str:
        if state["route"] in {
            RouteType.REALTIME_BUSINESS.value,
            RouteType.HYBRID.value,
        }:
            return "realtime_query"
        if state["route"] == RouteType.COMPLEX_QUERY.value:
            return "analysis"
        if state["route"] == RouteType.RISK_INVESTIGATION.value:
            return "risk_investigation"
        return "answer"

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
        trace = TraceEvent(
            event_type=TraceEventType.GRAPH,
            name="compose_answer",
            status="SUCCESS",
            duration_ms=self._elapsed_ms(started),
            result={"reply_length": len(reply)},
        )
        step_count = state["step_count"]
        if step_count < self.settings.max_execution_steps:
            step_count += 1
        return {
            "reply": reply,
            "step_count": step_count,
            "trace_events": [*state["trace_events"], trace.model_dump(mode="json")],
        }

    def _compose_answer(self, state: GraphState) -> str:
        route = RouteType(state["route"])
        if route is RouteType.RISK_INVESTIGATION and state.get("risk_investigation"):
            return RiskInvestigationOutput.model_validate(state["risk_investigation"]).answer
        if route is RouteType.COMPLEX_QUERY and state.get("analysis"):
            return AnalysisOutput.model_validate(state["analysis"]).answer
        if state["errors"]:
            error = GraphError.model_validate(state["errors"][-1])
            if route is RouteType.COMPLEX_QUERY:
                return f"暂时无法完成采购分析：{error.message}。"
            if route is RouteType.RISK_INVESTIGATION:
                return f"暂时无法完成风险调查：{error.message}。本次不形成风险结论。"
            if route is RouteType.HYBRID:
                return (
                    f"暂时无法确认实时采购数据：{error.message}。"
                    "制度知识未接入，本次不生成混合结论。"
                )
            return f"暂时无法确认采购申请的实时状态：{error.message}。"
        if route in {RouteType.REALTIME_BUSINESS, RouteType.HYBRID}:
            if not state["tool_results"]:
                return "请提供采购申请 ID，例如：查询采购申请 91007 的当前状态。"
            execution = ToolExecution.model_validate(state["tool_results"][-1])
            if not execution.success or not isinstance(execution.data, dict):
                return "采购后端未返回可确认的申请数据，本次不会猜测状态。"
            data = execution.data
            handler = data.get("current_handler")
            handler_name = handler.get("name") if isinstance(handler, dict) else None
            next_handler = handler_name or "暂无（流程可能已结束或尚未分配）"
            reply = (
                f"采购申请 {data.get('requirement_no', state.get('purchase_request_id'))} "
                f"当前状态为 {data.get('status', '未知')}，下一处理人为：{next_handler}。"
            )
            if route is RouteType.HYBRID:
                reply += " 制度解释知识库尚未接入，因此这里只确认实时业务数据。"
            return reply
        if route is RouteType.COMPLEX_QUERY:
            return "分析工具未返回可确认的数据，本次不会猜测结果。"
        pending = {
            RouteType.KNOWLEDGE: "知识库将在 DEV-04 接入，当前不会编造制度答案。",
            RouteType.RISK_INVESTIGATION: "请提供需要调查的采购申请 ID。",
        }
        return pending[route]

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
