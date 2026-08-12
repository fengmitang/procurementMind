from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUserDependency, DbSession
from app.core.responses import ApiResponse
from app.schemas.agent_sessions import (
    ActiveConversationData,
    ActiveConversationRequest,
    CompleteConversationRequest,
    ConversationCompletedData,
    ConversationListData,
    ConversationStateData,
    ConversationStatePayload,
    CreateMessageRequest,
    MessageCreatedData,
    MessageListData,
    SaveSnapshotRequest,
    SnapshotSavedData,
    StateSavedData,
)
from app.services.agent_sessions import AgentSessionService

router = APIRouter(prefix="/api/v1/agent/conversations", tags=["agent-support"])


@router.get("", response_model=ApiResponse[ConversationListData])
async def list_conversations(
    current_user: CurrentUserDependency,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> ApiResponse[ConversationListData]:
    data = await AgentSessionService().list_conversations(session, current_user, page, page_size)
    return ApiResponse(data=data)


@router.post("/active", response_model=ApiResponse[ActiveConversationData])
async def get_or_create_active_conversation(
    payload: ActiveConversationRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[ActiveConversationData]:
    data = await AgentSessionService().get_or_create_active(
        session,
        current_user,
        payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/{conversation_id}/messages",
    response_model=ApiResponse[MessageCreatedData],
)
async def create_conversation_message(
    conversation_id: int,
    payload: CreateMessageRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[MessageCreatedData]:
    data = await AgentSessionService().add_message(
        session,
        current_user,
        conversation_id,
        payload,
    )
    return ApiResponse(data=data)


@router.get(
    "/{conversation_id}/messages",
    response_model=ApiResponse[MessageListData],
)
async def list_conversation_messages(
    conversation_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[MessageListData]:
    data = await AgentSessionService().list_messages(
        session,
        current_user,
        conversation_id,
        page,
        page_size,
    )
    return ApiResponse(data=data)


@router.get(
    "/{conversation_id}/state",
    response_model=ApiResponse[ConversationStateData],
)
async def get_conversation_state(
    conversation_id: int,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[ConversationStateData]:
    data = await AgentSessionService().get_state(
        session,
        current_user,
        conversation_id,
    )
    return ApiResponse(data=data)


@router.put(
    "/{conversation_id}/state",
    response_model=ApiResponse[StateSavedData],
)
async def save_conversation_state(
    conversation_id: int,
    payload: ConversationStatePayload,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[StateSavedData]:
    data = await AgentSessionService().save_state(
        session,
        current_user,
        conversation_id,
        payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/{conversation_id}/snapshot",
    response_model=ApiResponse[SnapshotSavedData],
)
async def save_conversation_snapshot(
    conversation_id: int,
    payload: SaveSnapshotRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[SnapshotSavedData]:
    data = await AgentSessionService().save_snapshot(
        session,
        current_user,
        conversation_id,
        payload.snapshot_reason,
    )
    return ApiResponse(data=data)


@router.post(
    "/{conversation_id}/complete",
    response_model=ApiResponse[ConversationCompletedData],
)
async def complete_conversation(
    conversation_id: int,
    payload: CompleteConversationRequest,
    current_user: CurrentUserDependency,
    session: DbSession,
) -> ApiResponse[ConversationCompletedData]:
    data = await AgentSessionService().complete(
        session,
        current_user,
        conversation_id,
        payload,
    )
    return ApiResponse(data=data)
