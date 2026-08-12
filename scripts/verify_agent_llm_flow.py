"""Verify the configured live LLM through the formal Agent runtime and LangGraph."""

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import AgentSettings  # noqa: E402
from agent_app.graph.schemas import GraphRunRequest, GraphRunResult  # noqa: E402
from agent_app.graph.service import ProcurementGraphService  # noqa: E402
from agent_app.main import create_agent_app  # noqa: E402
from agent_app.mcp.schemas import MCPToolResponse  # noqa: E402
from agent_app.rag.schemas import (  # noqa: E402
    ChildChunkPayload,
    KnowledgeCitation,
    RetrievalFilters,
    RetrievalResult,
    RetrievalTrace,
    RetrievedEvidence,
)
from agent_app.schemas.backend import (  # noqa: E402
    BackendIdentity,
    BackendReadinessData,
    CurrentUserData,
    UserRoleData,
)


class VerificationBackend:
    async def readiness(self, _trace_id: str) -> BackendReadinessData:
        return BackendReadinessData(status="ready", mysql="ok", redis="ok")

    async def aclose(self) -> None:
        return None


class VerificationRetriever:
    async def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters,
        trace_id: str | None = None,
    ) -> RetrievalResult:
        payload = ChildChunkPayload(
            child_id="verify-child-1",
            parent_id="verify-parent-1",
            document_id="verify-document-1",
            title="采购申请流程规范",
            section_path=["采购申请", "驳回处理"],
            topic="采购申请驳回后的处理",
            chunk_type="step",
            version="1.0",
            status="ACTIVE",
            content="采购申请被驳回后，需求人应根据驳回意见修改申请，再重新提交审批。",
            source_path="knowledge/source/采购申请流程规范.md",
            source_start_line=20,
            source_end_line=22,
            allowed_roles=filters.allowed_roles,
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
            fusion_score=0.9,
            rerank_score=0.95,
            context_content=payload.content,
            citation=citation,
        )
        resolved_trace_id = trace_id or "verify-rag"
        trace = RetrievalTrace(
            trace_id=resolved_trace_id,
            original_query=query,
            rewritten_query=query,
            rewrite_applied=False,
            filters=filters,
            dense_candidates=[],
            sparse_candidates=[],
            rrf_candidates=[],
            rerank_candidates=[],
            final_evidence_ids=[citation.citation_id],
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


class VerificationMCPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResponse:
        values = arguments or {}
        self.calls.append((name, values))
        if name == "get_purchase_request":
            return MCPToolResponse.ok(
                {
                    "requirement_id": values["requirement_id"],
                    "requirement_no": "VERIFY-91007",
                    "status": "APPROVING",
                    "current_handler": "采购经理",
                },
                source="/api/v1/requirements/91007",
                trace_id="verify-tool",
            )
        if name == "query_purchase_analytics":
            return MCPToolResponse.ok(
                {
                    "items": [],
                    "summary": {"count": 9, "total_amount": "34350.00"},
                    "groups": [
                        {
                            "key": "A",
                            "label": "A楼",
                            "metrics": {"count": 5, "total_amount": "20000.00"},
                        }
                    ],
                    "page": 1,
                    "page_size": 20,
                    "total": 0,
                    "effective_query": values.get("query", {}),
                    "warnings": [],
                },
                source="/api/v1/analytics/purchase-query",
                trace_id="verify-analysis",
            )
        return MCPToolResponse.failure(
            "VERIFY_TOOL_NOT_SUPPORTED",
            f"verification tool not supported: {name}",
            source=f"mcp://{name}",
            trace_id="verify-tool",
        )


MCP_CLIENT = VerificationMCPClient()


@asynccontextmanager
async def verification_mcp_factory(*_args):
    yield MCP_CLIENT


def graph_request(message: str, trace_id: str) -> GraphRunRequest:
    return GraphRunRequest(
        task_id=uuid4(),
        trace_id=trace_id,
        conversation_id=99100 + len(MCP_CLIENT.calls),
        identity=BackendIdentity(
            platform_type="TEST_PLATFORM",
            platform_user_id="live-model-verifier",
        ),
        current_user=CurrentUserData(
            employee_id=1,
            employee_no="VERIFY-E001",
            name="验证用户",
            mobile=None,
            status="ACTIVE",
            platform_type="TEST_PLATFORM",
            platform_user_id="live-model-verifier",
            roles=[UserRoleData(role_id=1, role_code="APPLICANT", role_name="需求人")],
            buildings=[],
        ),
        message=message,
    )


def trace_summary(result: GraphRunResult) -> list[dict[str, Any]]:
    names = {"model_router", "model_planner", "compose_answer", "review"}
    return [
        {
            "name": event.name,
            "status": event.status,
            "model_used": event.result.get("model_used"),
            "primary_model": event.result.get("primary_model"),
            "actual_model": event.result.get("actual_model"),
            "fallback_used": event.result.get("fallback_used"),
            "fallback_reason": event.result.get("fallback_reason"),
            "planner_called": event.result.get("planner_called"),
        }
        for event in result.trace_events
        if event.name in names and isinstance(event.result, dict)
    ]


async def run_case(
    name: str,
    graph: ProcurementGraphService,
    message: str,
    *,
    expected_route: str,
    planner_expected: bool,
    tool_expected: bool,
) -> tuple[bool, dict[str, Any]]:
    before_calls = len(MCP_CLIENT.calls)
    result = await graph.run(graph_request(message, f"live-{name}"))
    traces = trace_summary(result)
    planner_called = any(item["name"] == "model_planner" for item in traces)
    planner_model_used = any(
        item["name"] == "model_planner" and item["model_used"] is True for item in traces
    )
    model_used = any(item["model_used"] is True for item in traces)
    tool_called = len(MCP_CLIENT.calls) > before_calls
    passed = (
        result.route.value == expected_route
        and planner_called is planner_expected
        and (not planner_expected or planner_model_used)
        and tool_called is tool_expected
        and model_used
    )
    return passed, {
        "route": result.route.value,
        "planner_called": planner_called,
        "tool_called": tool_called,
        "reply": result.reply[:160],
        "errors": [{"code": item.code, "message": item.message[:500]} for item in result.errors],
        "trace": traces,
    }


async def verify(only: str = "all") -> int:
    settings = AgentSettings()
    if only == "planner_role":
        settings = settings.model_copy(update={"model_structured_output_retries": 0})
    if not settings.model_configured or not settings.fallback_model:
        print("[FAIL] 正式 Runtime 配置不完整（需要 Primary 和 Fallback）")
        return 1

    graph = ProcurementGraphService(
        settings,
        mcp_client_factory=verification_mcp_factory,
        knowledge_retriever=VerificationRetriever(),
    )
    application = create_agent_app(
        settings,
        procurement_backend_client=VerificationBackend(),
        graph_service=graph,
    )
    runtime = application.state.model_runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://agent.test",
    ) as client:
        ready_response = await client.get("/ready")
    readiness = {
        "runtime_status": runtime.status.value.lower(),
        "provider": runtime.configuration.provider,
        "primary_model": runtime.configuration.model,
        "fallback_model": runtime.configuration.fallback_model,
        "graph_roles_injected": graph.model_roles is not None,
        "ready_api": ready_response.json(),
    }
    print(f"[PASS] Bootstrap/Readiness | {json.dumps(readiness, ensure_ascii=False)}")

    if only == "planner_role":
        assert graph.model_roles is not None
        try:
            plan = await graph.model_roles.plan(
                "请执行复杂聚合分析：统计各楼宇采购数量和总金额。",
                None,
            )
            print(f"[PASS] planner_role | {plan.model_dump_json()}")
            return 0
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            message = getattr(exc, "message", str(exc))
            print(f"[FAIL] planner_role | {code}: {message[:800]}")
            return 1
        finally:
            await runtime.aclose()

    cases = [
        (
            "knowledge",
            "采购申请被驳回后应该如何处理？这是制度知识问题。",
            "KNOWLEDGE",
            False,
            False,
        ),
        (
            "router",
            "采购制度中的供应商准入条件是什么？这是知识库规则问题。",
            "KNOWLEDGE",
            False,
            False,
        ),
        (
            "tool_compose",
            "查询采购申请 91007 的当前状态和处理人。",
            "REALTIME_BUSINESS",
            False,
            True,
        ),
        (
            "planner",
            "请执行复杂聚合分析：统计各楼宇采购数量和总金额，按楼宇分组、比较并给出分析。",
            "COMPLEX_QUERY",
            True,
            True,
        ),
    ]
    all_passed = True
    selected_cases = cases if only == "all" else [case for case in cases if case[0] == only]
    for name, message, route, planner_expected, tool_expected in selected_cases:
        try:
            passed, detail = await run_case(
                name,
                graph,
                message,
                expected_route=route,
                planner_expected=planner_expected,
                tool_expected=tool_expected,
            )
        except Exception as exc:
            passed = False
            detail = {"error": f"{type(exc).__name__}: {exc}"[:800]}
        all_passed = all_passed and passed
        print(
            f"[{'PASS' if passed else 'FAIL'}] {name} | "
            f"{json.dumps(detail, ensure_ascii=False, default=str)}"
        )

    if only not in {"all", "fallback"}:
        await runtime.aclose()
        return 0 if all_passed else 1

    invalid_primary = f"{settings.primary_model}-intentional-invalid"
    fallback_settings = settings.model_copy(update={"primary_model": invalid_primary})
    fallback_graph = ProcurementGraphService(
        fallback_settings,
        mcp_client_factory=verification_mcp_factory,
        knowledge_retriever=VerificationRetriever(),
    )
    fallback_app = create_agent_app(
        fallback_settings,
        procurement_backend_client=VerificationBackend(),
        graph_service=fallback_graph,
    )
    try:
        fallback_result = await fallback_graph.run(
            graph_request(
                "采购申请被驳回后应该如何处理？这是制度知识问题。",
                "live-runtime-fallback",
            )
        )
        fallback_trace = trace_summary(fallback_result)
        fallback_used = any(
            item["fallback_used"] is True
            and item["actual_model"] == settings.fallback_model
            and item["model_used"] is True
            for item in fallback_trace
        )
        all_passed = all_passed and fallback_used
        print(
            f"[{'PASS' if fallback_used else 'FAIL'}] runtime_fallback | "
            f"{json.dumps(fallback_trace, ensure_ascii=False, default=str)}"
        )
    except Exception as exc:
        all_passed = False
        print(f"[FAIL] runtime_fallback | {type(exc).__name__}: {str(exc)[:800]}")
    finally:
        await fallback_app.state.model_runtime.aclose()
        await runtime.aclose()

    return 0 if all_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        choices=[
            "all",
            "knowledge",
            "router",
            "tool_compose",
            "planner",
            "planner_role",
            "fallback",
        ],
        default="all",
    )
    raise SystemExit(asyncio.run(verify(parser.parse_args().only)))
