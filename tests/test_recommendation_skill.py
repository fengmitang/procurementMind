from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_app.core.config import AgentSettings
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.router import FirstVersionRouter
from agent_app.graph.schemas import GraphRunRequest, RouteType
from agent_app.graph.service import ProcurementGraphService
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.schemas.backend import (
    BackendIdentity,
    ConversationStateData,
    CurrentUserData,
    UserBuildingData,
    UserRoleData,
)
from agent_app.skills.base import SkillExecutionContext
from agent_app.skills.procurement_recommendation.resolver import RecommendationProfileResolver
from agent_app.skills.procurement_recommendation.schemas import (
    RecommendationProfileId,
    RecommendationType,
    RequesterCandidateFields,
    SupplierCandidateFields,
    WarehouseCandidateFields,
)
from agent_app.skills.procurement_recommendation.service import ProcurementRecommendationSkill
from agent_app.skills.procurement_recommendation.time_parser import parse_time_range
from scripts.seed_demo_dataset import build_dataset


def user(*roles: str) -> CurrentUserData:
    return CurrentUserData(
        employee_id=1,
        employee_no="E001",
        name="测试用户",
        mobile=None,
        status="ACTIVE",
        platform_type="TEST_PLATFORM",
        platform_user_id="user-1",
        roles=[
            UserRoleData(role_id=index, role_code=role, role_name=role)
            for index, role in enumerate(roles, start=1)
        ],
        buildings=[UserBuildingData(building_id=1, building_name="一号楼", is_primary=True)],
    )


class FakeRecommendationClient:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict | None = None) -> MCPToolResponse:
        self.calls.append((name, arguments or {}))
        return MCPToolResponse.ok(
            self.responses.get(name, {"items": []}),
            source=f"/fake/{name}",
            trace_id="trace-recommendation",
        )


class FakeDeviceTermSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def lookup(self, device_name: str, device_profession: str):
        self.calls.append((device_name, device_profession))
        return SimpleNamespace(selected_names=["机架服务器", "计算节点"])


def factory_for(client: FakeRecommendationClient):
    @asynccontextmanager
    async def factory(_settings, _identity, _trace_id):
        yield client

    return factory


def context(message: str, current_user: CurrentUserData, client, requirement_id=None):
    return SkillExecutionContext(
        message=message,
        current_user=current_user,
        identity=BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="user-1"),
        trace_id="trace-recommendation",
        purchase_request_id=requirement_id,
        mcp_client_factory=factory_for(client),
        settings=object(),
    )


PRODUCT_ITEMS = {
    "items": [
        {
            "reference_id": 101,
            "device_profession": "服务器",
            "device_name": "机架服务器",
            "brand": "浪潮",
            "model": "NF5180M6",
            "purchased_at": "2026-07-10T10:00:00",
        },
        {
            "reference_id": 102,
            "device_profession": "服务器",
            "device_name": "机架服务器",
            "brand": "华为",
            "model": None,
            "purchased_at": "2026-06-10T10:00:00",
        },
    ]
}


@pytest.mark.asyncio
async def test_requester_recommendation_is_aggregated_without_sensitive_fields() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    result = await ProcurementRecommendationSkill().execute(
        context("给我推荐一下服务器品牌和型号", user("APPLICANT"), client)
    )

    output = result.output
    assert output.profile is RecommendationProfileId.REQUESTER
    assert output.recommendation_type is RecommendationType.BRAND_MODEL
    assert len(output.candidates) == 2
    assert all(isinstance(item.fields, RequesterCandidateFields) for item in output.candidates)
    requester_fields = output.candidates[0].fields.model_dump()
    assert not (
        {"supplier_id", "supplier_name", "reference_unit_price", "contract_type"}
        & requester_fields.keys()
    )
    serialized = output.model_dump(mode="json")
    assert "supplier_id" not in serialized["query_context"]
    assert "supplier_name" not in serialized["query_context"]
    assert len(output.evidence) == 2
    assert output.retrieval_stages_used


@pytest.mark.asyncio
async def test_applicant_supplier_request_is_denied_with_legal_alternative() -> None:
    client = FakeRecommendationClient({})
    result = await ProcurementRecommendationSkill().execute(
        context("给我推荐几个服务器供应商", user("APPLICANT"), client)
    )

    assert result.output.clarification_required is True
    assert "权限不支持供应商推荐" in result.output.clarification_message
    assert "品牌和型号" in result.output.clarification_message
    assert client.calls == []


