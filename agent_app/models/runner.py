import asyncio
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agent_app.models.protocols import (
    ModelAdapterError,
    StructuredModelAdapter,
    StructuredModelRequest,
    StructuredModelResponse,
)
from agent_app.resilience import AsyncCircuitBreaker, CircuitOpenError

OutputT = TypeVar("OutputT", bound=BaseModel)


class StructuredModelRunError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        attempts: int,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts
        self.retryable = retryable


class StructuredModelRunner:
    def __init__(
        self,
        adapter: StructuredModelAdapter,
        *,
        timeout_seconds: float,
        max_retries: int,
        circuit_breaker: AsyncCircuitBreaker | None = None,
    ) -> None:
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker or AsyncCircuitBreaker(
            failure_threshold=3,
            recovery_timeout_seconds=30,
        )

    async def run(
        self,
        request: StructuredModelRequest,
        output_type: type[OutputT],
    ) -> tuple[OutputT, StructuredModelResponse, int]:
        attempts = 1 + self.max_retries
        last_error: StructuredModelRunError | None = None
        for attempt in range(1, attempts + 1):

            async def invoke_adapter() -> StructuredModelResponse:
                async with asyncio.timeout(self.timeout_seconds):
                    return await self.adapter.complete_structured(request)

            try:
                response = await self.circuit_breaker.call(invoke_adapter)
            except CircuitOpenError:
                last_error = StructuredModelRunError(
                    "MODEL_CIRCUIT_OPEN",
                    "模型服务熔断中，请稍后重试",
                    attempts=attempt,
                    retryable=True,
                )
            except TimeoutError:
                last_error = StructuredModelRunError(
                    "MODEL_TIMEOUT",
                    "模型调用超时",
                    attempts=attempt,
                    retryable=True,
                )
            except ModelAdapterError as exc:
                last_error = StructuredModelRunError(
                    exc.code,
                    exc.message,
                    attempts=attempt,
                    retryable=exc.retryable,
                )
            except Exception:
                raise StructuredModelRunError(
                    "MODEL_UNEXPECTED_FAILURE",
                    "模型调用发生未预期故障",
                    attempts=attempt,
                    retryable=False,
                ) from None
            else:
                try:
                    parsed = output_type.model_validate(response.output)
                except ValidationError:
                    last_error = StructuredModelRunError(
                        "MODEL_STRUCTURED_OUTPUT_INVALID",
                        "模型结构化输出不符合 Schema",
                        attempts=attempt,
                        retryable=True,
                    )
                else:
                    return parsed, response, attempt
            if last_error and (
                last_error.code == "MODEL_CIRCUIT_OPEN"
                or not last_error.retryable
                or attempt >= attempts
            ):
                raise last_error
        if last_error:
            raise last_error
        raise StructuredModelRunError(
            "MODEL_RUN_FAILED",
            "模型调用失败",
            attempts=attempts,
            retryable=False,
        )
