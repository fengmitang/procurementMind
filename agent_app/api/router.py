from fastapi import APIRouter

from agent_app.api.routes.actions import router as actions_router
from agent_app.api.routes.chat import router as chat_router
from agent_app.api.routes.health import router as health_router

agent_system_router = APIRouter()
agent_system_router.include_router(health_router)

agent_v1_router = APIRouter()
agent_v1_router.include_router(chat_router)
agent_v1_router.include_router(actions_router)
