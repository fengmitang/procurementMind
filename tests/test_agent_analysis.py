import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_app.analysis.executor import AnalysisExecutor
from agent_app.analysis.planner import DeterministicAnalysisPlanner
from agent_app.analysis.schemas import AnalysisPlan, AnalysisPlanStep, AnalysisToolName
from agent_app.analysis.service import AnalysisAgentService
from agent_app.core.config import AgentSettings
from agent_app.device_terms.schemas import (
    DeviceTermCandidate,
    DeviceTermLookupResult,
    DeviceTermLookupStatus,
)
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.schemas import GraphRunRequest, RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.models.fake import ScriptedModelAdapter
from agent_app.models.protocols import ModelPurpose, StructuredModelResponse
from agent_app.models.roles import StructuredModelRoles
from agent_app.models.runner import StructuredModelRunError, StructuredModelRunner
from agent_app.schemas.analytics import (
    AnalyticsAggregation,
    AnalyticsGroupBy,
    AnalyticsQueryInput,
)
from agent_app.schemas.backend import (
    BackendIdentity,
    ConversationStateData,
    CurrentUserData,
)
from app.schemas.procurement import DEVICE_PROFESSIONS

EVALUATION_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "analysis_evaluation_v0.1.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("device_profession", DEVICE_PROFESSIONS)
def test_agent_analytics_schema_accepts_formal_device_professions(
    device_profession: str,
) -> None:
    query = AnalyticsQueryInput(device_professions=[device_profession])

    assert query.device_professions == [device_profession]


def test_agent_analytics_schema_rejects_unknown_device_profession() -> None:
    with pytest.raises(ValidationError):
        AnalyticsQueryInput(device_professions=["未定义设备类型"])


@pytest.mark.asyncio
@pytest.mark.parametrize("device_profession", DEVICE_PROFESSIONS)
async def test_deterministic_planner_uses_formal_device_professions(
    device_profession: str,
) -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(
        f"统计设备类型为{device_profession}的采购数量"
    )

    assert plan.query_context is not None
    assert plan.query_context.device_professions == [device_profession]
    assert plan.query_context.device_name is None


@pytest.mark.asyncio
async def test_deterministic_planner_uses_catalog_typical_terms() -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(
        "看看以前UPS功率模块的采购情况"
    )

    assert plan.query_context is not None
    assert plan.query_context.device_professions == ["UPS"]
    assert plan.query_context.device_name == "UPS功率模块"


@pytest.mark.asyncio
async def test_deterministic_planner_does_not_map_ambiguous_term_alone() -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(
        "看看以前功率模块的采购情况"
    )

    assert plan.query_context is not None
    assert plan.query_context.device_professions == []
    assert plan.query_context.device_name == "功率模块"


