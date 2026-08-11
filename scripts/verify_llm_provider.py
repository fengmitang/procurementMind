"""Run minimal live checks against the configured OpenAI-compatible LLM provider."""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import AgentSettings  # noqa: E402


class StructuredVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    message: str = Field(min_length=1, max_length=100)


class PurchaseStatusArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(gt=0)


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    model: str
    detail: str


class ProviderResponseError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class LiveProviderVerifier:
    def __init__(self, settings: AgentSettings, *, timeout_seconds: float) -> None:
        if not settings.model_configured:
            raise RuntimeError("LLM Provider 配置不完整")
        if not settings.model_base_url:
            raise RuntimeError("MODEL_BASE_URL 未配置")
        if not settings.fallback_model:
            raise RuntimeError("FALLBACK_MODEL/LLM_FALLBACK_MODEL 未配置")
        assert settings.model_api_key is not None
        assert settings.primary_model is not None
        self.primary_model = settings.primary_model
        self.fallback_model = settings.fallback_model
        self.api_key = settings.model_api_key.get_secret_value()
        base_url = settings.model_base_url.rstrip("/")
        self.endpoint = (
            base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
        )
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        started = time.perf_counter()
        try:
            response = await self.client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except Exception as exc:
            raise RuntimeError(self.sanitize(f"{type(exc).__name__}: {exc}")) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        try:
            body = response.json() if response.content else {}
        except ValueError as exc:
            raise ProviderResponseError(
                response.status_code,
                self.sanitize(f"非 JSON 响应，latency_ms={latency_ms}"),
            ) from exc
        if not response.is_success:
            error = body.get("error") if isinstance(body, dict) else body
            detail = error.get("message") if isinstance(error, dict) else error
            raise ProviderResponseError(
                response.status_code,
                self.sanitize(f"{detail}; latency_ms={latency_ms}"),
            )
        if not isinstance(body, dict):
            raise RuntimeError("响应体不是 JSON 对象")
        body["_verification_latency_ms"] = latency_ms
        return body

    def sanitize(self, value: str) -> str:
        return value.replace(self.api_key, "[REDACTED]")[:800]

    @staticmethod
    def message(body: dict[str, Any]) -> dict[str, Any]:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("响应缺少 choices[0]")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError("响应缺少 assistant message")
        return message

    @staticmethod
    def content(message: dict[str, Any]) -> str:
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""


async def verify_primary_chat(verifier: LiveProviderVerifier) -> CheckResult:
    name = "Primary 中文 Chat Completion"
    model = verifier.primary_model
    try:
        body = await verifier.complete(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "请用一句简短中文回答：采购智能协同系统已连接成功。",
                }
            ],
        )
        content = verifier.content(verifier.message(body))
        if not content:
            raise RuntimeError("模型未返回最终文本")
        return CheckResult(
            name,
            True,
            str(body.get("model") or model),
            f"latency_ms={body['_verification_latency_ms']}; reply={content[:120]}",
        )
    except Exception as exc:
        return CheckResult(name, False, model, verifier.sanitize(str(exc)))


async def verify_structured_output(verifier: LiveProviderVerifier) -> CheckResult:
    name = "Pydantic/JSON 结构化输出"
    model = verifier.primary_model
    schema = StructuredVerification.model_json_schema(mode="serialization")
    try:
        body = await verifier.complete(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你必须严格按照指定 JSON Schema 返回结果。",
                },
                {
                    "role": "user",
                    "content": "返回 passed=true，message 使用中文说明结构化输出正常。",
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "provider_verification",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        content = verifier.content(verifier.message(body))
        parsed = StructuredVerification.model_validate_json(content)
        if not parsed.passed:
            raise RuntimeError("结构化结果 passed=false")
        return CheckResult(
            name,
            True,
            str(body.get("model") or model),
            f"latency_ms={body['_verification_latency_ms']}; message={parsed.message}",
        )
    except (ValidationError, ValueError, RuntimeError, ProviderResponseError) as exc:
        return CheckResult(name, False, model, verifier.sanitize(str(exc)))


def purchase_status_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "get_purchase_status",
            "description": "查询指定采购申请的当前状态。",
            "parameters": PurchaseStatusArguments.model_json_schema(mode="serialization"),
        },
    }


