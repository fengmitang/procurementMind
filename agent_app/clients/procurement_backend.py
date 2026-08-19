import asyncio
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from agent_app.clients.errors import (
    ProcurementBackendError,
    ProcurementBackendProtocolError,
    ProcurementBackendTimeout,
    ProcurementBackendUnavailable,
)
from agent_app.clients.signing import GatewaySigner
from agent_app.core.config import AgentSettings
from agent_app.schemas.analytics import (
    AnalyticsQueryInput,
    PurchaseQueryData,
    RequirementRiskData,
    SimilarCasesData,
    SupplierPerformanceData,
)
from agent_app.schemas.backend import (
    ActiveConversationData,
    BackendIdentity,
    BackendReadinessData,
    ConversationCompletedData,
    ConversationListData,
    ConversationStateData,
    ConversationStatePayload,
    CurrentUserData,
    FieldsSaveData,
    MessageCreatedData,
    MessageListData,
    ProductHistoryEvidenceData,
    ProductRecommendationData,
    PurchaseHistoryRecommendationData,
    PurchaseRecordListData,
    RequirementDetailData,
    RequirementMutationData,
    SnapshotSavedData,
    StateSavedData,
    SupplierContractEvidenceData,
    SupplierRecommendationData,
    SupplierRecommendationEvidenceData,
    TimelineData,
    WarehouseRecommendationEvidenceData,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class ProcurementBackendClient:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        signer: GatewaySigner | None = None,
    ) -> None:
        self.settings = settings
        self.signer = signer or GatewaySigner(settings.identity_gateway_secret)
        self._owns_http_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(
            base_url=settings.procurement_backend_url,
            timeout=settings.procurement_backend_timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self.http_client.aclose()

    async def readiness(self, trace_id: str) -> BackendReadinessData:
        return await self._request(
            "GET",
            "/ready",
            BackendReadinessData,
            trace_id=trace_id,
            identity=None,
            retryable=True,
        )

    async def get_current_user(
        self,
        identity: BackendIdentity,
        trace_id: str,
    ) -> CurrentUserData:
        return await self._request(
            "GET",
            "/api/v1/users/me",
            CurrentUserData,
            trace_id=trace_id,
            identity=identity,
            retryable=True,
        )

    async def get_requirement(
        self,
        identity: BackendIdentity,
        requirement_id: int,
        trace_id: str,
    ) -> RequirementDetailData:
        return await self._request(
            "GET",
            f"/api/v1/requirements/{requirement_id}",
            RequirementDetailData,
            trace_id=trace_id,
            identity=identity,
            retryable=True,
        )

    async def get_requirement_timeline(
        self,
        identity: BackendIdentity,
        requirement_id: int,
        trace_id: str,
    ) -> TimelineData:
        return await self._request(
            "GET",
            f"/api/v1/requirements/{requirement_id}/timeline",
            TimelineData,
            trace_id=trace_id,
            identity=identity,
            retryable=True,
        )

    async def search_purchase_records(
        self,
        identity: BackendIdentity,
        trace_id: str,
        *,
        requirement_no: str | None = None,
        supplier_id: int | None = None,
        status: str | None = None,
        device_name: str | None = None,
        brand: str | None = None,
        model: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PurchaseRecordListData:
        params = {
            "requirement_no": requirement_no,
            "supplier_id": supplier_id,
            "status": status,
            "device_name": device_name,
            "brand": brand,
            "model": model,
            "created_from": created_from,
            "created_to": created_to,
            "page": page,
            "page_size": page_size,
        }
        return await self._request(
            "GET",
            "/api/v1/purchase-records",
            PurchaseRecordListData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value is not None},
            retryable=True,
        )

    async def recommend_products(
        self,
        identity: BackendIdentity,
        trace_id: str,
        *,
        device_name: str,
        device_profession: str | None = None,
        keyword: str | None = None,
        limit: int = 10,
    ) -> ProductRecommendationData:
        params = {
            "device_name": device_name,
            "device_profession": device_profession,
            "keyword": keyword,
            "limit": limit,
        }
        return await self._request(
            "GET",
            "/api/v1/recommendations/products",
            ProductRecommendationData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value is not None},
            retryable=True,
        )

    async def recommend_purchase_history(
        self,
        identity: BackendIdentity,
        trace_id: str,
        *,
        requirement_id: int,
        limit: int = 10,
    ) -> PurchaseHistoryRecommendationData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/purchase-history",
            PurchaseHistoryRecommendationData,
            trace_id=trace_id,
            identity=identity,
            params={"requirement_id": requirement_id, "limit": limit},
            retryable=True,
        )

    async def recommend_suppliers(
        self,
        identity: BackendIdentity,
        trace_id: str,
        *,
        requirement_id: int,
        limit: int = 10,
    ) -> SupplierRecommendationData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/suppliers",
            SupplierRecommendationData,
            trace_id=trace_id,
            identity=identity,
            params={"requirement_id": requirement_id, "limit": limit},
            retryable=True,
        )

    async def search_product_history_evidence(
        self, identity: BackendIdentity, trace_id: str, **params
    ) -> ProductHistoryEvidenceData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/evidence/products",
            ProductHistoryEvidenceData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value not in (None, [])},
            retryable=True,
        )

    async def search_supplier_recommendation_evidence(
        self, identity: BackendIdentity, trace_id: str, **params
    ) -> SupplierRecommendationEvidenceData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/evidence/suppliers",
            SupplierRecommendationEvidenceData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value not in (None, [])},
            retryable=True,
        )

    async def search_supplier_contract_evidence(
        self, identity: BackendIdentity, trace_id: str, **params
    ) -> SupplierContractEvidenceData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/evidence/supplier-contracts",
            SupplierContractEvidenceData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value is not None},
            retryable=True,
        )

    async def search_warehouse_evidence(
        self, identity: BackendIdentity, trace_id: str, **params
    ) -> WarehouseRecommendationEvidenceData:
        return await self._request(
            "GET",
            "/api/v1/recommendations/evidence/warehouses",
            WarehouseRecommendationEvidenceData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value not in (None, [])},
            retryable=True,
        )

    async def query_purchase_analytics(
        self,
        identity: BackendIdentity,
        trace_id: str,
        query: AnalyticsQueryInput,
    ) -> PurchaseQueryData:
        return await self._request(
            "POST",
            "/api/v1/analytics/purchase-query",
            PurchaseQueryData,
            trace_id=trace_id,
            identity=identity,
            json=query.model_dump(mode="json"),
            retryable=True,
        )

    async def get_requirement_risk_signals(
        self,
        identity: BackendIdentity,
        requirement_id: int,
        trace_id: str,
    ) -> RequirementRiskData:
        return await self._request(
            "GET",
            f"/api/v1/requirements/{requirement_id}/risk-signals",
            RequirementRiskData,
            trace_id=trace_id,
            identity=identity,
            retryable=True,
        )

    async def get_similar_cases(
        self,
        identity: BackendIdentity,
        requirement_id: int,
        trace_id: str,
        *,
        limit: int = 10,
    ) -> SimilarCasesData:
        return await self._request(
            "GET",
            f"/api/v1/requirements/{requirement_id}/similar-cases",
            SimilarCasesData,
            trace_id=trace_id,
            identity=identity,
            params={"limit": limit},
            retryable=True,
        )

    async def get_supplier_performance(
        self,
        identity: BackendIdentity,
        supplier_id: int,
        trace_id: str,
        *,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> SupplierPerformanceData:
        params = {"created_from": created_from, "created_to": created_to}
        return await self._request(
            "GET",
            f"/api/v1/suppliers/{supplier_id}/performance",
            SupplierPerformanceData,
            trace_id=trace_id,
            identity=identity,
            params={key: value for key, value in params.items() if value is not None},
            retryable=True,
        )

    async def get_or_create_active_conversation(
        self,
        identity: BackendIdentity,
        *,
        current_action: str,
        trace_id: str,
        external_conversation_id: str | None = None,
    ) -> ActiveConversationData:
        return await self._request(
            "POST",
            "/api/v1/agent/conversations/active",
            ActiveConversationData,
            trace_id=trace_id,
            identity=identity,
            json={
                "current_action": current_action,
                "external_conversation_id": external_conversation_id,
            },
        )

    async def add_conversation_message(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        *,
        sender_type: str,
        content: str,
        trace_id: str,
        external_message_id: str | None = None,
        message_data: dict | None = None,
    ) -> MessageCreatedData:
        return await self._request(
            "POST",
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            MessageCreatedData,
            trace_id=trace_id,
            identity=identity,
            json={
                "external_message_id": external_message_id,
                "sender_type": sender_type,
                "content": content,
                "message_data": message_data,
            },
        )

    async def list_conversations(
        self,
        identity: BackendIdentity,
        trace_id: str,
        *,
        page: int = 1,
        page_size: int = 30,
    ) -> ConversationListData:
        return await self._request(
            "GET",
            "/api/v1/agent/conversations",
            ConversationListData,
            trace_id=trace_id,
            identity=identity,
            params={"page": page, "page_size": page_size},
            retryable=True,
        )

    async def list_conversation_messages(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        trace_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> MessageListData:
        return await self._request(
            "GET",
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            MessageListData,
            trace_id=trace_id,
            identity=identity,
            params={"page": page, "page_size": page_size},
            retryable=True,
        )

    async def get_conversation_state(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        trace_id: str,
    ) -> ConversationStateData:
        return await self._request(
            "GET",
            f"/api/v1/agent/conversations/{conversation_id}/state",
            ConversationStateData,
            trace_id=trace_id,
            identity=identity,
            retryable=True,
        )

    async def save_conversation_state(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        state: ConversationStatePayload,
        trace_id: str,
    ) -> StateSavedData:
        return await self._request(
            "PUT",
            f"/api/v1/agent/conversations/{conversation_id}/state",
            StateSavedData,
            trace_id=trace_id,
            identity=identity,
            json=state.model_dump(mode="json"),
        )

    async def save_conversation_snapshot(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        *,
        snapshot_reason: str,
        trace_id: str,
    ) -> SnapshotSavedData:
        return await self._request(
            "POST",
            f"/api/v1/agent/conversations/{conversation_id}/snapshot",
            SnapshotSavedData,
            trace_id=trace_id,
            identity=identity,
            json={"snapshot_reason": snapshot_reason},
        )

    async def complete_conversation(
        self,
        identity: BackendIdentity,
        conversation_id: int,
        trace_id: str,
        *,
        purchase_request_id: int | None = None,
    ) -> ConversationCompletedData:
        return await self._request(
            "POST",
            f"/api/v1/agent/conversations/{conversation_id}/complete",
            ConversationCompletedData,
            trace_id=trace_id,
            identity=identity,
            json={"purchase_request_id": purchase_request_id},
        )

    async def execute_confirmed_action(
        self,
        identity: BackendIdentity,
        *,
        action_type: str,
        action_id: str,
        draft: dict,
        trace_id: str,
    ) -> RequirementMutationData:
        """Execute an allow-listed business action through the procurement API."""
        if action_type == "CREATE_PURCHASE_DRAFT":
            created = await self._request(
                "POST",
                "/api/v1/requirements",
                RequirementMutationData,
                trace_id=trace_id,
                identity=identity,
                json={"building_id": int(draft["building_id"])},
            )
            fields = {
                key: draft.get(key)
                for key in (
                    "device_profession",
                    "device_name",
                    "brand",
                    "model",
                    "quantity",
                    "unit",
                    "application_reason",
                    "applicant_remark",
                )
                if draft.get(key) not in (None, "")
            }
            saved = await self._request(
                "PATCH",
                f"/api/v1/requirements/{created.requirement_id}/applicant-fields",
                FieldsSaveData,
                trace_id=trace_id,
                identity=identity,
                json={"expected_version": created.version, "fields": fields},
            )
            return RequirementMutationData(
                requirement_id=saved.requirement_id,
                requirement_no=created.requirement_no,
                status=saved.status,
                version=saved.version,
                current_handler=created.current_handler,
            )
        requirement_id = int(draft["requirement_id"])
        expected_version = int(draft["expected_version"])
        action_token = f"AGENT-{action_id}"[:64]
        path = f"/api/v1/requirements/{requirement_id}"
        method = "POST"
        body: dict = {
            "expected_version": expected_version,
            "action_token": action_token,
        }
        if action_type == "SUBMIT_PURCHASE_REQUEST":
            path += "/submit-review"
            body["assigned_to_employee_id"] = int(draft["assigned_to_employee_id"])
        elif action_type == "APPROVE_PURCHASE_REQUEST":
            path += "/submit-purchaser"
            body["assigned_to_employee_id"] = int(draft["assigned_to_employee_id"])
        elif action_type == "REJECT_PURCHASE_REQUEST":
            path += "/reject"
            body["reason"] = str(draft["reason"])
        elif action_type in {"SELECT_FINAL_SUPPLIER", "WRITE_PURCHASE_RESULT"}:
            method = "PATCH"
            path += "/purchase-fields"
            body = {"expected_version": expected_version, "fields": draft["fields"]}
        elif action_type == "SUBMIT_WAREHOUSE":
            path += "/submit-warehouse"
            body["assigned_to_employee_id"] = int(draft["assigned_to_employee_id"])
        elif action_type == "RECORD_WAREHOUSE":
            method = "PATCH"
            path += "/warehouse-fields"
            body = {"expected_version": expected_version, "fields": draft["fields"]}
        elif action_type == "COMPLETE_PURCHASE":
            path += "/complete"
        else:
            raise ValueError(f"Unsupported confirmed action: {action_type}")
        return await self._request(
            method,
            path,
            RequirementMutationData,
            trace_id=trace_id,
            identity=identity,
            json=body,
        )

    async def _request(
        self,
        method: str,
        path: str,
        response_model: type[ModelT],
        *,
        trace_id: str,
        identity: BackendIdentity | None,
        retryable: bool = False,
        **kwargs,
    ) -> ModelT:
        headers = {"X-Request-Id": trace_id}
        if identity is not None:
            headers = self.signer.signed_headers(method, path, identity, trace_id)

        attempts = 1 + (self.settings.procurement_backend_max_retries if retryable else 0)
        for attempt in range(attempts):
            try:
                response = await self.http_client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await self._retry_delay()
                    continue
                raise ProcurementBackendTimeout() from exc
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    await self._retry_delay()
                    continue
                raise ProcurementBackendUnavailable() from exc

            if response.status_code >= 500 and attempt + 1 < attempts:
                await self._retry_delay()
                continue
            return self._parse_response(response, response_model)

        raise ProcurementBackendUnavailable()

    async def _retry_delay(self) -> None:
        if self.settings.procurement_backend_retry_delay_seconds:
            await asyncio.sleep(self.settings.procurement_backend_retry_delay_seconds)

    @staticmethod
    def _parse_response(response: httpx.Response, response_model: type[ModelT]) -> ModelT:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProcurementBackendProtocolError() from exc
        if not isinstance(payload, dict):
            raise ProcurementBackendProtocolError()

        if response.is_error or payload.get("success") is False:
            backend_data = payload.get("data")
            details = (
                backend_data
                if isinstance(backend_data, dict)
                else {"backend_data": backend_data}
                if backend_data is not None
                else None
            )
            raise ProcurementBackendError(
                str(payload.get("code") or "PROCUREMENT_BACKEND_ERROR"),
                str(payload.get("message") or "采购后端请求失败"),
                response.status_code,
                backend_trace_id=payload.get("trace_id"),
                details=details,
            )

        try:
            return response_model.model_validate(payload.get("data"))
        except ValidationError as exc:
            raise ProcurementBackendProtocolError() from exc
