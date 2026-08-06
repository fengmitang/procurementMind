from typing import Literal

from pydantic import BaseModel

from agent_app.core.request_context import trace_id_context


class AgentApiResponse[DataT](BaseModel):
    success: bool = True
    code: str = "OK"
    message: str = "操作成功"
    data: DataT
    trace_id: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.trace_id is None:
            self.trace_id = trace_id_context.get()


class HealthData(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessData(BaseModel):
    status: Literal["ready", "not_ready"]
    procurement_backend: Literal["ok", "error"]
    model: Literal["configured", "not_configured"]