@pytest.mark.asyncio
async def test_building_manager_keeps_blacklisted_supplier_and_original_rank() -> None:
    items = {
        "items": [
            {
                "reference_id": 201,
                "supplier_id": 1,
                "supplier_name": "供应商A",
                "supplier_contact_name": "张三",
                "supplier_contact_info": "13800000000",
                "actual_unit_price": "1000.00",
                "contract_type": "设备采购合同",
                "payment_method": "验收后付款",
                "blacklist_status": "BLACKLISTED",
                "blacklist_history_count": 1,
                "purchased_at": "2026-07-10T10:00:00",
            },
            {
                "reference_id": 202,
                "supplier_id": 1,
                "supplier_name": "供应商A",
                "supplier_contact_name": None,
                "supplier_contact_info": None,
                "actual_unit_price": "900.00",
                "contract_type": None,
                "payment_method": None,
                "blacklist_status": "BLACKLISTED",
                "blacklist_history_count": 1,
                "purchased_at": "2026-06-10T10:00:00",
            },
            {
                "reference_id": 203,
                "supplier_id": 2,
                "supplier_name": "供应商B",
                "supplier_contact_name": None,
                "supplier_contact_info": None,
                "actual_unit_price": "800.00",
                "contract_type": None,
                "payment_method": None,
                "blacklist_status": "HISTORY",
                "blacklist_history_count": 1,
                "purchased_at": "2026-07-11T10:00:00",
            },
        ]
    }
    client = FakeRecommendationClient({"search_supplier_recommendation_evidence": items})
    result = await ProcurementRecommendationSkill().execute(
        context("推荐服务器供应商", user("BUILDING_MANAGER"), client)
    )

    assert [item.fields.supplier_id for item in result.output.candidates] == [1, 2]
    first = result.output.candidates[0]
    assert isinstance(first.fields, SupplierCandidateFields)
    assert first.evidence_count == 2
    assert "当前处于有效黑名单" in first.warnings
    assert "存在历史黑名单记录，当前已解除" in result.output.candidates[1].warnings


@pytest.mark.asyncio
async def test_purchaser_and_warehouse_profiles_aggregate_declared_keys() -> None:
    contract_client = FakeRecommendationClient(
        {
            "search_supplier_contract_evidence": {
                "items": [
                    {
                        "reference_id": 301,
                        "supplier_id": 1,
                        "supplier_name": "供应商A",
                        "tax_rate": "13.00",
                        "contract_contact_info": "张三 13800000000",
                        "purchased_at": "2026-07-10T10:00:00",
                    },
                    {
                        "reference_id": 302,
                        "supplier_id": 1,
                        "supplier_name": "供应商A",
                        "tax_rate": "13.00",
                        "contract_contact_info": "张三 13800000000",
                        "purchased_at": "2026-06-10T10:00:00",
                    },
                ],
                "ambiguous_suppliers": [],
            }
        }
    )
    contract = await ProcurementRecommendationSkill().execute(
        context(
            "供应商为供应商A，推荐历史税率和合同联系方式",
            user("PURCHASER"),
            contract_client,
        )
    )
    assert contract.output.profile is RecommendationProfileId.PURCHASER
    assert contract.output.candidates[0].evidence_count == 2

    warehouse_client = FakeRecommendationClient(
        {
            "search_warehouse_evidence": {
                "items": [
                    {
                        "reference_id": 401,
                        "device_profession": "服务器",
                        "device_name": "机架服务器",
                        "warehouse_location": "A-01",
                        "received_quantity": 3,
                        "received_at": "2026-07-10T10:00:00",
                    }
                ]
            }
        }
    )
    warehouse = await ProcurementRecommendationSkill().execute(
        context("服务器以前一般入哪个仓库", user("WAREHOUSE_MANAGER"), warehouse_client)
    )
    assert isinstance(warehouse.output.candidates[0].fields, WarehouseCandidateFields)
    assert warehouse.output.candidates[0].fields.warehouse_location == "A-01"


@pytest.mark.asyncio
async def test_contract_recommendation_without_supplier_uses_contract_evidence_tool() -> None:
    client = FakeRecommendationClient(
        {
            "search_supplier_contract_evidence": {
                "items": [
                    {
                        "reference_id": 303,
                        "supplier_id": 7,
                        "supplier_name": "历史供应商",
                        "tax_rate": "13.00",
                        "contract_contact_info": "合同联络渠道",
                        "purchased_at": "2026-05-10T10:00:00",
                    }
                ],
                "ambiguous_suppliers": [],
            }
        }
    )

    result = await ProcurementRecommendationSkill().execute(
        context(
            "比较服务器采购可参考的历史合同信息",
            user("APPLICANT", "PURCHASER"),
            client,
        )
    )

    assert client.calls == [("search_supplier_contract_evidence", {"limit": 20})]
    assert result.output.profile is RecommendationProfileId.PURCHASER
    assert result.output.recommendation_type is RecommendationType.PURCHASER_CONTRACT
    assert result.output.clarification_required is False
    assert len(result.output.evidence) == 1
    assert len(result.output.candidates) == 1


