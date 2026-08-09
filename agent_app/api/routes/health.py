from fastapi import APIRouter, Request

from agent_app.api.dependencies import ProcurementBackendClientDependency
from agent_app.clients.errors import ProcurementBackendError
from agent_app.core.request_context import trace_id_context
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
        ready = backend.status == "ready"
    except ProcurementBackendError:
        ready = False
    return AgentApiResponse(
        code="OK" if ready else "SERVICE_NOT_READY",
        message="Agent 服务就绪" if ready else "采购后端未就绪",
        data=ReadinessData(
            status="ready" if ready else "not_ready",
            procurement_backend="ok" if ready else "error",
            model=(
                "configured"
                if request.app.state.agent_settings.model_configured
                else "not_configured"
            ),
        ),
    )
