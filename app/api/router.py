from fastapi import APIRouter

from app.api.routes.agent_sessions import router as agent_sessions_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.demo import router as demo_router
from app.api.routes.handlers import router as handlers_router
from app.api.routes.health import router as health_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.procurement import router as procurement_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.records import router as records_router
from app.api.routes.suppliers import router as suppliers_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(demo_router)
api_router.include_router(agent_sessions_router)
api_router.include_router(analytics_router)
api_router.include_router(notifications_router)
api_router.include_router(users_router)
api_router.include_router(handlers_router)
api_router.include_router(procurement_router)
api_router.include_router(records_router)
api_router.include_router(suppliers_router)
api_router.include_router(recommendations_router)
