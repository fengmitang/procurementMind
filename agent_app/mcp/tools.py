import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from agent_app.clients.errors import ProcurementBackendError
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.mcp.runtime import MCPTrustedContext
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.schemas.analytics import AnalyticsQueryInput


class ProcurementTools:
    """P0 read-only tool whitelist. Identity never comes from tool arguments."""

    def __init__(
        self,
        backend: ProcurementBackendClient,
        context: MCPTrustedContext,
        *,
        timeout_seconds: float,
    ) -> None:
        self.backend = backend
        self.context = context
        self.timeout_seconds = timeout_seconds

    async def get_current_user(self) -> MCPToolResponse:
        return await self._execute(
            "/api/v1/users/me",
            lambda: self.backend.get_current_user(
                self.context.identity,
                self.context.trace_id,
            ),
        )

    async def get_purchase_request(self, requirement_id: int) -> MCPToolResponse:
        return await self._execute(
            f"/api/v1/requirements/{requirement_id}",
            lambda: self.backend.get_requirement(
                self.context.identity,
                requirement_id,
                self.context.trace_id,
            ),
        )

    async def get_purchase_timeline(self, requirement_id: int) -> MCPToolResponse:
        return await self._execute(
            f"/api/v1/requirements/{requirement_id}/timeline",
            lambda: self.backend.get_requirement_timeline(
                self.context.identity,
                requirement_id,
                self.context.trace_id,
            ),
        )

    async def search_purchase_records(
        self,
        *,
        requirement_no: str | None = None,
        supplier_id: int | None = None,
        status: str | None = None,
        device_name: str | None = None,
        brand: str | None = None,
        model: str | None = None,
        created_from: date | None = None,
        created_to: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> MCPToolResponse:
        if created_from and created_to:
            range_days = (created_to - created_from).days
            if range_days < 0 or range_days > 366:
                return MCPToolResponse.failure(
                    "MCP_INVALID_ARGUMENT",
                    "采购记录日期范围必须按先后顺序且不超过 366 天",
                    source="/api/v1/purchase-records",
                    trace_id=self.context.trace_id,
                )
        return await self._execute(
            "/api/v1/purchase-records",
            lambda: self.backend.search_purchase_records(
                self.context.identity,
                self.context.trace_id,
                requirement_no=requirement_no,
                supplier_id=supplier_id,
                status=status,
                device_name=device_name,
                brand=brand,
                model=model,
                created_from=created_from.isoformat() if created_from else None,
                created_to=created_to.isoformat() if created_to else None,
                page=page,
                page_size=page_size,
            ),
        )

    async def recommend_products(
        self,
        *,
        device_name: str,
        device_profession: str | None = None,
        keyword: str | None = None,
        limit: int = 10,
    ) -> MCPToolResponse:
        return await self._execute(
            "/api/v1/recommendations/products",
            lambda: self.backend.recommend_products(
                self.context.identity,
                self.context.trace_id,
                device_name=device_name,
                device_profession=device_profession,
                keyword=keyword,
                limit=limit,
            ),
        )

    async def recommend_purchase_history(
        self,
        *,
        requirement_id: int,
        limit: int = 10,
    ) -> MCPToolResponse:
        return await self._execute(
            "/api/v1/recommendations/purchase-history",
            lambda: self.backend.recommend_purchase_history(
                self.context.identity,
                self.context.trace_id,
                requirement_id=requirement_id,
                limit=limit,
            ),
        )

    async def recommend_suppliers(
        self,
        *,
        requirement_id: int,
        limit: int = 10,
    ) -> MCPToolResponse:
        return await self._execute(
            "/api/v1/recommendations/suppliers",
            lambda: self.backend.recommend_suppliers(
                self.context.identity,
                self.context.trace_id,
                requirement_id=requirement_id,
                limit=limit,
            ),
        )

    async def query_purchase_analytics(
        self,
        query: AnalyticsQueryInput,
    ) -> MCPToolResponse:
        return await self._execute(
            "/api/v1/analytics/purchase-query",
            lambda: self.backend.query_purchase_analytics(
                self.context.identity,
                self.context.trace_id,
                query,
            ),
        )

    async def get_requirement_risk_signals(
        self,
        requirement_id: int,
    ) -> MCPToolResponse:
        return await self._execute(
            f"/api/v1/requirements/{requirement_id}/risk-signals",
            lambda: self.backend.get_requirement_risk_signals(
                self.context.identity,
                requirement_id,
                self.context.trace_id,
            ),
        )

    async def get_similar_cases(
        self,
        requirement_id: int,
        *,
        limit: int = 10,
    ) -> MCPToolResponse:
        return await self._execute(
            f"/api/v1/requirements/{requirement_id}/similar-cases",
            lambda: self.backend.get_similar_cases(
                self.context.identity,
                requirement_id,
                self.context.trace_id,
                limit=limit,
            ),
        )

    async def get_supplier_performance(
        self,
        supplier_id: int,
        *,
        created_from: date | None = None,
        created_to: date | None = None,
    ) -> MCPToolResponse:
        return await self._execute(
            f"/api/v1/suppliers/{supplier_id}/performance",
            lambda: self.backend.get_supplier_performance(
                self.context.identity,
                supplier_id,
                self.context.trace_id,
                created_from=created_from.isoformat() if created_from else None,
                created_to=created_to.isoformat() if created_to else None,
            ),
        )

    async def _execute(
        self,
        source: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> MCPToolResponse:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                data = await operation()
        except TimeoutError:
            return MCPToolResponse.failure(
                "MCP_TOOL_TIMEOUT",
                "采购工具调用超时",
                source=source,
                trace_id=self.context.trace_id,
            )
        except ProcurementBackendError as exc:
            return MCPToolResponse.failure(
                exc.code,
                exc.message,
                source=source,
                trace_id=self.context.trace_id,
            )
        return MCPToolResponse.ok(data, source=source, trace_id=self.context.trace_id)
