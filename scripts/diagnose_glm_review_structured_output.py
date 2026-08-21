"""Diagnose glm-5.2 ReviewOutput compatibility without running the Agent graph."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import AgentSettings  # noqa: E402
from agent_app.models.role_schemas import ReviewOutput  # noqa: E402

Mode = Literal["json_schema", "json_object"]

REVIEW_SYSTEM_PROMPT = (
    "你是采购协同 Review。只检查证据缺失、遗漏约束、分析冒充事实、越权、不可见引用、"
    "RAG/Tool 冲突和人工确认需要；不得重新计算后端权限、金额、黑名单、幂等或状态机规则。"
)

JSON_OBJECT_INSTRUCTION = """
只返回一个合法 JSON 对象，不要使用 Markdown 代码块，不要返回数组或解释文字。
对象必须且只能包含以下字段：
- passed: boolean
- issues: array，每项必须包含 code、severity、message、evidence_ids；code 必须是
  MISSING_EVIDENCE、OMITTED_CONSTRAINT、ANALYSIS_AS_FACT、AUTHORITY_EXCEEDED、
  INVISIBLE_EVIDENCE、RAG_TOOL_CONFLICT、HUMAN_CONFIRMATION_REQUIRED 之一；severity
  必须是 WARNING 或 BLOCKING。
