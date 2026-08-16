import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent_app.api.router import agent_system_router, agent_v1_router
from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.core.config import AgentSettings, get_agent_settings
from agent_app.core.exceptions import register_agent_exception_handlers
from agent_app.core.logging import configure_agent_logging
from agent_app.core.middleware import AgentTraceIdMiddleware
from agent_app.device_terms.service import DeviceTermSearchService
from agent_app.device_terms.store import QdrantDeviceTermStore
from agent_app.graph.service import ProcurementGraphService
from agent_app.hitl.service import HITLService
from agent_app.models.registry import build_default_model_registry
from agent_app.models.roles import ModelQueryRewriteProvider, StructuredModelRoles
from agent_app.models.runtime import ModelRuntime, ModelRuntimeStatus
from agent_app.rag.models import LocalRAGModels, initialize_rag_providers
from agent_app.rag.providers import RAGProviders
from agent_app.rag.qdrant import QdrantKnowledgeStore
from agent_app.rag.retriever import KnowledgeRetriever
from app.db.session import async_session_factory


def create_agent_app(
    settings: AgentSettings | None = None,
    procurement_backend_client: ProcurementBackendClient | None = None,
    graph_service: ProcurementGraphService | None = None,
    rag_models: LocalRAGModels | RAGProviders | None = None,
    model_roles: StructuredModelRoles | None = None,
    model_runtime: ModelRuntime | None = None,
) -> FastAPI:
    resolved_settings = settings or get_agent_settings()
    owns_client = procurement_backend_client is None
    client = procurement_backend_client or ProcurementBackendClient(resolved_settings)
    resolved_graph_service = graph_service or ProcurementGraphService(resolved_settings)
    owns_model_runtime = model_runtime is None
    resolved_model_runtime = model_runtime or ModelRuntime.from_settings(
        resolved_settings,
        build_default_model_registry(),
    )
    resolved_model_roles = model_roles
    if resolved_model_roles is None and resolved_model_runtime.status is ModelRuntimeStatus.READY:
        resolved_model_roles = StructuredModelRoles(
            resolved_model_runtime.require_runner(),
            "agent-runtime",
            performance_optimizations_enabled=(resolved_settings.performance_optimizations_enabled),
        )
    if resolved_model_roles is not None and hasattr(resolved_graph_service, "set_model_roles"):
        resolved_graph_service.set_model_roles(resolved_model_roles)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_agent_logging(resolved_settings)
        qdrant_store: QdrantKnowledgeStore | None = None
        device_term_store: QdrantDeviceTermStore | None = None
        active_rag_models = rag_models
        if rag_models is None and resolved_settings.rag_models_configured:
            active_rag_models = await asyncio.to_thread(
                initialize_rag_providers,
                resolved_settings,
            )
            application.state.rag_models = active_rag_models
        if active_rag_models is not None and hasattr(
            resolved_graph_service, "set_knowledge_retriever"
        ):
            qdrant_store = QdrantKnowledgeStore(resolved_settings)
            resolved_graph_service.set_knowledge_retriever(
                KnowledgeRetriever(
                    settings=resolved_settings,
                    session_factory=async_session_factory,
                    model_provider=active_rag_models,
                    qdrant_store=qdrant_store,
                    query_rewriter=(
                        ModelQueryRewriteProvider(resolved_model_roles)
                        if resolved_model_roles is not None
                        else None
                    ),
                )
            )
            if hasattr(resolved_graph_service, "set_device_term_search"):
                device_term_store = QdrantDeviceTermStore(resolved_settings)
                resolved_graph_service.set_device_term_search(
                    DeviceTermSearchService(
                        embedding_provider=active_rag_models,
                        store=device_term_store,
                        top_k=resolved_settings.device_term_top_k,
                        embedding_batch_size=resolved_settings.rag_embedding_batch_size,
                        embedding_max_length=resolved_settings.rag_embedding_max_length,
                    )
                )
        try:
            yield
        finally:
            if qdrant_store is not None:
                await qdrant_store.close()
            if device_term_store is not None:
                await device_term_store.close()
            if rag_models is None and active_rag_models is not None:
                close_rag = getattr(active_rag_models, "close", None)
                if callable(close_rag):
                    await asyncio.to_thread(close_rag)
            if owns_client:
                await client.aclose()
            if owns_model_runtime:
                await resolved_model_runtime.aclose()

    application = FastAPI(
        title=resolved_settings.agent_app_name,
        version="0.1.0",
        debug=resolved_settings.agent_debug,
        lifespan=lifespan,
    )
    application.state.agent_settings = resolved_settings
    application.state.procurement_backend_client = client
    application.state.graph_service = resolved_graph_service
    application.state.model_runtime = resolved_model_runtime
    application.state.hitl_service = HITLService(client)
    application.state.rag_models = rag_models
    application.add_middleware(AgentTraceIdMiddleware)
    register_agent_exception_handlers(application)
    application.include_router(agent_system_router)
    application.include_router(
        agent_v1_router,
        prefix=resolved_settings.agent_api_v1_prefix,
    )
    return application


app = create_agent_app()