def test_resolver_treats_general_contract_request_as_contract_recommendation() -> None:
    resolution = RecommendationProfileResolver().resolve(
        "核实历史合同条款作为采购参考",
        user("APPLICANT", "PURCHASER"),
        request_status=None,
    )

    assert resolution.explicit_type is RecommendationType.PURCHASER_CONTRACT
    assert resolution.profile is not None
    assert resolution.profile.profile_id is RecommendationProfileId.PURCHASER


@pytest.mark.asyncio
async def test_ambiguous_supplier_name_requires_clarification() -> None:
    client = FakeRecommendationClient(
        {
            "search_supplier_contract_evidence": {
                "items": [],
                "ambiguous_suppliers": [
                    {"supplier_id": 1, "supplier_name": "同名供应商"},
                    {"supplier_id": 2, "supplier_name": "同名供应商"},
                ],
            }
        }
    )
    result = await ProcurementRecommendationSkill().execute(
        context(
            "供应商为同名供应商，推荐历史税率和合同联系方式",
            user("PURCHASER"),
            client,
        )
    )

    assert result.output.clarification_required is True
    assert "多个主体" in result.output.clarification_message
    assert result.output.candidates == []


def test_resolver_honors_explicit_type_and_stage_context() -> None:
    resolver = RecommendationProfileResolver()
    multi_role = user("APPLICANT", "BUILDING_MANAGER", "PURCHASER")

    explicit = resolver.resolve("推荐品牌型号", multi_role, request_status="PENDING_REVIEW")
    assert explicit.profile.profile_id is RecommendationProfileId.REQUESTER
    staged = resolver.resolve("给我历史参考", multi_role, request_status="PENDING_REVIEW")
    assert staged.profile.profile_id is RecommendationProfileId.BUILDING_MANAGER
    no_context = resolver.resolve("给我历史参考", multi_role, request_status=None)
    assert no_context.profile is None
    assert no_context.clarification_message
    admin = resolver.resolve("给我历史参考", user("ADMIN"), request_status=None)
    assert admin.profile is None


def test_time_range_parser_and_no_default_range() -> None:
    current = date(2026, 8, 19)
    recent = parse_time_range("推荐近2个月的服务器历史型号", today=current)
    assert recent.start == date(2026, 6, 19)
    assert recent.end == current
    explicit = parse_time_range("2026-05-01 到 2026-07-01", today=current)
    assert explicit.start == date(2026, 5, 1)
    assert explicit.end == date(2026, 7, 1)
    unrestricted = parse_time_range("推荐服务器型号", today=current)
    assert unrestricted.start is None
    assert unrestricted.end is None


def test_full_demo_history_is_separate_and_supports_recommendation() -> None:
    dataset = build_dataset(
        list(range(1, 10)),
        {
            "APPLICANT": 1,
            "BUILDING_MANAGER": 2,
            "PURCHASER": 3,
            "WAREHOUSE_MANAGER": 4,
            "ADMIN": 5,
        },
    )
    requests = dataset["requests"]
    executions = dataset["executions"]

    assert len(requests) == 210
    assert len(executions) == 100
    assert all(item["request_no"].startswith("DEMO-PR-") for item in requests)
    assert all(not item["request_no"].startswith("TEST-") for item in requests)
    request_ids = {item["request_id"] for item in requests}
    assert {item["request_id"] for item in executions} <= request_ids
    assert any(item["device_profession"] == "服务器" for item in requests)


@pytest.mark.asyncio
async def test_all_progressive_stages_share_time_range_and_deduplicate_evidence() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    result = await ProcurementRecommendationSkill().execute(
        context("推荐近2个月的服务器品牌型号", user("APPLICANT"), client)
    )

    evidence_calls = [arguments for name, arguments in client.calls if name.startswith("search_")]
    assert len(evidence_calls) >= 2
    assert all(
        item["purchased_from"] == result.output.time_range.start.isoformat()
        for item in evidence_calls
    )
    assert all(
        item["purchased_to"] == result.output.time_range.end.isoformat() for item in evidence_calls
    )
    assert len(result.output.evidence) == 2
    assert len({item.reference_id for item in result.output.evidence}) == 2


@pytest.mark.asyncio
async def test_skill_reuses_device_term_search_candidates() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    search = FakeDeviceTermSearch()
    skill = ProcurementRecommendationSkill()
    skill.set_device_term_search(search)

    await skill.execute(
        context("推荐服务器专业下机架式计算节点的品牌型号", user("APPLICANT"), client)
    )

    assert search.calls == [("计算节点", "服务器")]
    evidence_call = next(
        arguments for name, arguments in client.calls if name.startswith("search_")
    )
    assert evidence_call["device_names"] == ["机架服务器", "计算节点"]


