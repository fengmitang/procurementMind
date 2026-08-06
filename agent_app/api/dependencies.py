from typing import Annotated

from fastapi import Depends, Request

from agent_app.clients.procurement_backend import ProcurementBackendClient
from agent_app.graph.service import ProcurementGraphService


def get_procurement_backend_client(request: Request) -> ProcurementBackendClient:
    return request.app.state.procurement_backend_client


ProcurementBackendClientDependency = Annotated[
    ProcurementBackendClient,
    Depends(get_procurement_backend_client),
]


def get_graph_service(request: Request) -> ProcurementGraphService:
    return request.app.state.graph_service


ProcurementGraphServiceDependency = Annotated[
    ProcurementGraphService,
    Depends(get_graph_service),
]
