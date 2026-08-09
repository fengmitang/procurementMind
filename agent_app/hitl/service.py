import asyncio
import secrets
from collections import defaultdict
from datetime import UTC, datetime

from pydantic import ValidationError

from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.exceptions import AgentError
from agent_app.graph.schemas import HITLActionType, PendingAction
from agent_app.hitl.schemas import (
    ActionResolutionData,
    ActionResolutionStatus,
    ResolvedAction,
)
from agent_app.schemas.backend import BackendIdentity, ConversationStatePayload


class HITLService:
    """Resolve identity-bound, expiring, one-time business confirmations."""

    def __init__(self, backend: ProcurementBackendClient) -> None:
        self.backend = backend
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def confirm(
        self,
        identity: BackendIdentity,
        *,
        conversation_id: int,
        action_id: str,
        confirmation_token: str,
        trace_id: str,
    ) -> ActionResolutionData:
        async with self._locks[self._lock_key(identity, conversation_id)]:
            state = await self.backend.get_conversation_state(identity, conversation_id, trace_id)
            pending, resolved = self._load_action(state.collected_data, action_id)
            if resolved is not None:
                return self._repeat_result(resolved)
            self._validate_token(pending, confirmation_token)
            if pending.expires_at <= datetime.now(UTC):
                return await self._resolve(
                    identity,
                    state,
                    pending,
                    ActionResolutionStatus.EXPIRED,
                    trace_id,
                )
            self._validate_draft(pending)
            result = await self.backend.execute_confirmed_action(
                identity,
                action_type=pending.action_type.value,
                action_id=pending.action_id,
                draft=pending.draft,
                trace_id=trace_id,
            )
            return await self._resolve(
                identity,
                state,
                pending,
                ActionResolutionStatus.EXECUTED,
                trace_id,
                result=result.model_dump(mode="json"),
            )

    async def cancel(
        self,
        identity: BackendIdentity,
        *,
        conversation_id: int,
        action_id: str,
        confirmation_token: str,
        trace_id: str,
    ) -> ActionResolutionData:
        async with self._locks[self._lock_key(identity, conversation_id)]:
            state = await self.backend.get_conversation_state(identity, conversation_id, trace_id)
            pending, resolved = self._load_action(state.collected_data, action_id)
            if resolved is not None:
                return self._repeat_result(resolved)
            self._validate_token(pending, confirmation_token)
            status = (
                ActionResolutionStatus.EXPIRED
                if pending.expires_at <= datetime.now(UTC)
                else ActionResolutionStatus.CANCELED
            )
            return await self._resolve(identity, state, pending, status, trace_id)

    @staticmethod
    def _lock_key(identity: BackendIdentity, conversation_id: int) -> str:
        return f"{identity.platform_type}:{identity.platform_user_id}:{conversation_id}"

    @staticmethod
    def _load_action(
        collected_data: dict,
        action_id: str,
    ) -> tuple[PendingAction, None] | tuple[None, ResolvedAction]:
        raw_pending = collected_data.get("pending_action")
        if isinstance(raw_pending, dict):
            try:
                pending = PendingAction.model_validate(raw_pending)
            except ValidationError as exc:
                raise AgentError("HITL_STATE_INVALID", "待确认动作状态无效", 409) from exc
            if pending.action_id != action_id:
                raise AgentError("HITL_ACTION_NOT_FOUND", "待确认动作不存在或已被替换", 404)
            return pending, None
        raw_resolved = collected_data.get("last_resolved_action")
        if isinstance(raw_resolved, dict):
            try:
                resolved = ResolvedAction.model_validate(raw_resolved)
            except ValidationError:
                resolved = None
            if resolved is not None and resolved.action_id == action_id:
                return None, resolved
        raise AgentError("HITL_ACTION_NOT_FOUND", "待确认动作不存在或已处理", 404)

    @staticmethod
    def _validate_token(pending: PendingAction, confirmation_token: str) -> None:
        if not secrets.compare_digest(pending.confirmation_token, confirmation_token):
            raise AgentError("HITL_TOKEN_INVALID", "确认凭证无效", 403)

    @staticmethod
    def _validate_draft(pending: PendingAction) -> None:
        draft = pending.draft
        try:
            requirement_id = int(draft["requirement_id"])
            expected_version = int(draft["expected_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentError("HITL_DRAFT_INCOMPLETE", "操作草稿缺少采购单或版本信息", 409) from exc
        if requirement_id <= 0 or expected_version < 0:
            raise AgentError("HITL_DRAFT_INVALID", "操作草稿中的采购单或版本无效", 422)
        assigned = {
            HITLActionType.SUBMIT_PURCHASE_REQUEST,
            HITLActionType.APPROVE_PURCHASE_REQUEST,
            HITLActionType.SUBMIT_WAREHOUSE,
        }
        if pending.action_type in assigned and not isinstance(
            draft.get("assigned_to_employee_id"), int
        ):
            raise AgentError("HITL_DRAFT_INCOMPLETE", "操作草稿缺少下一处理人", 409)
        if (
            pending.action_type is HITLActionType.REJECT_PURCHASE_REQUEST
            and not str(draft.get("reason", "")).strip()
        ):
            raise AgentError("HITL_DRAFT_INCOMPLETE", "驳回草稿缺少原因", 409)
        fields_actions = {
            HITLActionType.SELECT_FINAL_SUPPLIER,
            HITLActionType.WRITE_PURCHASE_RESULT,
            HITLActionType.RECORD_WAREHOUSE,
        }
        if pending.action_type in fields_actions and not isinstance(draft.get("fields"), dict):
            raise AgentError("HITL_DRAFT_INCOMPLETE", "操作草稿缺少受控字段", 409)

    async def _resolve(
        self,
        identity: BackendIdentity,
        state,
        pending: PendingAction,
        status: ActionResolutionStatus,
        trace_id: str,
        *,
        result: dict | None = None,
    ) -> ActionResolutionData:
        resolution = ResolvedAction(
            action_id=pending.action_id,
            action_type=pending.action_type.value,
            status=status,
            resolved_at=datetime.now(UTC),
            result=result,
        )
        collected_data = dict(state.collected_data)
        collected_data.pop("pending_action", None)
        collected_data["last_resolved_action"] = resolution.model_dump(mode="json")
        await self.backend.save_conversation_state(
            identity,
            state.conversation_id,
            ConversationStatePayload(
                purchase_request_id=state.purchase_request_id,
                current_action="CHAT",
                collected_data=collected_data,
                missing_fields=state.missing_fields,
                pending_field=state.pending_field,
                awaiting_confirmation=False,
                recent_messages=state.recent_messages,
                last_recommendations=state.last_recommendations,
            ),
            trace_id,
        )
        await self.backend.save_conversation_snapshot(
            identity,
            state.conversation_id,
            snapshot_reason=f"HITL_{status.value}",
            trace_id=trace_id,
        )
        return ActionResolutionData.model_validate(resolution.model_dump(mode="json"))

    @staticmethod
    def _repeat_result(resolved: ResolvedAction) -> ActionResolutionData:
        repeated = {
            ActionResolutionStatus.EXECUTED: ActionResolutionStatus.ALREADY_EXECUTED,
            ActionResolutionStatus.CANCELED: ActionResolutionStatus.ALREADY_CANCELED,
            ActionResolutionStatus.EXPIRED: ActionResolutionStatus.ALREADY_EXPIRED,
        }.get(resolved.status, resolved.status)
        return ActionResolutionData(
            action_id=resolved.action_id,
            action_type=resolved.action_type,
            status=repeated,
            resolved_at=resolved.resolved_at,
            result=resolved.result,
        )
