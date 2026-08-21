import pytest
from pydantic import BaseModel, ConfigDict

from agent_app.analysis.planner import ModelBackedAnalysisPlanner
from agent_app.models.configuration import ModelRuntimeConfiguration
from agent_app.models.fake import ScriptedModelAdapter
from agent_app.models.protocols import (
    ModelAdapterError,
    ModelMessage,
    ModelPurpose,
    StructuredModelRequest,
    StructuredModelResponse,
)
from agent_app.models.registry import ModelAdapterRegistry
from agent_app.models.runner import StructuredModelRunError, StructuredModelRunner
from agent_app.resilience import AsyncCircuitBreaker


class ExpectedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


def request() -> StructuredModelRequest:
    return StructuredModelRequest(
        purpose=ModelPurpose.ANALYSIS_PLAN,
        trace_id="trace-model",
        messages=[ModelMessage(role="user", content="测试")],
        response_schema=ExpectedOutput.model_json_schema(mode="serialization"),
    )


def response(output: dict, *, model: str = "fake-1") -> StructuredModelResponse:
    return StructuredModelResponse(
        provider="fake",
        model=model,
        output=output,
        latency_ms=1,
    )


@pytest.mark.asyncio
async def test_runner_does_not_retry_invalid_structure_on_primary() -> None:
    adapter = ScriptedModelAdapter([response({"wrong": 1}), response({"value": 2})])

    with pytest.raises(StructuredModelRunError) as exc_info:
        await StructuredModelRunner(
            adapter,
            timeout_seconds=1,
            max_retries=1,
        ).run(request(), ExpectedOutput)

    assert exc_info.value.code == "MODEL_STRUCTURED_OUTPUT_INVALID"
    assert exc_info.value.attempts == 1
    assert len(adapter.requests) == 1


@pytest.mark.asyncio
async def test_runner_does_not_call_fallback_when_primary_schema_is_valid() -> None:
    primary = ScriptedModelAdapter([response({"value": 1}, model="primary-model")])
    fallback = ScriptedModelAdapter([response({"value": 2}, model="fallback-model")])

    output, metadata, attempts = await StructuredModelRunner(
        primary,
        fallback_adapter=fallback,
        primary_model="primary-model",
        timeout_seconds=1,
        max_retries=2,
    ).run(request(), ExpectedOutput)

    assert output.value == 1
    assert metadata.fallback_used is False
    assert metadata.actual_model == "primary-model"
    assert attempts == 1
    assert len(primary.requests) == 1
    assert fallback.requests == []


