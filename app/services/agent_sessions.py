from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.domain.enums import RoleCode
from app.domain.identity import CurrentUser
from app.integrations.agent_state_store import AgentStateStore
from app.models.agent import AgentConversation, AgentMessage, AgentSessionState
from app.repositories.agent_sessions import AgentSessionRepository
from app.repositories.procurement import ProcurementRepository
from app.schemas.agent_sessions import (
    ActiveConversationData,
    ActiveConversationRequest,
    CompleteConversationRequest,
    ConversationCompletedData,
    ConversationData,
    ConversationListData,
    ConversationStateData,
    ConversationStatePayload,
    CreateMessageRequest,
    MessageCreatedData,
    MessageData,
    MessageListData,
    SnapshotSavedData,
    StateSavedData,
)


class AgentSessionService:
    def __init__(
        self,
        repository: AgentSessionRepository | None = None,
        state_store: AgentStateStore | None = None,
        procurement_repository: ProcurementRepository | None = None,
    ) -> None:
        self.repository = repository or AgentSessionRepository()
        self.state_store = state_store or AgentStateStore()
        self.procurement = procurement_repository or ProcurementRepository()
        self.settings = get_settings()

    async def get_or_create_active(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        payload: ActiveConversationRequest,
    ) -> ActiveConversationData:
        await self.repository.lock_employee(session, current_user.employee_id)
        conversation = None
        if payload.external_conversation_id:
            conversation = await self.repository.get_active_by_external_id(
                session,
                current_user.employee_id,
                payload.external_conversation_id,
            )
        else:
            conversation = await self.repository.get_active_by_action(
                session,
                current_user.employee_id,
                payload.current_action,
            )
        if conversation is None:
            now = datetime.now().replace(microsecond=0)
            conversation = AgentConversation(
                employee_id=current_user.employee_id,
                platform_type=current_user.platform_type,
                external_conversation_id=payload.external_conversation_id,
                purchase_request_id=None,
                status="ACTIVE",
                started_at=now,
                last_active_at=now,
            )
            session.add(conversation)
            await session.flush()
            initial_state = ConversationStatePayload(
                current_action=payload.current_action,
            )
            snapshot = AgentSessionState(
                conversation_id=conversation.conversation_id,
                current_action=payload.current_action,
                state_data=self._snapshot_state_data(initial_state, "SESSION_CREATED"),
                missing_fields=[],
                confirmed=False,
                saved_at=now,
            )
            session.add(snapshot)
            await session.flush()
            await self.state_store.set(
                conversation.conversation_id,
                initial_state.model_dump(mode="json"),
            )
        else:
            conversation.last_active_at = datetime.now().replace(microsecond=0)
            state, _ = await self._get_or_restore_state(session, conversation)
            await self.state_store.set(
                conversation.conversation_id,
                state.model_dump(mode="json"),
            )

        return ActiveConversationData(
            conversation_id=conversation.conversation_id,
            status=conversation.status,
            purchase_request_id=conversation.purchase_request_id,
            redis_state_exists=True,
        )

    async def add_message(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        payload: CreateMessageRequest,
    ) -> MessageCreatedData:
        conversation = await self._owned_conversation(
            session,
            current_user,
            conversation_id,
            for_update=True,
        )
        self._require_active(conversation)
        if payload.external_message_id:
            existing = await self.repository.get_message_by_external_id(
                session,
                conversation_id,
                payload.external_message_id,
            )
            if existing is not None:
                return MessageCreatedData(
                    message_id=existing.message_id,
                    created_at=existing.created_at,
                    duplicate=True,
                )

        now = datetime.now().replace(microsecond=0)
        message = AgentMessage(
            conversation_id=conversation_id,
            external_message_id=payload.external_message_id,
            sender_type=payload.sender_type,
            content=payload.content,
            message_data=payload.message_data,
            created_at=now,
        )
        session.add(message)
        conversation.last_active_at = now
        await session.flush()
        return MessageCreatedData(
            message_id=message.message_id,
            created_at=message.created_at,
        )

    async def list_messages(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        page: int,
        page_size: int,
    ) -> MessageListData:
        await self._owned_conversation(
            session,
            current_user,
            conversation_id,
        )
        messages, total = await self.repository.list_messages(
            session,
            conversation_id,
            page,
            page_size,
        )
        return MessageListData(
            items=[
                MessageData(
                    message_id=message.message_id,
                    external_message_id=message.external_message_id,
                    sender_type=message.sender_type,
                    content=message.content,
                    message_data=message.message_data,
                    created_at=message.created_at,
                )
                for message in messages
            ],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def list_conversations(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        page: int,
        page_size: int,
    ) -> ConversationListData:
        rows, total = await self.repository.list_conversations(
            session, current_user.employee_id, page, page_size
        )
        items: list[ConversationData] = []
        for conversation in rows:
            first_message = await self.repository.first_user_message(
                session, conversation.conversation_id
            )
            title = first_message.content.strip()[:30] if first_message else "新会话"
            items.append(
                ConversationData(
                    conversation_id=conversation.conversation_id,
                    external_conversation_id=conversation.external_conversation_id,
                    status=conversation.status,
                    title=title or "新会话",
                    message_count=await self.repository.message_count(
                        session, conversation.conversation_id
                    ),
                    started_at=conversation.started_at,
                    last_active_at=conversation.last_active_at,
                )
            )
        return ConversationListData(items=items, page=page, page_size=page_size, total=total)

    async def get_state(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
    ) -> ConversationStateData:
        conversation = await self._owned_conversation(
            session,
            current_user,
            conversation_id,
        )
        self._require_active(conversation)
        state, restored = await self._get_or_restore_state(session, conversation)
        conversation.last_active_at = datetime.now().replace(microsecond=0)
        return ConversationStateData(
            conversation_id=conversation_id,
            restored_from_snapshot=restored,
            **state.model_dump(),
        )

    async def save_state(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        state: ConversationStatePayload,
    ) -> StateSavedData:
        conversation = await self._owned_conversation(
            session,
            current_user,
            conversation_id,
            for_update=True,
        )
        self._require_active(conversation)
        await self._validate_request_access(
            session,
            current_user,
            state.purchase_request_id,
        )
        conversation.purchase_request_id = state.purchase_request_id
        conversation.last_active_at = datetime.now().replace(microsecond=0)
        await self.state_store.set(
            conversation_id,
            state.model_dump(mode="json"),
        )
        return StateSavedData(
            expires_in_seconds=self.settings.agent_session_ttl_seconds,
        )

    async def save_snapshot(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        snapshot_reason: str,
    ) -> SnapshotSavedData:
        conversation = await self._owned_conversation(
            session,
            current_user,
            conversation_id,
            for_update=True,
        )
        self._require_active(conversation)
        state, _ = await self._get_or_restore_state(session, conversation)
        snapshot = await self._persist_snapshot(
            session,
            conversation,
            state,
            snapshot_reason,
        )
        return SnapshotSavedData(
            state_id=snapshot.state_id,
            saved_at=snapshot.saved_at,
        )

    async def complete(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        payload: CompleteConversationRequest,
    ) -> ConversationCompletedData:
        conversation = await self._owned_conversation(
            session,
            current_user,
            conversation_id,
            for_update=True,
        )
        self._require_active(conversation)
        state, _ = await self._get_or_restore_state(session, conversation)
        if payload.purchase_request_id is not None:
            await self._validate_request_access(
                session,
                current_user,
                payload.purchase_request_id,
            )
            state.purchase_request_id = payload.purchase_request_id
        conversation.purchase_request_id = state.purchase_request_id
        await self._persist_snapshot(
            session,
            conversation,
            state,
            "SESSION_COMPLETED",
        )
        conversation.status = "COMPLETED"
        conversation.last_active_at = datetime.now().replace(microsecond=0)
        redis_state_deleted = await self.state_store.delete(conversation_id)
        return ConversationCompletedData(
            conversation_id=conversation_id,
            status=conversation.status,
            redis_state_deleted=redis_state_deleted,
        )

    async def _owned_conversation(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        conversation_id: int,
        *,
        for_update: bool = False,
    ) -> AgentConversation:
        conversation = await self.repository.get_conversation(
            session,
            conversation_id,
            for_update=for_update,
        )
        if conversation is None:
            raise AppError("SESSION_NOT_FOUND", "Agent 会话不存在", 404)
        if conversation.employee_id != current_user.employee_id:
            raise AppError("PERMISSION_DENIED", "无权访问该 Agent 会话", 403)
        return conversation

    async def _get_or_restore_state(
        self,
        session: AsyncSession,
        conversation: AgentConversation,
    ) -> tuple[ConversationStatePayload, bool]:
        cached = await self.state_store.get(conversation.conversation_id)
        if cached is not None:
            return ConversationStatePayload.model_validate(cached), False
        snapshot = await self.repository.get_snapshot(
            session,
            conversation.conversation_id,
        )
        if snapshot is None:
            raise AppError(
                "SESSION_EXPIRED",
                "Redis 会话状态已过期且无法从 MySQL 快照恢复",
                410,
            )
        state_data = snapshot.state_data or {}
        collected_data = state_data.get("collected_data")
        if collected_data is None:
            metadata_keys = {
                "pending_field",
                "awaiting_confirmation",
                "recent_messages",
                "last_recommendations",
                "snapshot_reason",
            }
            collected_data = {
                key: value for key, value in state_data.items() if key not in metadata_keys
            }
        state = ConversationStatePayload(
            purchase_request_id=conversation.purchase_request_id,
            current_action=snapshot.current_action,
            collected_data=collected_data,
            missing_fields=snapshot.missing_fields or [],
            pending_field=state_data.get("pending_field"),
            awaiting_confirmation=state_data.get("awaiting_confirmation", False),
            recent_messages=state_data.get("recent_messages", []),
            last_recommendations=state_data.get("last_recommendations", []),
        )
        await self.state_store.set(
            conversation.conversation_id,
            state.model_dump(mode="json"),
        )
        return state, True

    async def _persist_snapshot(
        self,
        session: AsyncSession,
        conversation: AgentConversation,
        state: ConversationStatePayload,
        snapshot_reason: str,
    ) -> AgentSessionState:
        snapshot = await self.repository.get_snapshot(
            session,
            conversation.conversation_id,
        )
        now = datetime.now().replace(microsecond=0)
        if snapshot is None:
            snapshot = AgentSessionState(conversation_id=conversation.conversation_id)
            session.add(snapshot)
        snapshot.current_action = state.current_action
        snapshot.state_data = self._snapshot_state_data(state, snapshot_reason)
        snapshot.missing_fields = state.missing_fields
        snapshot.confirmed = snapshot_reason in {"USER_CONFIRMED", "HITL_EXECUTED"}
        snapshot.saved_at = now
        conversation.purchase_request_id = state.purchase_request_id
        conversation.last_active_at = now
        await session.flush()
        return snapshot

    @staticmethod
    def _snapshot_state_data(
        state: ConversationStatePayload,
        snapshot_reason: str,
    ) -> dict:
        return {
            "collected_data": state.collected_data,
            "pending_field": state.pending_field,
            "awaiting_confirmation": state.awaiting_confirmation,
            "recent_messages": state.recent_messages,
            "last_recommendations": state.last_recommendations,
            "snapshot_reason": snapshot_reason,
        }

    async def _validate_request_access(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        request_id: int | None,
    ) -> None:
        if request_id is None:
            return
        request = await self.procurement.get_request(session, request_id)
        if request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)
        visible = await self.procurement.can_view_request(
            session,
            request,
            current_user.employee_id,
            current_user.has_any_role(RoleCode.ADMIN.value),
            current_user.building_ids,
            current_user.has_any_role(RoleCode.BUILDING_MANAGER.value),
        )
        if not visible:
            raise AppError("PERMISSION_DENIED", "无权关联该采购申请", 403)

    @staticmethod
    def _require_active(conversation: AgentConversation) -> None:
        if conversation.status != "ACTIVE":
            raise AppError("INVALID_SESSION_STATUS", "当前 Agent 会话不是活动状态", 409)
