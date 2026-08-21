import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from agent_app.models.protocols import (
    ModelAdapterError,
    StreamingStructuredModelAdapter,
    StructuredModelAdapter,
    StructuredModelRequest,
    StructuredModelResponse,
)
from agent_app.models.usage import ModelUsageLedger
from agent_app.resilience import AsyncCircuitBreaker, CircuitOpenError

OutputT = TypeVar("OutputT", bound=BaseModel)
logger = logging.getLogger(__name__)
_STRUCTURED_OUTPUT_ERROR_CODES = {
    "MODEL_STRUCTURED_OUTPUT_INVALID_JSON",
    "MODEL_STRUCTURED_OUTPUT_INVALID",
}
_DIRECT_FALLBACK_ERROR_CODES = {
    *_STRUCTURED_OUTPUT_ERROR_CODES,
    "MODEL_AUTH_FAILED",
}


class StructuredModelRunError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        attempts: int,
        retryable: bool,
        primary_model: str | None = None,
        actual_model: str | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts
        self.retryable = retryable
        self.primary_model = primary_model
        self.actual_model = actual_model
        self.fallback_used = fallback_used
        self.fallback_reason = fallback_reason


class StructuredModelRunner:
    def __init__(
        self,
        adapter: StructuredModelAdapter,
        *,
        timeout_seconds: float,
        max_retries: int,
        circuit_breaker: AsyncCircuitBreaker | None = None,
        usage_ledger: ModelUsageLedger | None = None,
        fallback_adapter: StructuredModelAdapter | None = None,
        primary_model: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.usage_ledger = usage_ledger
        self.circuit_breaker = circuit_breaker or AsyncCircuitBreaker(
            failure_threshold=3,
            recovery_timeout_seconds=30,
        )
        self.fallback_adapter = fallback_adapter
        self.primary_model = primary_model

    async def aclose(self) -> None:
        seen: set[int] = set()
        for adapter in (self.adapter, self.fallback_adapter):
            if adapter is None or id(adapter) in seen:
                continue
            seen.add(id(adapter))
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()

    async def run(
        self,
        request: StructuredModelRequest,
        output_type: type[OutputT],
        delta_handler: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[OutputT, StructuredModelResponse, int]:
        run_started = time.perf_counter()
        expected_schema = output_type.model_json_schema(mode="serialization")
        if request.response_schema != expected_schema:
            raise StructuredModelRunError(
                "MODEL_RESPONSE_SCHEMA_MISMATCH",
                "请求声明的结构化 Schema 与输出类型不一致",
                attempts=0,
                retryable=False,
                primary_model=self.primary_model,
            )
        attempts = 1 + self.max_retries
        last_error: StructuredModelRunError | None = None
        for attempt in range(1, attempts + 1):
            emitted_delta = False

            async def tracked_delta(value: str) -> None:
                nonlocal emitted_delta
                emitted_delta = True
                assert delta_handler is not None
                await delta_handler(value)

            async def invoke_adapter(
                adapter: StructuredModelAdapter,
            ) -> StructuredModelResponse:
                async with asyncio.timeout(self.timeout_seconds):
                    if delta_handler is not None:
                        streaming = getattr(adapter, "complete_structured_stream", None)
                        if streaming is None:
                            raise ModelAdapterError(
                                "MODEL_STREAMING_NOT_SUPPORTED",
                                "当前模型 Provider 不支持真实流式输出",
                                retryable=False,
                            )
                        typed_adapter = cast(StreamingStructuredModelAdapter, adapter)
                        return await typed_adapter.complete_structured_stream(
                            request, tracked_delta
                        )
                    return await adapter.complete_structured(request)

            async def invoke_fallback(
                fallback_reason: str, current_attempt: int
            ) -> StructuredModelResponse:
                assert self.fallback_adapter is not None
                try:
                    fallback_response = await invoke_adapter(self.fallback_adapter)
                except TimeoutError:
                    raise self._error(
                        "MODEL_FALLBACK_TIMEOUT",
                        "Fallback 模型调用超时",
                        current_attempt,
                        retryable=True,
                        fallback_used=True,
                        fallback_reason=fallback_reason,
                    ) from None
                except ModelAdapterError as exc:
                    raise self._error(
                        exc.code,
                        f"Fallback 模型失败：{exc.message}",
                        current_attempt,
                        retryable=exc.retryable,
                        fallback_used=True,
                        fallback_reason=fallback_reason,
                    ) from None
                except Exception:
                    raise self._error(
                        "MODEL_FALLBACK_UNEXPECTED_FAILURE",
                        "Fallback 模型发生未预期故障",
                        current_attempt,
                        retryable=False,
                        fallback_used=True,
                        fallback_reason=fallback_reason,
                    ) from None
                response = fallback_response.model_copy(
                    update={
                        "primary_model": self.primary_model,
                        "actual_model": fallback_response.model,
                        "fallback_used": True,
                        "fallback_reason": fallback_reason,
                    }
                )
                logger.warning(
                    "Primary model failed; fallback model used",
                    extra={
                        "primary_model": self.primary_model,
                        "actual_model": fallback_response.model,
                        "fallback_used": True,
                        "fallback_reason": fallback_reason,
                    },
                )
                return response

            response: StructuredModelResponse | None = None
            primary_error: StructuredModelRunError | None = None
            try:
                response = await self.circuit_breaker.call(lambda: invoke_adapter(self.adapter))
            except CircuitOpenError:
                primary_error = self._error(
                    "MODEL_CIRCUIT_OPEN",
                    "Primary 模型熔断中",
                    attempt,
                    retryable=True,
                )
            except TimeoutError:
                primary_error = self._error(
                    "MODEL_TIMEOUT",
                    "Primary 模型调用超时",
                    attempt,
                    retryable=True,
                )
            except ModelAdapterError as exc:
                primary_error = self._error(
                    exc.code,
                    exc.message,
                    attempt,
                    retryable=exc.retryable,
                )
            except Exception:
                raise self._error(
                    "MODEL_UNEXPECTED_FAILURE",
                    "Primary 模型发生未预期故障",
                    attempt,
                    retryable=False,
                ) from None

            if primary_error is not None:
                last_error = primary_error
                direct_fallback_error = primary_error.code in _DIRECT_FALLBACK_ERROR_CODES
                if (
                    (primary_error.retryable or direct_fallback_error)
                    and self.fallback_adapter is not None
                    and not emitted_delta
                ):
                    fallback_reason = f"{primary_error.code}: {primary_error.message}"
                    try:
                        response = await invoke_fallback(fallback_reason, attempt)
                    except StructuredModelRunError as exc:
                        last_error = exc
                        if direct_fallback_error:
                            raise last_error from None
                if response is None:
                    assert last_error is not None
                    if (
                        last_error.code == "MODEL_CIRCUIT_OPEN"
                        or not last_error.retryable
                        or attempt >= attempts
                    ):
                        raise last_error
                    continue

            assert response is not None
            while True:
                validation_started = time.perf_counter()
                try:
                    parsed = output_type.model_validate(response.output)
                except ValidationError as exc:
                    validation_details = "; ".join(
                        (
                            f"{'.'.join(str(part) for part in item['loc'])}: "
                            f"{item['type']} ({str(item.get('msg', ''))[:200]})"
                        )
                        for item in exc.errors(include_input=False)[:8]
                    )
                    last_error = self._error(
                        "MODEL_STRUCTURED_OUTPUT_INVALID",
                        f"模型结构化输出不符合 Schema：{validation_details}",
                        attempt,
                        retryable=False,
                        actual_model=response.actual_model or response.model,
                        fallback_used=response.fallback_used,
                        fallback_reason=response.fallback_reason,
                    )
                    if emitted_delta or response.fallback_used or self.fallback_adapter is None:
                        raise last_error from None
                    fallback_reason = f"{last_error.code}: {last_error.message}"
                    try:
                        response = await invoke_fallback(fallback_reason, attempt)
                    except StructuredModelRunError as exc:
                        raise exc from None
                    continue

                schema_validation_ms = max(
                    0, round((time.perf_counter() - validation_started) * 1000)
                )
                runner_latency_ms = max(0, round((time.perf_counter() - run_started) * 1000))
                response = response.model_copy(
                    update={
                        "schema_validation_ms": schema_validation_ms,
                        "runner_latency_ms": runner_latency_ms,
                        "retry_overhead_ms": max(0, runner_latency_ms - response.latency_ms),
                    }
                )
                if self.usage_ledger is not None:
                    self.usage_ledger.record(request.purpose, response, attempt)
                return parsed, response, attempt
        if last_error:
            raise last_error
        raise self._error(
            "MODEL_RUN_FAILED",
            "模型调用失败",
            attempts,
            retryable=False,
        )

    def _error(
        self,
        code: str,
        message: str,
        attempts: int,
        *,
        retryable: bool,
        actual_model: str | None = None,
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> StructuredModelRunError:
        return StructuredModelRunError(
            code,
            message,
            attempts=attempts,
            retryable=retryable,
            primary_model=self.primary_model,
            actual_model=actual_model,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
