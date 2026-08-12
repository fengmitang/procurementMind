import asyncio
import json
import logging
import time
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
from agent_app.schemas.chat import (
    BusinessResultData,
    ChatData,
    ChatRequest,
    KnowledgeSourceData,
)
from agent_app.schemas.common import AgentApiResponse

router = APIRouter(prefix="/chat", tags=["agent-chat"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedChat:
    identity: BackendIdentity
    conversation_id: int
    graph_request: GraphRunRequest
    timings: dict[str, int]


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


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
    prepare_started = time.perf_counter()
    timings: dict[str, int] = {}
    _validate_development_identity(payload, request)
    trace_id = trace_id_context.get() or str(uuid4())
    task_id = uuid4()
    identity = BackendIdentity(
        platform_type=payload.platform_type,
        platform_user_id=payload.platform_user_id,
    )
    call_started = time.perf_counter()
    current_user = await client.get_current_user(identity, trace_id)
    timings["prepare_identity_ms"] = _elapsed_ms(call_started)
    call_started = time.perf_counter()
    conversation = await client.get_or_create_active_conversation(
        identity,
        current_action="CHAT",
        trace_id=trace_id,
        external_conversation_id=payload.external_conversation_id,
    )
    timings["prepare_conversation_ms"] = _elapsed_ms(call_started)
    call_started = time.perf_counter()
    await client.add_conversation_message(
        identity,
        conversation.conversation_id,
        sender_type="USER",
        content=payload.message,
        external_message_id=payload.external_message_id or f"user:{task_id}",
        trace_id=trace_id,
    )
    timings["prepare_user_message_ms"] = _elapsed_ms(call_started)
    call_started = time.perf_counter()
    restored_state = await client.get_conversation_state(
        identity,
        conversation.conversation_id,
        trace_id,
    )
    timings["prepare_state_ms"] = _elapsed_ms(call_started)
    timings["prepare_total_ms"] = _elapsed_ms(prepare_started)
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
        timings=timings,
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


def _build_chat_data(
    request: Request,
    result: GraphRunResult,
    performance: dict[str, int] | None = None,
) -> ChatData:
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
        knowledge=None,
        knowledge_sources=_knowledge_sources(result),
        business_results=_business_results(result),
        form_draft=result.form_draft,
        form_missing_fields=result.form_missing_fields,
        review=result.review,
        evidence_sufficient=result.evidence_sufficient,
        pending_action=result.pending_action,
        performance=performance or {},
    )


def _knowledge_sources(result: GraphRunResult) -> list[KnowledgeSourceData]:
    if result.knowledge is None:
        return []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    sources: list[KnowledgeSourceData] = []
    for citation in result.knowledge.citations:
        key = (citation.document_title, tuple(citation.section_path))
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            KnowledgeSourceData(
                title=citation.document_title,
                section_path=list(citation.section_path),
            )
        )
    return sources


def _business_results(result: GraphRunResult) -> list[BusinessResultData]:
    rows = []
    total: int | None = None
    if result.analysis is not None and result.analysis.table is not None:
        rows = result.analysis.table.rows
        total = result.analysis.table.total
    else:
        search = next(
            (
                item
                for item in reversed(result.tool_results)
                if item.name == "search_purchase_records"
                and item.success
                and isinstance(item.data, dict)
            ),
            None,
        )
        if search is not None and isinstance(search.data, dict):
            value = search.data.get("items", [])
            rows = value if isinstance(value, list) else []
            total_value = search.data.get("total")
            total = int(total_value) if isinstance(total_value, int) else None
    if not rows:
        return []
    if all(isinstance(item, dict) and item.get("requirement_no") for item in rows):
        allowed = {
            "requirement_id",
            "requirement_no",
            "device_name",
            "brand",
            "model",
            "quantity",
            "unit",
            "status",
            "created_at",
            "current_handler_name",
            "supplier_name",
            "actual_total_price",
        }
        items = [{key: value for key, value in row.items() if key in allowed} for row in rows]
        return [
            BusinessResultData(
                kind="PURCHASE_REQUIREMENTS",
                title="采购申请",
                items=items,
                total=total,
            )
        ]
    if all(isinstance(item, dict) and item.get("supplier_name") for item in rows):
        allowed = {
            "supplier_id",
            "supplier_name",
            "historical_purchase_count",
            "last_purchase_at",
            "blacklist_status",
        }
        items = [{key: value for key, value in row.items() if key in allowed} for row in rows]
        return [
            BusinessResultData(
                kind="SUPPLIERS",
                title="供应商",
                items=items,
                total=total,
            )
        ]
    return []


