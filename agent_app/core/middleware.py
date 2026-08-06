from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_app.core.request_context import trace_id_context


class AgentTraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Request-Id") or str(uuid4())
        token = trace_id_context.set(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = trace_id
            return response
        finally:
            trace_id_context.reset(token)
