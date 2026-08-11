from fastapi import APIRouter, Request

from agent_app.api.dependencies import ProcurementBackendClientDependency
from agent_app.clients.errors import ProcurementBackendError
from agent_app.core.request_context import trace_id_context
from agent_app.models.runtime import ModelRuntimeStatus
from agent_app.schemas.common import AgentApiResponse, HealthData, ReadinessData

router = APIRouter(tags=["agent-system"])


@router.get("/health", response_model=AgentApiResponse[HealthData])
async def health() -> AgentApiResponse[HealthData]:
    return AgentApiResponse(data=HealthData())


@router.get("/ready", response_model=AgentApiResponse[ReadinessData])
async def readiness(
    request: Request,
    client: ProcurementBackendClientDependency,
) -> AgentApiResponse[ReadinessData]:
    trace_id = trace_id_context.get() or "agent-ready"
    try:
        backend = await client.readiness(trace_id)
        backend_ready = backend.status == "ready"
    except ProcurementBackendError:
        backend_ready = False
    runtime_status = request.app.state.model_runtime.status
    model_status = {
        ModelRuntimeStatus.NOT_CONFIGURED: "not_configured",
        ModelRuntimeStatus.INITIALIZING: "initializing",
        ModelRuntimeStatus.READY: "ready",
        ModelRuntimeStatus.PROVIDER_NOT_REGISTERED: "provider_not_registered",
        ModelRuntimeStatus.INITIALIZATION_FAILED: "initialization_failed",
    }[runtime_status]
    model_ready = runtime_status in {
        ModelRuntimeStatus.NOT_CONFIGURED,
        ModelRuntimeStatus.READY,
    }
    ready = backend_ready and model_ready
    return AgentApiResponse(
        code="OK" if ready else "SERVICE_NOT_READY",
        message="Agent 服务就绪" if ready else "采购后端未就绪",
        data=ReadinessData(
            status="ready" if ready else "not_ready",
            procurement_backend="ok" if backend_ready else "error",
            model=model_status,
        ),
    )
