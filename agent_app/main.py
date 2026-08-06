from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_app.api.router import agent_system_router, agent_v1_router
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.config import AgentSettings, get_agent_settings
from agent_app.core.exceptions import register_agent_exception_handlers
from agent_app.core.logging import configure_agent_logging
from agent_app.core.middleware import AgentTraceIdMiddleware
from agent_app.graph.service import ProcurementGraphService


def create_agent_app(
    settings: AgentSettings | None = None,
    procurement_backend_client: ProcurementBackendClient | None = None,
    graph_service: ProcurementGraphService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_agent_settings()
    owns_client = procurement_backend_client is None
    client = procurement_backend_client or ProcurementBackendClient(resolved_settings)
    resolved_graph_service = graph_service or ProcurementGraphService(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_agent_logging(resolved_settings)
        try:
            yield
        finally:
            if owns_client:
                await client.aclose()

    application = FastAPI(
        title=resolved_settings.agent_app_name,
        version="0.1.0",
        debug=resolved_settings.agent_debug,
        lifespan=lifespan,
    )
    application.state.agent_settings = resolved_settings
    application.state.procurement_backend_client = client
    application.state.graph_service = resolved_graph_service
    application.add_middleware(AgentTraceIdMiddleware)
    register_agent_exception_handlers(application)
    application.include_router(agent_system_router)
    application.include_router(
        agent_v1_router,
        prefix=resolved_settings.agent_api_v1_prefix,
    )
    return application


app = create_agent_app()