class FakeDeviceTermSearch:
    top_k = 5

    def __init__(self, result: DeviceTermLookupResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def lookup(self, query_term, device_profession):
        self.calls.append((query_term, device_profession))
        return self.result


@pytest.mark.asyncio
async def test_analysis_service_adds_semantic_candidates_before_backend_tool() -> None:
    lookup = DeviceTermLookupResult(
        status=DeviceTermLookupStatus.SEMANTIC,
        query_term="UPS功率模块",
        device_profession="UPS",
        semantic_used=True,
        candidates=[
            DeviceTermCandidate(
                device_name="UPS模块", device_profession="UPS", score=0.91
            ),
            DeviceTermCandidate(
                device_name="模块化UPS功率单元", device_profession="UPS", score=0.87
            ),
        ],
        top_k=5,
    )
    search = FakeDeviceTermSearch(lookup)
    client = FakeAnalysisClient()

    output = await AnalysisAgentService(device_term_search=search).run(
        "看看以前UPS功率模块的采购情况", client
    )

    query = client.calls[0][1]["query"]
    assert query["device_professions"] == ["UPS"]
    assert query["device_name"] == "UPS功率模块"
    assert query["device_names"] == ["UPS模块", "模块化UPS功率单元"]
    assert output.device_term_lookup == lookup
    assert search.calls == [("UPS功率模块", "UPS")]


@pytest.mark.asyncio
async def test_ambiguous_query_requires_profession_without_calling_backend() -> None:
    client = FakeAnalysisClient()

    output = await AnalysisAgentService().run("看看以前功率模块的采购情况", client)

    assert client.calls == []
    assert output.device_term_lookup is not None
    assert (
        output.device_term_lookup.status
        is DeviceTermLookupStatus.CLASSIFICATION_REQUIRED
    )
    assert "请补充设备类型" in output.answer


@pytest.mark.asyncio
async def test_semantic_fallback_keeps_original_backend_query() -> None:
    fallback = DeviceTermLookupResult(
        status=DeviceTermLookupStatus.FALLBACK,
        query_term="UPS功率模块",
        device_profession="UPS",
        top_k=5,
        fallback_triggered=True,
        error_code="RAG_API_TIMEOUT",
        message="已回退",
    )
    client = FakeAnalysisClient()

    output = await AnalysisAgentService(
        device_term_search=FakeDeviceTermSearch(fallback)
    ).run("看看以前UPS功率模块的采购情况", client)

    query = client.calls[0][1]["query"]
    assert query["device_name"] == "UPS功率模块"
    assert query["device_names"] == []
    assert output.device_term_lookup is not None
    assert output.device_term_lookup.fallback_triggered is True
    assert "已回退" in output.warnings


@pytest.mark.asyncio
async def test_planner_parses_my_july_requirements_as_scoped_business_query() -> None:
    plan = await DeterministicAnalysisPlanner().create_plan("我七月发起的采购申请有哪些")
    query = plan.query_context

    assert query is not None
    assert query.created_by_me is True
    assert query.created_from == date(date.today().year, 7, 1)
    assert query.created_to == date(date.today().year, 7, 31)


class FakeAnalysisClient:
    def __init__(self, responses: dict[str, list[MCPToolResponse]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []
        self.active = 0
        self.max_active = 0

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls.append((name, arguments or {}))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        queued = self.responses.get(name)
        if queued:
            return queued.pop(0)
        return analytics_response()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", EVALUATION_CASES, ids=lambda case: case["id"])
async def test_analysis_planner_evaluation_cases(case: dict) -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(case["message"])

    step = plan.steps[0]
    assert step.tool.value == case["expected_tool"]
    for key, expected in case.get("expected_arguments", {}).items():
        assert step.arguments[key] == expected
    query = plan.query_context.model_dump(mode="json") if plan.query_context else {}
    for key, expected in case.get("expected_query", {}).items():
        assert query[key] == expected


def analytics_response() -> MCPToolResponse:
    return MCPToolResponse.ok(
        {
            "items": [
                {
                    "requirement_id": 91001,
                    "requirement_no": "TEST-91001",
                    "building_name": "A 楼",
                    "device_name": "服务器",
                    "actual_total_price": "9500.00",
                }
            ],
            "summary": {"count": 9, "total_amount": "34350.00"},
            "groups": [
                {
                    "key": "1001",
                    "label": "A 楼",
                    "metrics": {"count": 5, "total_amount": "20000.00"},
                }
            ],
            "page": 1,
            "page_size": 20,
            "total": 9,
            "scanned_rows": 9,
            "effective_query": {
                "device_name": "服务器",
                "exclude_blacklisted": True,
                "exclude_delayed_suppliers": False,
                "group_by": "BUILDING",
                "aggregations": ["COUNT", "TOTAL_AMOUNT"],
                "page": 1,
                "page_size": 20,
            },
            "warnings": [],
        },
        source="/api/v1/analytics/purchase-query",
        trace_id="trace-analysis",
    )


@pytest.mark.asyncio
async def test_deterministic_planner_builds_whitelisted_query() -> None:
    planner = DeterministicAnalysisPlanner()

    plan = await planner.create_plan("统计各楼宇服务器采购数量和总金额，排除黑名单")

    assert len(plan.steps) == 1
    assert plan.steps[0].tool is AnalysisToolName.QUERY_PURCHASE_ANALYTICS
    query = plan.query_context
    assert query is not None
    assert query.device_name == "服务器"
    assert query.group_by is AnalyticsGroupBy.BUILDING
    assert query.exclude_blacklisted is True
    assert query.aggregations == [
        AnalyticsAggregation.COUNT,
        AnalyticsAggregation.TOTAL_AMOUNT,
    ]
    assert "sql" not in plan.steps[0].arguments


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "group_by", "aggregations"),
    [
        ("按状态统计采购申请数量", AnalyticsGroupBy.STATUS, [AnalyticsAggregation.COUNT]),
        ("分析今年采购申请数量的月度趋势", AnalyticsGroupBy.MONTH, [AnalyticsAggregation.COUNT]),
        ("统计已完成采购申请的总金额", None, [AnalyticsAggregation.TOTAL_AMOUNT]),
        (
            "按设备名称统计采购数量并给出排名",
            AnalyticsGroupBy.DEVICE_NAME,
            [AnalyticsAggregation.COUNT],
        ),
    ],
)
async def test_deterministic_planner_supports_acceptance_aggregations(
    message: str,
    group_by: AnalyticsGroupBy | None,
    aggregations: list[AnalyticsAggregation],
) -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(message)

    assert plan.query_context is not None
    assert plan.query_context.group_by is group_by
    assert plan.query_context.aggregations == aggregations
    if "已完成" in message:
        assert plan.query_context.statuses == ["COMPLETED"]
    assert plan.steps[0].arguments == {"query": plan.query_context.model_dump(mode="json")}


@pytest.mark.asyncio
async def test_follow_up_inherits_only_structured_query_conditions() -> None:
    planner = DeterministicAnalysisPlanner()
    first = await planner.create_plan("查询 2026-01-01 到 2026-06-30 的服务器采购，排除黑名单")

    follow_up = await planner.create_plan("再排除延期供应商", first.query_context)

    query = follow_up.query_context
    assert query is not None
    assert query.created_from == date(2026, 1, 1)
    assert query.created_to == date(2026, 6, 30)
    assert query.device_name == "服务器"
    assert query.exclude_blacklisted is True
    assert query.exclude_delayed_suppliers is True


@pytest.mark.asyncio
async def test_executor_parallelizes_independent_steps() -> None:
    steps = [
        AnalysisPlanStep(
            step_id="supplier",
            objective="供应商履约",
            tool=AnalysisToolName.GET_SUPPLIER_PERFORMANCE,
            arguments={"supplier_id": 92001},
            independent=True,
        ),
        AnalysisPlanStep(
            step_id="cases",
            objective="相似案例",
            tool=AnalysisToolName.GET_SIMILAR_CASES,
            arguments={"requirement_id": 91001},
            independent=True,
        ),
    ]
    plan = AnalysisPlan(
        goal="综合分析",
        steps=steps,
        termination_condition="工具完成",
    )
    client = FakeAnalysisClient()

    result = await AnalysisExecutor().execute(
        plan,
        client,
        DeterministicAnalysisPlanner(),
    )

    assert result.successful_steps == 2
    assert client.max_active == 2


@pytest.mark.asyncio
async def test_planner_creates_parallel_multi_tool_plan() -> None:
    plan = await DeterministicAnalysisPlanner().create_plan(
        "对比供应商 92001 的履约和采购申请 91001 的相似案例"
    )

    assert [step.tool for step in plan.steps] == [
        AnalysisToolName.GET_SUPPLIER_PERFORMANCE,
        AnalysisToolName.GET_SIMILAR_CASES,
    ]


@pytest.mark.asyncio
async def test_planner_uses_controlled_supplier_recommendation_tool() -> None:
    plan = await DeterministicAnalysisPlanner().create_plan("为采购申请 91003 推荐供应商")

    assert plan.steps[0].tool is AnalysisToolName.RECOMMEND_SUPPLIERS
    assert plan.steps[0].arguments == {"requirement_id": 91003, "limit": 10}
    assert all(step.independent for step in plan.steps)


def test_context_single_tool_shortcuts_skip_model_planner() -> None:
    assert ProcurementGraphService._should_use_model_planner("为采购申请 91003 推荐供应商") is False
    assert (
        ProcurementGraphService._should_use_model_planner("查看采购申请 91003 的相似案例") is False
    )
    for message in (
        "按状态统计采购申请数量",
        "分析各楼宇的采购申请数量并进行对比",
        "统计已完成采购申请的总金额",
        "按设备名称统计采购数量并给出排名",
        "分析今年采购申请数量的月度趋势",
    ):
        assert ProcurementGraphService._should_use_model_planner(message) is False
    assert ProcurementGraphService._should_use_model_planner("筛选哪些采购申请需要综合研判") is True


def test_analysis_plan_rejects_filters_outside_query() -> None:
    with pytest.raises(ValidationError):
        AnalysisPlanStep(
            step_id="invalid_filters",
            objective="非法 Planner 输出",
            tool=AnalysisToolName.QUERY_PURCHASE_ANALYTICS,
            arguments={"query": {"aggregations": ["TOTAL_AMOUNT"]}, "filters": {}},
        )


@pytest.mark.asyncio
async def test_executor_adjusts_once_without_repeating_successful_step() -> None:
    timeout = MCPToolResponse.failure(
        "MCP_TOOL_TIMEOUT",
        "超时",
        source="mcp://query_purchase_analytics",
        trace_id="trace-analysis",
    )
    client = FakeAnalysisClient({"query_purchase_analytics": [timeout, analytics_response()]})
    service = AnalysisAgentService()

    result = await service.run("统计服务器采购数量", client)

    assert len(client.calls) == 2
    assert result.plan.revision_count == 1
    assert result.step_results[0].success is False
    assert result.step_results[1].success is True


@pytest.mark.asyncio
async def test_executor_does_not_repeat_completed_step_during_adjustment() -> None:
    ok = analytics_response()
    timeout = MCPToolResponse.failure(
        "MCP_TOOL_TIMEOUT",
        "超时",
        source="mcp://get_similar_cases",
        trace_id="trace-analysis",
    )
    client = FakeAnalysisClient(
        {
            "get_supplier_performance": [ok],
            "get_similar_cases": [timeout, ok],
        }
    )
    plan = AnalysisPlan(
        goal="综合分析",
        steps=[
            AnalysisPlanStep(
                step_id="supplier",
                objective="履约",
                tool=AnalysisToolName.GET_SUPPLIER_PERFORMANCE,
                arguments={"supplier_id": 92001},
            ),
            AnalysisPlanStep(
                step_id="cases",
                objective="案例",
                tool=AnalysisToolName.GET_SIMILAR_CASES,
                arguments={"requirement_id": 91001},
                depends_on=["supplier"],
            ),
        ],
        termination_condition="工具完成",
    )

    result = await AnalysisExecutor().execute(
        plan,
        client,
        DeterministicAnalysisPlanner(),
    )

    assert [name for name, _ in client.calls].count("get_supplier_performance") == 1
    assert [name for name, _ in client.calls].count("get_similar_cases") == 2
    assert result.plan.revision_count == 1


def graph_request(
    message: str,
    restored_state: ConversationStateData | None = None,
) -> GraphRunRequest:
    return GraphRunRequest(
        task_id=uuid4(),
        trace_id="trace-analysis",
        conversation_id=1,
        identity=BackendIdentity(
            platform_type="TEST_PLATFORM",
            platform_user_id="user-1",
        ),
        current_user=CurrentUserData(
            employee_id=1,
            employee_no="E001",
            name="需求人",
            mobile=None,
            status="ACTIVE",
            platform_type="TEST_PLATFORM",
            platform_user_id="user-1",
            roles=[],
            buildings=[],
        ),
        message=message,
        restored_state=restored_state,
    )


@pytest.mark.asyncio
async def test_complex_query_graph_returns_structured_analysis_and_persists_context() -> None:
    client = FakeAnalysisClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )
    service = ProcurementGraphService(settings, mcp_client_factory=factory)
    request = graph_request("统计各楼宇服务器采购数量和总金额，排除黑名单")

    result = await service.run(request)
    state = GraphMemoryMapper.to_backend_state(request, result)

    assert result.route is RouteType.COMPLEX_QUERY
    assert result.analysis is not None
    assert result.analysis.summary["count"] == 9
    assert result.analysis.table is not None
    assert result.analysis.table.total == 9
    assert result.tool_call_count == 1
    assert state.collected_data["analysis_query_context"]["device_name"] == "服务器"
    assert "后端授权范围" in result.reply