@pytest.mark.asyncio
async def test_runner_uses_fallback_for_invalid_primary_json() -> None:
    primary = ScriptedModelAdapter(
        [
            ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_INVALID_JSON",
                "模型结构化正文不是有效 JSON",
                retryable=False,
            )
        ]
    )
    fallback = ScriptedModelAdapter([response({"value": 2}, model="fallback-model")])

    output, metadata, attempts = await StructuredModelRunner(
        primary,
        fallback_adapter=fallback,
        primary_model="primary-model",
        timeout_seconds=1,
        max_retries=3,
    ).run(request(), ExpectedOutput)

    assert output.value == 2
    assert metadata.fallback_used is True
    assert metadata.primary_model == "primary-model"
    assert metadata.actual_model == "fallback-model"
    assert "MODEL_STRUCTURED_OUTPUT_INVALID_JSON" in str(metadata.fallback_reason)
    assert attempts == 1
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_content_type", ["array", "string"])
async def test_runner_uses_fallback_for_non_object_primary_json(
    primary_content_type: str,
) -> None:
    primary = ScriptedModelAdapter(
        [
            ModelAdapterError(
                "MODEL_STRUCTURED_OUTPUT_INVALID",
                f"模型结构化结果不是对象：{primary_content_type}",
                retryable=False,
            )
        ]
    )
    fallback = ScriptedModelAdapter([response({"value": 3}, model="fallback-model")])

    output, metadata, _ = await StructuredModelRunner(
        primary,
        fallback_adapter=fallback,
        primary_model="primary-model",
        timeout_seconds=1,
        max_retries=3,
    ).run(request(), ExpectedOutput)

    assert output.value == 3
    assert metadata.fallback_used is True
    assert metadata.actual_model == "fallback-model"
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
async def test_runner_uses_fallback_for_primary_pydantic_validation_failure() -> None:
    primary = ScriptedModelAdapter([response({"wrong": 1}, model="primary-model")])
    fallback = ScriptedModelAdapter([response({"value": 4}, model="fallback-model")])

    output, metadata, attempts = await StructuredModelRunner(
        primary,
        fallback_adapter=fallback,
        primary_model="primary-model",
        timeout_seconds=1,
        max_retries=3,
    ).run(request(), ExpectedOutput)

    assert output.value == 4
    assert metadata.fallback_used is True
    assert metadata.primary_model == "primary-model"
    assert metadata.actual_model == "fallback-model"
    assert "MODEL_STRUCTURED_OUTPUT_INVALID" in str(metadata.fallback_reason)
    assert attempts == 1
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
async def test_runner_fails_when_primary_and_fallback_fail_schema_validation() -> None:
    primary = ScriptedModelAdapter([response({"wrong": 1}, model="primary-model")])
    fallback = ScriptedModelAdapter([response({"also_wrong": 2}, model="fallback-model")])

    with pytest.raises(StructuredModelRunError) as exc_info:
        await StructuredModelRunner(
            primary,
            fallback_adapter=fallback,
            primary_model="primary-model",
            timeout_seconds=1,
            max_retries=3,
        ).run(request(), ExpectedOutput)

    error = exc_info.value
    assert error.code == "MODEL_STRUCTURED_OUTPUT_INVALID"
    assert error.fallback_used is True
    assert error.primary_model == "primary-model"
    assert error.actual_model == "fallback-model"
    assert "MODEL_STRUCTURED_OUTPUT_INVALID" in str(error.fallback_reason)
    assert error.attempts == 1
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
async def test_runner_does_not_retry_non_retryable_adapter_error() -> None:
    adapter = ScriptedModelAdapter(
        [ModelAdapterError("MODEL_AUTH_FAILED", "认证失败", retryable=False)]
    )

    with pytest.raises(StructuredModelRunError) as exc_info:
        await StructuredModelRunner(
            adapter,
            timeout_seconds=1,
            max_retries=3,
        ).run(request(), ExpectedOutput)

    assert exc_info.value.code == "MODEL_AUTH_FAILED"
    assert exc_info.value.attempts == 1


@pytest.mark.asyncio
async def test_runner_uses_fallback_once_for_primary_auth_failure() -> None:
    primary = ScriptedModelAdapter(
        [ModelAdapterError("MODEL_AUTH_FAILED", "认证失败", retryable=False)]
    )
    fallback = ScriptedModelAdapter([response({"value": 5}, model="fallback-model")])

    output, metadata, attempts = await StructuredModelRunner(
        primary,
        fallback_adapter=fallback,
        primary_model="primary-model",
        timeout_seconds=1,
        max_retries=3,
    ).run(request(), ExpectedOutput)

    assert output.value == 5
    assert metadata.primary_model == "primary-model"
    assert metadata.actual_model == "fallback-model"
    assert metadata.fallback_used is True
    assert metadata.fallback_reason == "MODEL_AUTH_FAILED: 认证失败"
    assert attempts == 1
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
async def test_runner_surfaces_fallback_auth_failure_without_retrying_primary() -> None:
    primary = ScriptedModelAdapter(
        [ModelAdapterError("MODEL_AUTH_FAILED", "Primary 认证失败", retryable=False)]
    )
    fallback = ScriptedModelAdapter(
        [ModelAdapterError("MODEL_AUTH_FAILED", "Fallback 认证失败", retryable=False)]
    )

    with pytest.raises(StructuredModelRunError) as exc_info:
        await StructuredModelRunner(
            primary,
            fallback_adapter=fallback,
            primary_model="primary-model",
            timeout_seconds=1,
            max_retries=3,
        ).run(request(), ExpectedOutput)

    error = exc_info.value
    assert error.code == "MODEL_AUTH_FAILED"
    assert error.message == "Fallback 模型失败：Fallback 认证失败"
    assert error.retryable is False
    assert error.fallback_used is True
    assert error.fallback_reason == "MODEL_AUTH_FAILED: Primary 认证失败"
    assert error.attempts == 1
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1


