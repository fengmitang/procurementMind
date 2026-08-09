import asyncio
from uuid import uuid4

from fastapi import APIRouter, Request

from agent_app.api.dependencies import (
    ProcurementBackendClientDependency,
    ProcurementGraphServiceDependency,
)
from agent_app.core.exceptions import AgentError
from agent_app.core.request_context import trace_id_context
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.schemas import GraphRunRequest
from agent_app.observability import build_execution_details
from agent_app.schemas.backend import BackendIdentity
from agent_app.schemas.chat import ChatData, ChatRequest
from agent_app.schemas.common import AgentApiResponse

router = APIRouter(prefix="/chat", tags=["agent-chat"])


@router.post("", response_model=AgentApiResponse[ChatData])
async def chat(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClientDependency,
    graph_service: ProcurementGraphServiceDependency,
) -> AgentApiResponse[ChatData]:
    settings = request.app.state.agent_settings
    if settings.agent_app_env.lower() != "development":
        raise AgentError(
            "IDENTITY_SESSION_REQUIRED",
            "当前环境必须通过服务端登录会话提供身份",
            401,
        )
    if payload.platform_type != "TEST_PLATFORM":
        raise AgentError(
            "DEVELOPMENT_IDENTITY_REQUIRED",
            "开发环境聊天接口只允许 TEST_PLATFORM 身份",
            403,
        )
    trace_id = trace_id_context.get() or str(uuid4())
    task_id = uuid4()
    identity = BackendIdentity(
        platform_type=payload.platform_type,
        platform_user_id=payload.platform_user_id,
    )

    current_user = await client.get_current_user(identity, trace_id)
    conversation = await client.get_or_create_active_conversation(
        identity,
        current_action="CHAT",
        trace_id=trace_id,
        external_conversation_id=payload.external_conversation_id,
    )
    await client.add_conversation_message(
        identity,
        conversation.conversation_id,
        sender_type="USER",
        content=payload.message,
        external_message_id=payload.external_message_id or f"user:{task_id}",
        trace_id=trace_id,
    )
    restored_state = await client.get_conversation_state(
        identity,
        conversation.conversation_id,
        trace_id,
    )
    graph_request = GraphRunRequest(
        task_id=task_id,
        trace_id=trace_id,
        conversation_id=conversation.conversation_id,
        identity=identity,
        current_user=current_user,
        message=payload.message,
        restored_state=restored_state,
    )
    try:
        async with asyncio.timeout(settings.task_timeout_seconds):
            graph_result = await graph_service.run(graph_request)
    except TimeoutError as exc:
        raise AgentError(
            "AGENT_TASK_TIMEOUT",
            "Agent 任务达到总执行时限，本次未生成结论",
            504,
        ) from exc
    reply = graph_result.reply
    await client.add_conversation_message(
        identity,
        conversation.conversation_id,
        sender_type="AGENT",
        content=reply,
        external_message_id=f"agent:{task_id}",
        trace_id=trace_id,
    )
    backend_state = GraphMemoryMapper.to_backend_state(graph_request, graph_result)
    await client.save_conversation_state(
        identity,
        conversation.conversation_id,
        backend_state,
        trace_id,
    )
    await client.save_conversation_snapshot(
        identity,
        conversation.conversation_id,
        snapshot_reason="GRAPH_RUN_COMPLETED",
        trace_id=trace_id,
    )
    return AgentApiResponse(
        message="回答已生成",
        data=ChatData(
            task_id=task_id,
            conversation_id=conversation.conversation_id,
            reply=reply,
            route=graph_result.route.value,
            restored_from_snapshot=graph_result.restored_from_snapshot,
            tool_call_count=graph_result.tool_call_count,
            evidence_count=len(graph_result.evidence),
            execution=build_execution_details(
                graph_result,
                model_configured=settings.model_configured,
                model_provider=settings.model_provider,
                model_name=settings.primary_model,
            ),
            analysis=graph_result.analysis,
            risk_investigation=graph_result.risk_investigation,
            knowledge=graph_result.knowledge,
            review=graph_result.review,
            evidence_sufficient=graph_result.evidence_sufficient,
            pending_action=graph_result.pending_action,
        ),
    )
