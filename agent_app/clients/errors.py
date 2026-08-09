from typing import Any

from agent_app.core.exceptions import AgentError


class ProcurementBackendError(AgentError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        backend_trace_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = dict(details or {})
        if backend_trace_id:
            merged_details["backend_trace_id"] = backend_trace_id
        super().__init__(
            code,
            message,
            status_code,
            details=merged_details or None,
        )
        self.backend_trace_id = backend_trace_id


class ProcurementBackendTimeout(ProcurementBackendError):
    def __init__(self) -> None:
        super().__init__(
            "PROCUREMENT_BACKEND_TIMEOUT",
            "采购后端响应超时",
            504,
        )


class ProcurementBackendUnavailable(ProcurementBackendError):
    def __init__(self) -> None:
        super().__init__(
            "PROCUREMENT_BACKEND_UNAVAILABLE",
            "采购后端暂不可用",
            503,
        )


class ProcurementBackendProtocolError(ProcurementBackendError):
    def __init__(self) -> None:
        super().__init__(
            "PROCUREMENT_BACKEND_PROTOCOL_ERROR",
            "采购后端返回了无法识别的响应",
            502,
        )