@pytest.mark.asyncio
async def test_runner_bounds_timeout_retries() -> None:
    adapter = ScriptedModelAdapter([response({"value": 1})], delay_seconds=0.05)

    with pytest.raises(StructuredModelRunError) as exc_info:
        await StructuredModelRunner(
            adapter,
            timeout_seconds=0.001,
            max_retries=1,
        ).run(request(), ExpectedOutput)

    assert exc_info.value.code == "MODEL_TIMEOUT"
    assert exc_info.value.attempts == 2


@pytest.mark.asyncio
async def test_runner_rejects_calls_while_model_circuit_is_open() -> None:
    adapter = ScriptedModelAdapter(
        [ModelAdapterError("MODEL_UPSTREAM_ERROR", "上游故障", retryable=True)]
    )
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=30,
    )
    runner = StructuredModelRunner(
        adapter,
        timeout_seconds=1,
        max_retries=0,
        circuit_breaker=breaker,
    )

    with pytest.raises(StructuredModelRunError) as first:
        await runner.run(request(), ExpectedOutput)
    with pytest.raises(StructuredModelRunError) as blocked:
        await runner.run(request(), ExpectedOutput)

    assert first.value.code == "MODEL_UPSTREAM_ERROR"
    assert blocked.value.code == "MODEL_CIRCUIT_OPEN"
    assert len(adapter.requests) == 1


def test_registry_requires_configured_known_provider() -> None:
    registry = ModelAdapterRegistry()
    blank = ModelRuntimeConfiguration(
        provider=None,
        model=None,
        fallback_model=None,
        api_key=None,
        base_url=None,
        configured=False,
    )

    with pytest.raises(ValueError, match="尚未完成"):
        registry.build(blank)

    registry.register("fake", lambda _: ScriptedModelAdapter([]))
    assert registry.providers == ("fake",)
    with pytest.raises(ValueError, match="已注册"):
        registry.register("FAKE", lambda _: ScriptedModelAdapter([]))


@pytest.mark.asyncio
async def test_model_backed_planner_uses_same_strict_plan_schema() -> None:
    plan_output = {
        "goal": "统计采购数量",
        "steps": [
            {
                "step_id": "query",
                "objective": "执行统计",
                "tool": "query_purchase_analytics",
                "arguments": {"query": {"aggregations": ["COUNT"]}},
                "depends_on": [],
                "independent": False,
            }
        ],
        "termination_condition": "完成工具调用",
        "revision_count": 0,
        "query_context": {"aggregations": ["COUNT"]},
    }
    adapter = ScriptedModelAdapter([response(plan_output)])
    planner = ModelBackedAnalysisPlanner(
        StructuredModelRunner(adapter, timeout_seconds=1, max_retries=0),
        "trace-planner",
    )

    plan = await planner.create_plan("统计采购数量")

    assert plan.steps[0].tool.value == "query_purchase_analytics"
    assert adapter.requests[0].trace_id == "trace-planner"
    assert "SQL" in adapter.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_model_backed_planner_rejects_non_whitelisted_tool_arguments() -> None:
    invalid = {
        "goal": "执行查询",
        "steps": [
            {
                "step_id": "query",
                "objective": "执行查询",
                "tool": "query_purchase_analytics",
                "arguments": {"query": {}, "sql": "select * from users"},
                "depends_on": [],
                "independent": False,
            }
        ],
        "termination_condition": "完成",
        "revision_count": 0,
        "query_context": {},
    }
    adapter = ScriptedModelAdapter([response(invalid)])
    planner = ModelBackedAnalysisPlanner(
        StructuredModelRunner(adapter, timeout_seconds=1, max_retries=0),
        "trace-planner",
    )

    with pytest.raises(StructuredModelRunError) as exc_info:
        await planner.create_plan("执行查询")

    assert exc_info.value.code == "MODEL_STRUCTURED_OUTPUT_INVALID"