@pytest.mark.asyncio
async def test_skill_does_not_map_ambiguous_device_term_without_profession() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    search = FakeDeviceTermSearch()
    skill = ProcurementRecommendationSkill()
    skill.set_device_term_search(search)

    result = await skill.execute(context("推荐机架式计算节点的品牌型号", user("APPLICANT"), client))

    assert search.calls == []
    assert result.output.candidates == []
    assert result.output.clarification_message == "请提供需要参考的设备类型或设备名称。"


@pytest.mark.asyncio
async def test_skill_enforces_output_limits_and_handles_partial_or_empty_evidence() -> None:
    many_items = {
        "items": [
            {
                "reference_id": 500 + index,
                "device_profession": "服务器",
                "device_name": "机架服务器",
                "brand": f"品牌{index}",
                "model": None,
                "purchased_at": f"2026-07-{(index % 20) + 1:02d}T10:00:00",
            }
            for index in range(25)
        ]
    }
    limited = await ProcurementRecommendationSkill().execute(
        context(
            "推荐服务器品牌型号",
            user("APPLICANT"),
            FakeRecommendationClient({"search_product_history_evidence": many_items}),
        )
    )

    assert len(limited.output.evidence) == 20
    assert len(limited.output.candidates) == 5
    assert all(item.fields.brand for item in limited.output.candidates)
    assert all(item.fields.model is None for item in limited.output.candidates)

    empty = await ProcurementRecommendationSkill().execute(
        context(
            "推荐冷水机组品牌型号",
            user("APPLICANT"),
            FakeRecommendationClient({"search_product_history_evidence": {"items": []}}),
        )
    )
    assert empty.output.candidates == []
    assert empty.output.no_result_reason == "未查询到相关历史采购记录，暂无可参考推荐。"


@pytest.mark.asyncio
async def test_graph_routes_executes_skill_traces_and_persists_compact_result() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="recommendation-test-secret",
        procurement_backend_url="http://backend.test",
    )
    graph_request = GraphRunRequest(
        task_id=uuid4(),
        trace_id="trace-recommendation",
        conversation_id=1,
        identity=BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="user-1"),
        current_user=user("APPLICANT"),
        message="给我推荐一下服务器品牌型号",
    )
    result = await ProcurementGraphService(settings, mcp_client_factory=factory_for(client)).run(
        graph_request
    )

    assert result.route is RouteType.RECOMMENDATION
    assert result.recommendation is not None
    assert result.pending_action is None
    trace = next(
        item for item in result.trace_events if item.name == "skill.procurement_recommendation"
    )
    assert trace.result["skill_id"] == "procurement_recommendation"
    assert trace.result["skill_version"] == "1.0"
    state = GraphMemoryMapper.to_backend_state(graph_request, result)
    assert len(state.last_recommendations) == 1
    assert "evidence" not in state.last_recommendations[0]
    assert state.last_recommendations[0]["reference_ids"] == [101, 102]


@pytest.mark.asyncio
async def test_completed_form_recommendation_confirmation_reuses_draft_context() -> None:
    client = FakeRecommendationClient({"search_product_history_evidence": PRODUCT_ITEMS})
    restored = ConversationStateData(
        conversation_id=1,
        current_action="CHAT",
        collected_data={
            "form_draft": {
                "building_id": 1,
                "device_profession": "服务器",
                "device_name": "机架服务器",
                "quantity": 3,
                "unit": "台",
                "application_reason": "扩容",
            },
            "form_missing_fields": [],
        },
    )
    request = GraphRunRequest(
        task_id=uuid4(),
        trace_id="trace-form-recommendation",
        conversation_id=1,
        identity=BackendIdentity(platform_type="TEST_PLATFORM", platform_user_id="user-1"),
        current_user=user("APPLICANT"),
        message="需要",
        restored_state=restored,
    )
    settings = AgentSettings(
        _env_file=None,
        identity_gateway_secret="recommendation-test-secret",
        procurement_backend_url="http://backend.test",
    )

    result = await ProcurementGraphService(settings, mcp_client_factory=factory_for(client)).run(
        request
    )

    assert result.route is RouteType.RECOMMENDATION
    assert result.recommendation.query_context.device_profession == "服务器"
    assert result.recommendation.query_context.device_name == "机架服务器"
    assert result.pending_action is None


def test_router_keeps_knowledge_complex_and_form_paths_stable() -> None:
    router = FirstVersionRouter()
    assert router.classify("推荐供应商") is RouteType.RECOMMENDATION
    assert router.classify("供应商黑名单制度是什么？") is RouteType.KNOWLEDGE
    assert router.classify("按月份统计采购金额") is RouteType.COMPLEX_QUERY
    assert router.classify("我要采购3台服务器") is RouteType.FORM_PREFILL