@pytest.mark.asyncio
async def test_device_term_lookup_is_recorded_in_graph_trace() -> None:
    client = FakeAnalysisClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    lookup = DeviceTermLookupResult(
        status=DeviceTermLookupStatus.SEMANTIC,
        query_term="UPS功率模块",
        device_profession="UPS",
        semantic_used=True,
        embedding_latency_ms=12,
        qdrant_latency_ms=3,
        total_latency_ms=15,
        candidates=[
            DeviceTermCandidate(
                device_name="UPS模块", device_profession="UPS", score=0.9
            )
        ],
        top_k=5,
    )
    configured = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )
    service = ProcurementGraphService(
        configured,
        mcp_client_factory=factory,
        analysis_agent=AnalysisAgentService(
            device_term_search=FakeDeviceTermSearch(lookup)
        ),
    )

    result = await service.run(graph_request("统计以前UPS功率模块的采购数量"))

    trace = next(item for item in result.trace_events if item.name == "device_term_lookup")
    assert trace.arguments == {
        "query_device_term": "UPS功率模块",
        "device_profession": "UPS",
    }
    assert trace.result["embedding_latency_ms"] == 12
    assert trace.result["qdrant_search_latency_ms"] == 3
    assert trace.result["selected_device_names"] == ["UPS模块"]
    assert trace.result["fallback_triggered"] is False


