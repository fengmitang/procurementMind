import asyncio
from collections import deque

from agent_app.models.protocols import (
    ModelAdapterError,
    StructuredModelRequest,
    StructuredModelResponse,
)


class ScriptedModelAdapter:
    """Deterministic test adapter; never selected by production configuration."""

    def __init__(
        self,
        outcomes: list[StructuredModelResponse | ModelAdapterError],
        *,
        delay_seconds: float = 0,
    ) -> None:
        self.outcomes = deque(outcomes)
        self.delay_seconds = delay_seconds
        self.requests: list[StructuredModelRequest] = []

    async def complete_structured(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not self.outcomes:
            raise ModelAdapterError(
                "FAKE_MODEL_EXHAUSTED",
                "假模型没有更多预设输出",
                retryable=False,
            )
        outcome = self.outcomes.popleft()
        if isinstance(outcome, ModelAdapterError):
            raise outcome
        return outcome