- requires_human_confirmation: boolean
- revised_answer: string 或 null
passed=true 时不能包含 BLOCKING；passed=false 时至少包含一个 BLOCKING。
""".strip()


def synthetic_cases() -> list[dict[str, Any]]:
    base = [
        {
            "scenario": "passed_empty_issues",
            "question": "合成问题：当前状态是什么？",
            "draft": {
                "answer": "合成申请当前状态为已完成。",
                "citations": [{"citation_id": "K1", "claim": "当前状态为已完成"}],
                "limitations": [],
                "requires_human_confirmation": False,
            },
            "visible_evidence": [
                {"evidence_id": "K1", "kind": "TOOL", "content": "合成状态：已完成"}
            ],
            "expected_review": {
                "passed": True,
                "issues": [],
                "requires_human_confirmation": False,
                "revised_answer": None,
            },
        },
        {
            "scenario": "blocking_issue",
            "question": "合成问题：供应商是否合规？",
            "draft": {
                "answer": "合成供应商一定合规且不在黑名单。",
                "citations": [],
                "limitations": [],
                "requires_human_confirmation": False,
            },
            "visible_evidence": [],
            "expected_review": {
                "passed": False,
                "issues": [
                    {
                        "code": "MISSING_EVIDENCE",
                        "severity": "BLOCKING",
                        "message": "合规结论缺少证据",
                        "evidence_ids": [],
                    }
                ],
                "requires_human_confirmation": False,
                "revised_answer": "当前证据不足，无法确认合成供应商是否合规。",
            },
        },
        {
            "scenario": "human_confirmation",
            "question": "合成问题：是否可以直接批准？",
            "draft": {
                "answer": "证据仅供参考，最终需要人工确认。",
                "citations": [{"citation_id": "K2", "claim": "最终需要人工确认"}],
                "limitations": [],
                "requires_human_confirmation": True,
            },
            "visible_evidence": [
                {"evidence_id": "K2", "kind": "RULE", "content": "审批结论须由人工确认"}
            ],
            "expected_review": {
                "passed": True,
                "issues": [
                    {
                        "code": "HUMAN_CONFIRMATION_REQUIRED",
                        "severity": "WARNING",
                        "message": "需要人工确认",
                        "evidence_ids": ["K2"],
                    }
                ],
                "requires_human_confirmation": True,
                "revised_answer": None,
            },
        },
        {
            "scenario": "passed_null_revision",
            "question": "合成问题：数量是多少？",
            "draft": {
                "answer": "合成申请数量为3台。",
                "citations": [{"citation_id": "K3", "claim": "数量为3台"}],
                "limitations": [],
                "requires_human_confirmation": False,
            },
            "visible_evidence": [
                {"evidence_id": "K3", "kind": "TOOL", "content": "合成数量：3台"}
            ],
            "expected_review": {
                "passed": True,
                "issues": [],
                "requires_human_confirmation": False,
                "revised_answer": None,
            },
        },
        {
            "scenario": "blocking_with_revision",
            "question": "合成问题：助手能否替用户批准？",
            "draft": {
                "answer": "助手已经替用户批准合成申请。",
                "citations": [],
                "limitations": [],
                "requires_human_confirmation": False,
            },
            "visible_evidence": [
                {"evidence_id": "K4", "kind": "RULE", "content": "助手不得替代人工审批"}
            ],
            "expected_review": {
                "passed": False,
                "issues": [
                    {
                        "code": "AUTHORITY_EXCEEDED",
                        "severity": "BLOCKING",
                        "message": "助手不得替代人工审批",
                        "evidence_ids": ["K4"],
                    }
                ],
                "requires_human_confirmation": True,
                "revised_answer": "助手不能替代人工审批，请由有权限的人员确认。",
            },
        },
    ]
    return [dict(item, repetition=repetition) for repetition in (1, 2) for item in base]


def safe_content(value: Any, api_key: str) -> str:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered.replace(api_key, "[REDACTED]")[:1200]


def response_format(mode: Mode) -> dict[str, Any]:
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "procurement_review",
            "strict": True,
            "schema": ReviewOutput.model_json_schema(mode="serialization"),
        },
    }


async def run_call(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    api_key: str,
    mode: Mode,
    case: dict[str, Any],
) -> dict[str, Any]:
    system = REVIEW_SYSTEM_PROMPT
    if mode == "json_object":
        system = f"{system}\n\n{JSON_OBJECT_INSTRUCTION}"
    payload = {
        "model": "glm-5.2",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(case, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 800,
        "enable_thinking": False,
        "response_format": response_format(mode),
    }
    started = time.perf_counter()
    status_code: int | None = None
    content: Any = None
    finish_reason: Any = None
    error_type: str | None = None
    error_detail: str | None = None
    decoded: Any = None
    http_success = False
    valid_json = False
    top_level_object = False
    schema_valid = False
    try:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Request-Id": f"glm-review-diagnostic-{uuid4().hex}",
            },
            json=payload,
        )
        status_code = response.status_code
        http_success = response.is_success
        try:
            body = response.json()
        except ValueError:
            body = None
            error_type = "RESPONSE_NOT_JSON"
            error_detail = safe_content(response.text, api_key)
        if isinstance(body, dict):
            choices = body.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            if isinstance(choice, dict):
                finish_reason = choice.get("finish_reason")
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
            if not http_success:
                error_type = "HTTP_ERROR"
                error_detail = safe_content(body.get("error") or body, api_key)
        elif error_type is None:
            error_type = "RESPONSE_PROTOCOL_ERROR"

        if http_success:
            if not isinstance(content, str):
                error_type = "CONTENT_NOT_STRING"
            else:
                try:
                    decoded = json.loads(content)
                    valid_json = True
                except json.JSONDecodeError as exc:
                    error_type = "INVALID_JSON"
                    error_detail = str(exc)
                if valid_json:
                    top_level_object = isinstance(decoded, dict)
                    if not top_level_object:
                        error_type = "TOP_LEVEL_NOT_OBJECT"
                    else:
                        try:
                            ReviewOutput.model_validate(decoded)
                            schema_valid = True
                            error_type = None
                            error_detail = None
                        except ValidationError as exc:
                            error_type = "PYDANTIC_VALIDATION_ERROR"
                            error_detail = safe_content(exc.errors(include_input=False), api_key)
    except httpx.TimeoutException as exc:
        error_type = "TIMEOUT"
        error_detail = str(exc)
    except httpx.TransportError as exc:
        error_type = "TRANSPORT_ERROR"
        error_detail = str(exc)

    return {
        "mode": mode,
        "scenario": case["scenario"],
        "repetition": case["repetition"],
        "http_success": http_success,
        "http_status": status_code,
        "raw_content_type": type(content).__name__,
        "raw_content": safe_content(content, api_key),
        "valid_json": valid_json,
        "decoded_json_type": type(decoded).__name__ if valid_json else None,
        "top_level_object": top_level_object,
        "schema_valid": schema_valid,
        "error_type": error_type,
        "error_detail": error_detail,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "enable_thinking": payload["enable_thinking"],
        "finish_reason": finish_reason,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [item["latency_ms"] for item in results]
    total = len(results)
    return {
        "calls": total,
        "http_success_rate": sum(item["http_success"] for item in results) / total,
        "valid_json_rate": sum(item["valid_json"] for item in results) / total,
        "top_level_object_rate": sum(item["top_level_object"] for item in results) / total,
        "schema_validation_rate": sum(item["schema_valid"] for item in results) / total,
        "average_latency_ms": round(statistics.mean(latencies), 2),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
    }


def write_artifact(output_dir: Path, artifact: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"glm-5.2-review-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


async def run(timeout_seconds: float, output_dir: Path) -> Path:
    settings = AgentSettings()
    if not settings.model_base_url or not settings.model_api_key:
        raise RuntimeError("MODEL_BASE_URL/MODEL_API_KEY 未配置")
    api_key = settings.model_api_key.get_secret_value()
    base_url = settings.model_base_url.rstrip("/")
    endpoint = (
        base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    )
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for mode in ("json_schema", "json_object"):
            for index, case in enumerate(synthetic_cases(), start=1):
                result = await run_call(
                    client,
                    endpoint=endpoint,
                    api_key=api_key,
                    mode=mode,
                    case=case,
                )
                results.append(result)
                print(
                    f"[{mode} {index}/10] scenario={case['scenario']} "
                    f"http={result['http_success']} json={result['valid_json']} "
                    f"object={result['top_level_object']} schema={result['schema_valid']} "
                    f"latency_ms={result['latency_ms']} error={result['error_type']}"
                )

    grouped = {
        mode: [item for item in results if item["mode"] == mode]
        for mode in ("json_schema", "json_object")
    }
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "glm-5.2",
        "enable_thinking": False,
        "calls_per_mode": 10,
        "summary": {mode: summarize(items) for mode, items in grouped.items()},
        "results": results,
    }
    output = await asyncio.to_thread(write_artifact, output_dir, artifact)
    print(json.dumps(artifact["summary"], ensure_ascii=False, indent=2))
    print(f"OUTPUT {output}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".artifacts" / "model-diagnostics",
    )
    args = parser.parse_args()
    asyncio.run(run(args.timeout, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
