from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.responses import ApiResponse
from app.db.session import engine

router = APIRouter(tags=["system"])


class HealthData(BaseModel):
    status: Literal["ok"]


class ReadinessData(BaseModel):
    status: Literal["ready", "not_ready"]
    mysql: Literal["ok", "error"]
    redis: Literal["ok", "error"]


@router.get("/health", response_model=ApiResponse[HealthData])
async def health() -> ApiResponse[HealthData]:
    return ApiResponse(data=HealthData(status="ok"))


@router.get("/ready", response_model=ApiResponse[ReadinessData])
async def readiness() -> ApiResponse[ReadinessData]:
    mysql_status: Literal["ok", "error"] = "error"
    redis_status: Literal["ok", "error"] = "error"

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        mysql_status = "ok"
    except Exception:
        mysql_status = "error"

    settings = get_settings()
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "error"
    finally:
        await client.aclose()

    ready = mysql_status == "ok" and redis_status == "ok"
    return ApiResponse(
        code="OK" if ready else "SERVICE_NOT_READY",
        message="服务就绪" if ready else "依赖服务未就绪",
        data=ReadinessData(
            status="ready" if ready else "not_ready",
            mysql=mysql_status,
            redis=redis_status,
        ),
    )
