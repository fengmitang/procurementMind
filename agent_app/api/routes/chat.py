import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent_app.api.dependencies import (
    ProcurementBackendClientDependency,
    ProcurementGraphServiceDependency,
)
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.exceptions import AgentError
from agent_app.core.request_context import trace_id_context
from agent_app.graph.memory import GraphMemoryMapper
from agent_app.graph.schemas import GraphRunRequest, GraphRunResult
from agent_app.graph.service import GraphStreamHandler, ProcurementGraphService
from agent_app.observability import build_execution_details
from agent_app.schemas.backend import BackendIdentity
from agent_app.schemas.chat import ChatData, ChatRequest
from agent_app.schemas.common import AgentApiResponse

router = APIRouter(prefix="/chat", tags=["agent-chat"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedChat:
    identity: BackendIdentity
    conversation_id: int
    graph_request: GraphRunRequest


def _validate_development_identity(payload: ChatRequest, request: Request) -> None:
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


async def _prepare_chat(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClient,
) -> PreparedChat:
    _validate_development_identity(payload, request)
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
    return PreparedChat(
        identity=identity,
        conversation_id=conversation.conversation_id,
        graph_request=GraphRunRequest(
            task_id=task_id,
            trace_id=trace_id,
            conversation_id=conversation.conversation_id,
            identity=identity,
            current_user=current_user,
            message=payload.message,
            ui_context=payload.ui_context,
            restored_state=restored_state,
        ),
    )


async def _run_graph(
    request: Request,
    graph_service: ProcurementGraphService,
    graph_request: GraphRunRequest,
    stream_handler: GraphStreamHandler | None = None,
) -> GraphRunResult:
    try:
        async with asyncio.timeout(request.app.state.agent_settings.task_timeout_seconds):
            if stream_handler is None:
                return await graph_service.run(graph_request)
            return await graph_service.run(
                graph_request,
                stream_handler=stream_handler,
            )
    except TimeoutError as exc:
        raise AgentError(
            "AGENT_TASK_TIMEOUT",
            "本次分析超过执行时限，未生成结论，请缩小问题范围后重试",
            504,
        ) from exc


def _build_chat_data(request: Request, result: GraphRunResult) -> ChatData:
    settings = request.app.state.agent_settings
    return ChatData(
        task_id=result.task_id,
        conversation_id=result.conversation_id,
        reply=result.reply,
        route=result.route.value,
        restored_from_snapshot=result.restored_from_snapshot,
        tool_call_count=result.tool_call_count,
        evidence_count=len(result.evidence),
        execution=build_execution_details(
            result,
            model_configured=settings.model_configured,
            model_provider=settings.model_provider,
            model_name=settings.primary_model,
        ),
        analysis=result.analysis,
        risk_investigation=result.risk_investigation,
        knowledge=result.knowledge,
        review=result.review,
        evidence_sufficient=result.evidence_sufficient,
        pending_action=result.pending_action,
    )


async def _persist_result(
    prepared: PreparedChat,
    result: GraphRunResult,
    client: ProcurementBackendClient,
) -> None:
    graph_request = prepared.graph_request
    logger.info(
        "agent_graph_completed trace_id=%s conversation_id=%s route=%s path=%s tools=%s "
        "evidence_count=%s errors=%s",
        graph_request.trace_id,
        prepared.conversation_id,
        result.route.value,
        [f"{item.name}:{item.status}" for item in result.trace_events],
        [item.name for item in result.tool_results],
        len(result.evidence),
        [item.code for item in result.errors],
    )
    await client.add_conversation_message(
        prepared.identity,
        prepared.conversation_id,
        sender_type="AGENT",
        content=result.reply,
        external_message_id=f"agent:{graph_request.task_id}",
        trace_id=graph_request.trace_id,
    )
    backend_state = GraphMemoryMapper.to_backend_state(graph_request, result)
    await client.save_conversation_state(
        prepared.identity,
        prepared.conversation_id,
        backend_state,
        graph_request.trace_id,
    )
    await client.save_conversation_snapshot(
        prepared.identity,
        prepared.conversation_id,
        snapshot_reason="GRAPH_RUN_COMPLETED",
        trace_id=graph_request.trace_id,
    )


@router.post("", response_model=AgentApiResponse[ChatData])
async def chat(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClientDependency,
    graph_service: ProcurementGraphServiceDependency,
) -> AgentApiResponse[ChatData]:
    prepared = await _prepare_chat(payload, request, client)
    result = await _run_graph(request, graph_service, prepared.graph_request)
    await _persist_result(prepared, result, client)
    return AgentApiResponse(message="回答已生成", data=_build_chat_data(request, result))


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClientDependency,
    graph_service: ProcurementGraphServiceDependency,
) -> StreamingResponse:
    prepared = await _prepare_chat(payload, request, client)

    async def generate() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict[str, object]] | None] = asyncio.Queue()

        async def handle_graph_event(event: str, data: dict[str, object]) -> None:
            await queue.put((event, data))

        async def execute() -> None:
            try:
                result = await _run_graph(
                    request,
                    graph_service,
                    prepared.graph_request,
                    handle_graph_event,
                )
                await _persist_result(prepared, result, client)
                chat_data = _build_chat_data(request, result)
                for evidence in result.knowledge.evidences if result.knowledge else []:
                    await queue.put(
                        (
                            "citation",
                            evidence.citation.model_dump(mode="json"),
                        )
                    )
                if result.tool_results:
                    await queue.put(
                        (
                            "tool_summary",
                            {
                                "count": len(result.tool_results),
                                "items": [
                                    {"name": item.name, "success": item.success, "code": item.code}
                                    for item in result.tool_results
                                ],
                            },
                        )
                    )
                if result.pending_action is not None:
                    await queue.put(
                        (
                            "confirmation_required",
                            result.pending_action.model_dump(mode="json"),
                        )
                    )
                await queue.put(
                    (
                        "completed",
                        {
                            "success": True,
                            "code": "OK",
                            "message": "回答已生成",
                            "data": chat_data.model_dump(mode="json"),
                            "trace_id": prepared.graph_request.trace_id,
                        },
                    )
                )
            except AgentError as exc:
                await queue.put(
                    (
                        "error",
                        {
                            "code": exc.code,
                            "message": exc.message,
                            "trace_id": prepared.graph_request.trace_id,
                        },
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "agent_stream_failed trace_id=%s",
                    prepared.graph_request.trace_id,
                )
                await queue.put(
                    (
                        "error",
                        {
                            "code": "AGENT_STREAM_FAILED",
                            "message": "智能助手暂时无法完成本次回答，请稍后重试",
                            "trace_id": prepared.graph_request.trace_id,
                        },
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(execute())
        try:
            yield _sse(
                "conversation_started",
                {
                    "conversation_id": prepared.conversation_id,
                    "task_id": str(prepared.graph_request.task_id),
                    "trace_id": prepared.graph_request.trace_id,
                },
            )
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield _sse(event, data)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Trace-Id": prepared.graph_request.trace_id,
        },
    )
