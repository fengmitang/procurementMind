from uuid import uuid4

from fastapi import APIRouter, Request

from agent_app.api.dependencies import HITLServiceDependency
from agent_app.core.exceptions import AgentError
from agent_app.core.request_context import trace_id_context
from agent_app.hitl.schemas import ActionDecisionRequest, ActionResolutionData
from agent_app.schemas.backend import BackendIdentity
from agent_app.schemas.common import AgentApiResponse

router = APIRouter(prefix="/chat/actions", tags=["agent-hitl"])


def _identity(payload: ActionDecisionRequest, request: Request) -> BackendIdentity:
    settings = request.app.state.agent_settings
    if settings.agent_app_env.lower() != "development":
        raise AgentError("IDENTITY_SESSION_REQUIRED", "当前环境必须通过服务端登录会话提供身份", 401)
    if payload.platform_type != "TEST_PLATFORM":
        raise AgentError(
            "DEVELOPMENT_IDENTITY_REQUIRED",
            "开发环境确认接口只允许 TEST_PLATFORM 身份",
            403,
        )
    return BackendIdentity(
        platform_type=payload.platform_type,
        platform_user_id=payload.platform_user_id,
    )


@router.post("/confirm", response_model=AgentApiResponse[ActionResolutionData])
async def confirm_action(
    payload: ActionDecisionRequest,
    request: Request,
    service: HITLServiceDependency,
) -> AgentApiResponse[ActionResolutionData]:
    result = await service.confirm(
        _identity(payload, request),
        conversation_id=payload.conversation_id,
        action_id=payload.action_id,
        confirmation_token=payload.confirmation_token,
        trace_id=trace_id_context.get() or str(uuid4()),
    )
    return AgentApiResponse(message="确认动作已处理", data=result)


@router.post("/cancel", response_model=AgentApiResponse[ActionResolutionData])
async def cancel_action(
    payload: ActionDecisionRequest,
    request: Request,
    service: HITLServiceDependency,
) -> AgentApiResponse[ActionResolutionData]:
    result = await service.cancel(
        _identity(payload, request),
        conversation_id=payload.conversation_id,
        action_id=payload.action_id,
        confirmation_token=payload.confirmation_token,
        trace_id=trace_id_context.get() or str(uuid4()),
    )
    return AgentApiResponse(message="确认动作已取消", data=result)
