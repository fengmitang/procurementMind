from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent_app.mcp.catalog import tool_registration
from agent_app.mcp.runtime import MCPRuntime
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.mcp.tools import ProcurementTools
from agent_app.schemas.analytics import AnalyticsQueryInput


@asynccontextmanager
async def _lifespan(_: FastMCP):
    global _runtime
    try:
        yield None
    finally:
        if _runtime is not None:
            await _runtime.aclose()
            _runtime = None


mcp = FastMCP(
    name="procurement-mind",
    instructions="数据中心设备采购系统 P0 只读工具；权限和数据范围由采购后端最终校验。",
    lifespan=_lifespan,
)
_runtime: MCPRuntime | None = None


def _tools() -> ProcurementTools:
    global _runtime
    if _runtime is None:
        _runtime = MCPRuntime.from_environment()
    return ProcurementTools(
        _runtime.backend,
        _runtime.context,
        timeout_seconds=_runtime.settings.mcp_tool_timeout_seconds,
    )


PositiveId = Annotated[int, Field(gt=0)]
LimitedText = Annotated[str, Field(min_length=1, max_length=200)]
ResultLimit = Annotated[int, Field(ge=1, le=30)]


@mcp.tool(**tool_registration("get_current_user"))
async def get_current_user() -> MCPToolResponse:
    """读取当前可信平台用户、角色和可访问楼宇；不接受身份参数。"""
    return await _tools().get_current_user()


@mcp.tool(**tool_registration("get_purchase_request"))
async def get_purchase_request(requirement_id: PositiveId) -> MCPToolResponse:
    """读取已由系统定位的采购申请详情；参数是内部定位键，禁止向用户索取。"""
    return await _tools().get_purchase_request(requirement_id)


@mcp.tool(**tool_registration("get_purchase_timeline"))
async def get_purchase_timeline(requirement_id: PositiveId) -> MCPToolResponse:
    """读取已定位申请的时间线；内部定位键不得出现在用户交互中。"""
    return await _tools().get_purchase_timeline(requirement_id)


@mcp.tool(**tool_registration("search_purchase_records"))
async def search_purchase_records(
    requirement_no: LimitedText | None = None,
    supplier_id: PositiveId | None = None,
    status: LimitedText | None = None,
    device_name: LimitedText | None = None,
    brand: LimitedText | None = None,
    model: LimitedText | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: Annotated[int, Field(ge=1, le=20)] = 1,
    page_size: Annotated[int, Field(ge=1, le=50)] = 20,
) -> MCPToolResponse:
    """按受控条件检索当前用户可见的历史采购记录。"""
    return await _tools().search_purchase_records(
        requirement_no=requirement_no,
        supplier_id=supplier_id,
        status=status,
        device_name=device_name,
        brand=brand,
        model=model,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )


@mcp.tool(**tool_registration("recommend_products"))
async def recommend_products(
    device_name: LimitedText,
    device_profession: LimitedText | None = None,
    keyword: LimitedText | None = None,
    limit: ResultLimit = 10,
) -> MCPToolResponse:
    """根据历史采购返回产品候选，不代表兼容性确认。"""
    return await _tools().recommend_products(
        device_name=device_name,
        device_profession=device_profession,
        keyword=keyword,
        limit=limit,
    )


@mcp.tool(**tool_registration("recommend_purchase_history"))
async def recommend_purchase_history(
    requirement_id: PositiveId,
    limit: ResultLimit = 10,
) -> MCPToolResponse:
    """返回已由系统定位申请的历史候选；不得要求用户提供内部定位键。"""
    return await _tools().recommend_purchase_history(
        requirement_id=requirement_id,
        limit=limit,
    )


@mcp.tool(**tool_registration("recommend_suppliers"))
async def recommend_suppliers(
    requirement_id: PositiveId,
    limit: ResultLimit = 10,
) -> MCPToolResponse:
    """返回已定位申请的供应商候选；不得要求用户提供内部定位键。"""
    return await _tools().recommend_suppliers(
        requirement_id=requirement_id,
        limit=limit,
    )


@mcp.tool(**tool_registration("query_purchase_analytics"))
async def query_purchase_analytics(query: AnalyticsQueryInput) -> MCPToolResponse:
    """执行白名单采购查询和聚合；不接受 SQL 或任意字段。"""
    return await _tools().query_purchase_analytics(query)


@mcp.tool(**tool_registration("get_requirement_risk_signals"))
async def get_requirement_risk_signals(
    requirement_id: PositiveId,
) -> MCPToolResponse:
    """读取已定位申请的确定性风险结果；不得要求用户提供内部定位键。"""
    return await _tools().get_requirement_risk_signals(requirement_id)


@mcp.tool(**tool_registration("get_similar_cases"))
async def get_similar_cases(
    requirement_id: PositiveId,
    limit: Annotated[int, Field(ge=1, le=20)] = 10,
) -> MCPToolResponse:
    """读取已定位申请的可解释相似案例；不得要求用户提供内部定位键。"""
    return await _tools().get_similar_cases(requirement_id, limit=limit)


@mcp.tool(**tool_registration("get_supplier_performance"))
async def get_supplier_performance(
    supplier_id: PositiveId,
    created_from: date | None = None,
    created_to: date | None = None,
) -> MCPToolResponse:
    """读取供应商履约统计，比例同时包含分子和分母。"""
    return await _tools().get_supplier_performance(
        supplier_id,
        created_from=created_from,
        created_to=created_to,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
