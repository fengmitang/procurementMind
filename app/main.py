from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    try:
        yield
    finally:
        await engine.dispose()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
app.include_router(api_router)

demo_directory = Path(__file__).resolve().parents[1] / "frontend"
if settings.app_env.lower() == "development" and demo_directory.exists():
    app.mount(
        "/demo",
        StaticFiles(directory=demo_directory, html=True),
        name="development-demo",
    )