def _persisted_message_data(result: GraphRunResult) -> dict:
    return {
        "conversation_id": result.conversation_id,
        "route": result.route.value,
        "tool_call_count": result.tool_call_count,
        "knowledge_sources": [item.model_dump(mode="json") for item in _knowledge_sources(result)],
        "business_results": [item.model_dump(mode="json") for item in _business_results(result)],
        "pending_action": (
            result.pending_action.model_dump(mode="json") if result.pending_action else None
        ),
        "form_draft": result.form_draft,
        "form_missing_fields": result.form_missing_fields,
    }


async def _persist_result(
    prepared: PreparedChat,
    result: GraphRunResult,
    client: ProcurementBackendClient,
) -> dict[str, int]:
    persist_started = time.perf_counter()
    timings: dict[str, int] = {}
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
    call_started = time.perf_counter()
    await client.add_conversation_message(
        prepared.identity,
        prepared.conversation_id,
        sender_type="AGENT",
        content=result.reply,
        external_message_id=f"agent:{graph_request.task_id}",
        message_data=_persisted_message_data(result),
        trace_id=graph_request.trace_id,
    )
    timings["persist_agent_message_ms"] = _elapsed_ms(call_started)
    backend_state = GraphMemoryMapper.to_backend_state(graph_request, result)
    call_started = time.perf_counter()
    await client.save_conversation_state(
        prepared.identity,
        prepared.conversation_id,
        backend_state,
        graph_request.trace_id,
    )
    timings["persist_state_ms"] = _elapsed_ms(call_started)
    call_started = time.perf_counter()
    await client.save_conversation_snapshot(
        prepared.identity,
        prepared.conversation_id,
        snapshot_reason="GRAPH_RUN_COMPLETED",
        trace_id=graph_request.trace_id,
    )
    timings["persist_snapshot_ms"] = _elapsed_ms(call_started)
    timings["persist_total_ms"] = _elapsed_ms(persist_started)
    logger.info(
        "agent_persistence_completed trace_id=%s timings=%s",
        graph_request.trace_id,
        timings,
    )
    return timings


@router.post("", response_model=AgentApiResponse[ChatData])
async def chat(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClientDependency,
    graph_service: ProcurementGraphServiceDependency,
) -> AgentApiResponse[ChatData]:
    request_started = time.perf_counter()
    prepared = await _prepare_chat(payload, request, client)
    result = await _run_graph(request, graph_service, prepared.graph_request)
    persist_timings = await _persist_result(prepared, result, client)
    performance = {
        **prepared.timings,
        "graph_total_ms": result.duration_ms,
        **persist_timings,
        "request_total_ms": _elapsed_ms(request_started),
    }
    return AgentApiResponse(
        message="回答已生成",
        data=_build_chat_data(request, result, performance),
    )


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    client: ProcurementBackendClientDependency,
    graph_service: ProcurementGraphServiceDependency,
) -> StreamingResponse:
    request_started = time.perf_counter()
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
                persist_timings = await _persist_result(prepared, result, client)
                performance = {
                    **prepared.timings,
                    "graph_total_ms": result.duration_ms,
                    **persist_timings,
                    "request_total_ms": _elapsed_ms(request_started),
                }
                chat_data = _build_chat_data(request, result, performance)
                for source in _knowledge_sources(result):
                    await queue.put(
                        (
                            "citation",
                            source.model_dump(mode="json"),
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