@pytest.mark.asyncio
async def test_analysis_dates_are_not_persisted_as_purchase_request_id() -> None:
    client = FakeAnalysisClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )
    graph_request_value = graph_request(
        "统计 2026-08-01 到 2026-08-05 设备类型为服务器的采购数量和总金额"
    )

    result = await ProcurementGraphService(settings, mcp_client_factory=factory).run(
        graph_request_value
    )
    state = GraphMemoryMapper.to_backend_state(graph_request_value, result)

    assert result.route is RouteType.COMPLEX_QUERY
    assert result.purchase_request_id is None
    assert state.purchase_request_id is None


@pytest.mark.asyncio
async def test_graph_follow_up_restores_backend_confirmed_query() -> None:
    restored = ConversationStateData(
        conversation_id=1,
        purchase_request_id=None,
        current_action="CHAT",
        collected_data={
            "analysis_query_context": {
                "created_from": "2026-01-01",
                "created_to": "2026-06-30",
                "device_name": "服务器",
                "exclude_blacklisted": True,
            }
        },
        restored_from_snapshot=True,
    )
    client = FakeAnalysisClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )
    result = await ProcurementGraphService(settings, mcp_client_factory=factory).run(
        graph_request("再排除延期供应商并统计总金额", restored)
    )

    assert result.analysis is not None
    query = client.calls[0][1]["query"]
    assert query["created_from"] == "2026-01-01"
    assert query["device_name"] == "服务器"
    assert query["exclude_blacklisted"] is True
    assert query["exclude_delayed_suppliers"] is True


