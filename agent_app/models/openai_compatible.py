import json
import time
from typing import Any

import httpx

from agent_app.models.configuration import ModelRuntimeConfiguration
from agent_app.models.protocols import (
    ModelAdapterError,
    ModelDeltaHandler,
    ModelUsage,
    ModelUsageSource,
    StructuredModelRequest,
    StructuredModelResponse,
)


class OpenAICompatibleStructuredAdapter:
    """Minimal production adapter for OpenAI-compatible structured chat completions."""

    def __init__(
        self,
        configuration: ModelRuntimeConfiguration,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not configuration.model or not configuration.api_key or not configuration.base_url:
            raise ValueError("OpenAI-compatible Adapter 配置不完整")
        self.configuration = configuration
        self.model = configuration.model
        self.api_key = configuration.api_key.get_secret_value()
        base_url = configuration.base_url.rstrip("/")
        self.endpoint = (
            base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        )
        self._owns_client = http_client is None
        # StructuredModelRunner owns the single request timeout policy. Disabling
        # httpx's shorter default prevents it from pre-empting that runtime limit.
        self.http_client = http_client or httpx.AsyncClient(timeout=None)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.http_client.aclose()

    async def complete_structured(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        started = time.perf_counter()
        try:
            response = await self.http_client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-Id": request.trace_id,
                },
                json={
                    "model": self.model,
                    "messages": [item.model_dump(mode="json") for item in request.messages],
                    "temperature": request.temperature,
                    "max_tokens": request.max_output_tokens,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"procurement_{request.purpose.value.lower()}",
                            "strict": True,
                            "schema": self._provider_schema(request.response_schema),
                        },
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise ModelAdapterError("MODEL_TIMEOUT", "模型请求超时", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ModelAdapterError(
                "MODEL_TRANSPORT_ERROR", "模型网络请求失败", retryable=True
            ) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        body = self._json_body(response)
        if response.is_error:
            raise self._response_error(response.status_code, body)
        output = self._structured_output(body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        usage_model = ModelUsage()
        if all(isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)):
            usage_model = ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                source=ModelUsageSource.PROVIDER_REPORTED,
            )
        actual_model = str(body.get("model") or self.model)
        return StructuredModelResponse(
            provider=str(self.configuration.provider or "openai_compatible"),
            model=actual_model,
            output=output,
            usage=usage_model,
            latency_ms=latency_ms,
            request_id=(
                str(body.get("id")) if body.get("id") else response.headers.get("x-request-id")
            ),
            primary_model=self.model,
            actual_model=actual_model,
        )

    async def complete_structured_stream(
        self,
        request: StructuredModelRequest,
        delta_handler: ModelDeltaHandler,
    ) -> StructuredModelResponse:
        started = time.perf_counter()
        content_parts: list[str] = []
        usage: dict[str, Any] = {}
        response_id: str | None = None
        actual_model = self.model
        try:
            async with self.http_client.stream(
                "POST",
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-Id": request.trace_id,
                },
                json={
                    "model": self.model,
                    "messages": [item.model_dump(mode="json") for item in request.messages],
                    "temperature": request.temperature,
                    "max_tokens": request.max_output_tokens,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"procurement_{request.purpose.value.lower()}",
                            "strict": True,
                            "schema": self._provider_schema(request.response_schema),
                        },
                    },
                },
            ) as response:
                if response.is_error:
                    raw = await response.aread()
                    try:
                        body = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        body = {}
                    raise self._response_error(response.status_code, body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ModelAdapterError(
                            "MODEL_STREAM_PROTOCOL_ERROR",
                            "模型流式响应包含无效 JSON 事件",
                            retryable=False,
                        ) from exc
                    if not isinstance(event, dict):
                        continue
                    if event.get("id"):
                        response_id = str(event["id"])
                    if event.get("model"):
                        actual_model = str(event["model"])
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    choices = event.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") if isinstance(choice, dict) else None
                    content = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(content, str) and content:
                        content_parts.append(content)
                        await delta_handler(content)
        except ModelAdapterError:
            raise
        except httpx.TimeoutException as exc:
            raise ModelAdapterError("MODEL_TIMEOUT", "模型请求超时", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ModelAdapterError(
                "MODEL_TRANSPORT_ERROR", "模型网络请求失败", retryable=True
            ) from exc

        content = "".join(content_parts)
        if not content.strip():
            raise ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_EMPTY", "模型未返回结构化正文", retryable=False
            )
        output = self._structured_output({"choices": [{"message": {"content": content}}]})
        usage_model = ModelUsage()
        values = (
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        if all(isinstance(value, int) for value in values):
            usage_model = ModelUsage(
                input_tokens=values[0],
                output_tokens=values[1],
                total_tokens=values[2],
                source=ModelUsageSource.PROVIDER_REPORTED,
            )
        return StructuredModelResponse(
            provider=str(self.configuration.provider or "openai_compatible"),
            model=actual_model,
            output=output,
            usage=usage_model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            request_id=response_id,
            primary_model=self.model,
            actual_model=actual_model,
        )

    @staticmethod
    def _provider_schema(value: Any) -> Any:
        """Remove regex features unsupported by the provider's schema converter.

        Pydantic still validates the complete output after the provider responds, so
        this transport compatibility step does not weaken the runtime contract.
        """
        if isinstance(value, list):
            return [OpenAICompatibleStructuredAdapter._provider_schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {
            key: OpenAICompatibleStructuredAdapter._provider_schema(item)
            for key, item in value.items()
            if not (key == "pattern" and isinstance(item, str) and "(?" in item)
        }

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise ModelAdapterError(
                "MODEL_PROTOCOL_ERROR", "模型返回了非 JSON 响应", retryable=False
            ) from exc
        if not isinstance(body, dict):
            raise ModelAdapterError(
                "MODEL_PROTOCOL_ERROR", "模型响应不是 JSON 对象", retryable=False
            )
        return body

    @staticmethod
    def _structured_output(body: dict[str, Any]) -> dict[str, Any]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelAdapterError(
                "MODEL_PROTOCOL_ERROR", "模型响应缺少 choices[0]", retryable=False
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ModelAdapterError(
                "MODEL_PROTOCOL_ERROR", "模型响应缺少 assistant message", retryable=False
            )
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_EMPTY", "模型未返回结构化正文", retryable=False
            )
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            normalized = "\n".join(lines).strip()
        try:
            output = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_INVALID_JSON",
                "模型结构化正文不是有效 JSON",
                retryable=False,
            ) from exc
        if not isinstance(output, dict):
            raise ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_INVALID", "模型结构化结果不是对象", retryable=False
            )
        return output

    @staticmethod
    def _response_error(status_code: int, body: dict[str, Any]) -> ModelAdapterError:
        error = body.get("error")
        detail = error.get("message") if isinstance(error, dict) else str(error or "")
        safe_detail = str(detail).replace("\r", " ").replace("\n", " ")[:300]
        lowered = detail.lower()
        model_unavailable = any(
            marker in lowered
            for marker in ("model not exist", "model not found", "model unavailable", "已下架")
        )
        if status_code in {401, 403}:
            return ModelAdapterError("MODEL_AUTH_FAILED", "模型认证失败", retryable=False)
        if status_code == 429:
            return ModelAdapterError("MODEL_RATE_LIMITED", "模型请求被限流", retryable=True)
        if status_code in {408, 409, 425} or status_code >= 500:
            return ModelAdapterError(
                "MODEL_UPSTREAM_UNAVAILABLE",
                f"模型服务暂时不可用（HTTP {status_code}）",
                retryable=True,
            )
        if model_unavailable:
            return ModelAdapterError(
                "MODEL_NOT_AVAILABLE", "Primary 模型当前不可用", retryable=True
            )
        return ModelAdapterError(
            "MODEL_REQUEST_REJECTED",
            f"模型请求被拒绝（HTTP {status_code}）：{safe_detail or '未提供详情'}",
            retryable=False,
        )
