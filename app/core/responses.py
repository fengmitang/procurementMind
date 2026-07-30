from pydantic import BaseModel

from app.core.request_context import request_id_context


class ApiResponse[DataT](BaseModel):
    success: bool = True
    code: str = "OK"
    message: str = "操作成功"
    data: DataT
    trace_id: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.trace_id is None:
            self.trace_id = request_id_context.get()
