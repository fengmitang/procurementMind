from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent_app.core.request_context import trace_id_context


class AgentError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "code": code,
            "message": message,
            "data": details,
            "trace_id": trace_id_context.get(),
        },
    )


def register_agent_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentError)
    async def agent_exception_handler(_: Request, exc: AgentError) -> JSONResponse:
        return error_response(
            exc.code,
            exc.message,
            exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            422,
            details={"errors": exc.errors()},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response("HTTP_ERROR", str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
        return error_response("INTERNAL_ERROR", "Agent 服务内部错误", 500)