@pytest.mark.asyncio
async def test_model_failure_keeps_error_code_and_never_claims_analysis_complete() -> None:
    class FailingModelAnalysis:
        async def run(self, *_args, **_kwargs):
            raise StructuredModelRunError(
                "MODEL_CIRCUIT_OPEN",
                "模型服务熔断中",
                attempts=1,
                retryable=True,
            )

    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )
    result = await ProcurementGraphService(
        settings,
        analysis_agent=FailingModelAnalysis(),
    ).run(graph_request("统计服务器采购金额"))

    assert result.errors[0].code == "MODEL_CIRCUIT_OPEN"
    assert result.analysis is None
    assert result.tool_call_count == 0
    assert result.reply == "暂时无法完成采购分析：模型服务熔断中。"


@pytest.mark.asyncio
async def test_complex_query_calls_model_planner_and_records_plan_trace() -> None:
    client = FakeAnalysisClient()

    @asynccontextmanager
    async def factory(*_args):
        yield client

    outputs = [
        {
            "goal": "统计采购数量和金额",
            "steps": [
                {
                    "step_id": "purchase_summary",
                    "objective": "查询采购聚合数据",
                    "tool": "query_purchase_analytics",
                    "arguments": {
                        "query": {
                            "group_by": "BUILDING",
                            "aggregations": ["COUNT", "TOTAL_AMOUNT"],
                            "page": 1,
                            "page_size": 20,
                        }
                    },
                    "depends_on": [],
                    "independent": False,
                }
            ],
            "termination_condition": "聚合数据返回",
            "revision_count": 0,
            "query_context": {
                "group_by": "BUILDING",
                "aggregations": ["COUNT", "TOTAL_AMOUNT"],
                "page": 1,
                "page_size": 20,
            },
        },
        {
            "answer": "已根据实时工具结果完成统计。",
            "citations": [],
            "limitations": [],
            "requires_human_confirmation": False,
        },
        {
            "passed": False,
            "issues": [
                {
                    "code": "ANALYSIS_AS_FACT",
                    "severity": "BLOCKING",
                    "message": "需要把分析范围说明清楚",
                    "evidence_ids": [],
                }
            ],
            "requires_human_confirmation": False,
            "revised_answer": "已按后端可见数据完成统计，并明确限定统计范围。",
        },
    ]
    adapter = ScriptedModelAdapter(
        [
            StructuredModelResponse(
                provider="fake",
                model="planner-model",
                output=output,
                latency_ms=1,
            )
            for output in outputs
        ]
    )
    roles = StructuredModelRoles(
        StructuredModelRunner(adapter, timeout_seconds=1, max_retries=0),
        "trace-analysis",
    )
    configured = AgentSettings(
        _env_file=None,
        identity_gateway_secret="analysis-test-secret-123",
        procurement_backend_url="http://backend.test",
    )

    result = await ProcurementGraphService(
        configured,
        mcp_client_factory=factory,
        model_roles=roles,
    ).run(graph_request("筛选哪些采购申请需要综合研判"))

    assert [request.purpose for request in adapter.requests] == [
        ModelPurpose.ANALYSIS_PLAN,
        ModelPurpose.COMPOSE,
        ModelPurpose.REVIEW,
    ]
    planner_trace = next(item for item in result.trace_events if item.name == "model_planner")
    assert planner_trace.result["planner_called"] is True
    assert planner_trace.result["model_used"] is True
    assert planner_trace.result["actual_model"] == "planner-model"
    assert planner_trace.result["plan"]["steps"][0]["tool"] == "query_purchase_analytics"
    assert result.reply == "已按后端可见数据完成统计，并明确限定统计范围。"
    review_trace = next(item for item in result.trace_events if item.name == "review")
    assert review_trace.result["review_output_enforced"] is True
    assert review_trace.result["revised_answer_used"] is True
