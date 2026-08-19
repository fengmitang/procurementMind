"""Exercise production MCP tools and recommendation skill against the DEMO dataset."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from agent_app.core.config import get_agent_settings
from agent_app.graph.service import default_mcp_client_factory
from agent_app.schemas.backend import (
    BackendIdentity,
    CurrentUserData,
    UserBuildingData,
    UserRoleData,
)
from agent_app.skills.base import SkillExecutionContext
from agent_app.skills.procurement_recommendation.service import ProcurementRecommendationSkill
from app.db.session import async_session_factory
from app.models.procurement import PurchaseExecution, PurchaseRequest


def _user(index: int, role: str, building_ids: list[int] | None = None) -> CurrentUserData:
    return CurrentUserData(
        employee_id=8_100_000 + index,
        employee_no=f"DEMO-E{index:03d}",
        name=f"演示用户{index:02d}",
        mobile=f"DEMO-MOBILE-{index:03d}",
        status="ACTIVE",
        platform_type="WEB",
        platform_user_id=f"demo_user_{index:03d}",
        roles=[UserRoleData(role_id=index, role_code=role, role_name=role)],
        buildings=[
            UserBuildingData(building_id=value, building_name=f"{value}号楼", is_primary=pos == 0)
            for pos, value in enumerate(building_ids or [])
        ],
    )


async def _recommend(index: int, role: str, message: str) -> list[dict[str, Any]]:
    settings = get_agent_settings()
    identity = BackendIdentity(platform_type="WEB", platform_user_id=f"demo_user_{index:03d}")
    result = await ProcurementRecommendationSkill().execute(
        SkillExecutionContext(
            message=message,
            current_user=_user(index, role, [1, 2] if role == "BUILDING_MANAGER" else []),
            identity=identity,
            trace_id=f"demo-capability-{index}",
            purchase_request_id=None,
            mcp_client_factory=default_mcp_client_factory,
            settings=settings,
        )
    )
    return [
        {
            "title": candidate.title,
            "fields": candidate.fields.model_dump(mode="json"),
            "evidence_count": candidate.evidence_count,
            "warnings": candidate.warnings,
        }
        for candidate in result.output.candidates
    ]


async def _mcp_calls() -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_agent_settings()
    identity = BackendIdentity(platform_type="WEB", platform_user_id="demo_user_005")
    complex_queries = {
        "building_count": {"group_by": "BUILDING", "aggregations": ["COUNT"]},
        "server_amount_6m": {
            "created_from": "2026-02-19",
            "created_to": "2026-08-19",
            "device_professions": ["服务器"],
            "aggregations": ["COUNT", "TOTAL_AMOUNT"],
        },
        "brand_average": {
            "group_by": "BRAND",
            "aggregations": ["COUNT", "AVERAGE_UNIT_PRICE"],
        },
        "monthly_trend": {"group_by": "MONTH", "aggregations": ["COUNT", "TOTAL_AMOUNT"]},
        "supplier_ranking": {"group_by": "SUPPLIER", "aggregations": ["COUNT", "TOTAL_AMOUNT"]},
    }
    query_results: dict[str, Any] = {}
    risk_results: dict[str, Any] = {}
    async with default_mcp_client_factory(settings, identity, "demo-capability-admin") as client:
        for name, query in complex_queries.items():
            response = await client.call_tool("query_purchase_analytics", {"query": query})
            data = response.data or {}
            query_results[name] = {
                "success": response.success,
                "total": data.get("total"),
                "summary": data.get("summary"),
                "top_groups": (data.get("groups") or [])[:5],
            }
        async with async_session_factory() as session:
            request_ids = list(
                (
                    await session.scalars(
                        select(PurchaseRequest.request_id)
                        .join(PurchaseExecution)
                        .where(PurchaseRequest.request_no.like("DEMO-PR-%"))
                        .order_by(PurchaseRequest.request_id)
                    )
                ).all()
            )
        for request_id in request_ids:
            response = await client.call_tool(
                "get_requirement_risk_signals", {"requirement_id": request_id}
            )
            data = response.data or {}
            matched = [item["risk_code"] for item in data.get("signals", []) if item.get("matched")]
            if matched:
                risk_results[str(request_id)] = matched
            if any("PRICE_DEVIATION" in values for values in risk_results.values()) and any(
                "SUPPLIER_BLACKLIST" in values for values in risk_results.values()
            ):
                break
    return query_results, risk_results


async def main() -> None:
    supplier_name = "合肥新能制冷05号有限公司"
    recommendations = {
        "requester_all": await _recommend(1, "APPLICANT", "推荐服务器品牌型号"),
        "requester_recent_2m": await _recommend(1, "APPLICANT", "推荐近2个月的服务器品牌型号"),
        "building_manager": await _recommend(10, "BUILDING_MANAGER", "给我推荐服务器的历史供应商"),
        "purchaser": await _recommend(
            3, "PURCHASER", f"供应商为{supplier_name}，历史一般用什么税率和合同联系方式？"
        ),
        "warehouse": await _recommend(4, "WAREHOUSE_MANAGER", "服务器历史一般放在哪个仓库？"),
    }
    queries, risks = await _mcp_calls()
    print(
        json.dumps(
            {"recommendations": recommendations, "complex_queries": queries, "risks": risks},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