async def verify_tool_roundtrip(
    verifier: LiveProviderVerifier,
) -> tuple[CheckResult, CheckResult]:
    call_name = "Tool Calling 主动调用"
    answer_name = "Tool Result 第二轮回答"
    model = verifier.primary_model
    user_message = {
        "role": "user",
        "content": "请查询采购申请 91007 的当前状态。必须先调用提供的工具，不要猜测。",
    }
    try:
        first = await verifier.complete(
            model=model,
            messages=[user_message],
            tools=[purchase_status_tool()],
            tool_choice="auto",
        )
        assistant_message = verifier.message(first)
        tool_calls = assistant_message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            raise RuntimeError("模型没有主动发起工具调用")
        tool_call = tool_calls[0]
        if not isinstance(tool_call, dict):
            raise RuntimeError("tool_call 格式无效")
        function = tool_call.get("function")
        if not isinstance(function, dict) or function.get("name") != "get_purchase_status":
            raise RuntimeError("模型调用了非预期工具")
        arguments = PurchaseStatusArguments.model_validate_json(str(function.get("arguments", "")))
        if arguments.requirement_id != 91007:
            raise RuntimeError(f"工具参数错误 requirement_id={arguments.requirement_id}")
        call_result = CheckResult(
            call_name,
            True,
            str(first.get("model") or model),
            (
                f"latency_ms={first['_verification_latency_ms']}; "
                f"tool=get_purchase_status; requirement_id={arguments.requirement_id}"
            ),
        )
    except Exception as exc:
        detail = verifier.sanitize(str(exc))
        return (
            CheckResult(call_name, False, model, detail),
            CheckResult(answer_name, False, model, "前置 Tool Calling 未通过"),
        )

    forwarded_assistant = {
        key: assistant_message[key]
        for key in ("role", "content", "reasoning_content", "tool_calls")
        if key in assistant_message
    }
    try:
        second = await verifier.complete(
            model=model,
            messages=[
                user_message,
                forwarded_assistant,
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call.get("id")),
                    "name": "get_purchase_status",
                    "content": json.dumps(
                        {
                            "requirement_id": 91007,
                            "status": "COMPLETED",
                            "source": "fake_verification_tool",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            tools=[purchase_status_tool()],
            tool_choice="auto",
        )
        content = verifier.content(verifier.message(second))
        if not content:
            raise RuntimeError("模型接收 Tool Result 后未返回最终文本")
        answer_result = CheckResult(
            answer_name,
            True,
            str(second.get("model") or model),
            f"latency_ms={second['_verification_latency_ms']}; reply={content[:160]}",
        )
    except Exception as exc:
        answer_result = CheckResult(answer_name, False, model, verifier.sanitize(str(exc)))
    return call_result, answer_result


async def verify_fallback(verifier: LiveProviderVerifier) -> CheckResult:
    name = "Primary 失败后切换 Fallback"
    invalid_primary = f"{verifier.primary_model}-intentional-invalid"
    primary_error = ""
    try:
        await verifier.complete(
            model=invalid_primary,
            messages=[{"role": "user", "content": "只回复 OK"}],
            max_tokens=128,
        )
        return CheckResult(name, False, invalid_primary, "故意设置的无效 Primary 未失败")
    except Exception as exc:
        primary_error = verifier.sanitize(str(exc))

    try:
        body = await verifier.complete(
            model=verifier.fallback_model,
            messages=[{"role": "user", "content": "请用中文回复：备用模型切换成功。"}],
        )
        content = verifier.content(verifier.message(body))
        if not content:
            raise RuntimeError("Fallback 未返回最终文本")
        return CheckResult(
            name,
            True,
            str(body.get("model") or verifier.fallback_model),
            (
                f"primary_error={primary_error}; "
                f"latency_ms={body['_verification_latency_ms']}; reply={content[:120]}"
            ),
        )
    except Exception as exc:
        return CheckResult(
            name,
            False,
            verifier.fallback_model,
            f"primary_error={primary_error}; fallback_error={verifier.sanitize(str(exc))}",
        )


def print_result(result: CheckResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"[{status}] {result.name} | model={result.model} | {result.detail}")


async def verify(timeout_seconds: float) -> int:
    settings = AgentSettings()
    verifier = LiveProviderVerifier(settings, timeout_seconds=timeout_seconds)
    try:
        results = [
            await verify_primary_chat(verifier),
            await verify_structured_output(verifier),
        ]
        results.extend(await verify_tool_roundtrip(verifier))
        results.append(await verify_fallback(verifier))
    finally:
        await verifier.close()

    for result in results:
        print_result(result)
    passed = sum(result.passed for result in results)
    print(f"SUMMARY {passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="验证当前 OpenAI-compatible LLM Provider")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="单次请求超时秒数，默认使用 MODEL_TIMEOUT_SECONDS",
    )
    args = parser.parse_args()
    settings = AgentSettings()
    timeout_seconds = args.timeout or settings.model_timeout_seconds
    return asyncio.run(verify(timeout_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
