import json

import httpx
import pytest
from pydantic import SecretStr

from agent_app.models.configuration import ModelRuntimeConfiguration
from agent_app.models.json_stream import JsonStringFieldDeltaExtractor
from agent_app.models.openai_compatible import OpenAICompatibleStructuredAdapter
from agent_app.models.protocols import ModelMessage, ModelPurpose, StructuredModelRequest
from agent_app.models.role_schemas import ComposeOutput


def test_json_answer_delta_extractor_handles_chunk_and_escape_boundaries() -> None:
    extractor = JsonStringFieldDeltaExtractor("answer")

    values = [
        extractor.feed('{"answer":"采购申请'),
        extractor.feed(r"被驳回后\n请补充"),
        extractor.feed('材料","citations":[]}'),
    ]

    assert "".join(values) == "采购申请被驳回后\n请补充材料"


@pytest.mark.asyncio
async def test_openai_compatible_adapter_forwards_real_structured_deltas() -> None:
    structured = json.dumps(
        {
            "answer": "请修改申请后重新提交。",
            "citations": [],
            "limitations": [],
            "requires_human_confirmation": False,
        },
        ensure_ascii=False,
    )
    pieces = [structured[:12], structured[12:25], structured[25:]]
    events = []
    for piece in pieces:
        event = {
            "id": "stream-1",
            "model": "primary",
            "choices": [{"delta": {"content": piece}}],
        }
        events.append(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
    usage_event = {
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }
    events.append(f"data: {json.dumps(usage_event)}\n\n".encode())
    events.append(b"data: [DONE]\n\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=httpx.ByteStream(b"".join(events)),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleStructuredAdapter(
        ModelRuntimeConfiguration(
            provider="openai_compatible",
            model="primary",
            fallback_model=None,
            api_key=SecretStr("unit-test-key"),
            base_url="https://model.test/v1",
            configured=True,
        ),
        http_client=client,
    )
    deltas: list[str] = []
    request = StructuredModelRequest(
        purpose=ModelPurpose.COMPOSE,
        trace_id="trace-stream",
        messages=[ModelMessage(role="user", content="test")],
        response_schema=ComposeOutput.model_json_schema(mode="serialization"),
    )

    async def collect_delta(value: str) -> None:
        deltas.append(value)

    response = await adapter.complete_structured_stream(request, collect_delta)

    assert "".join(deltas) == structured
    assert response.output["answer"] == "请修改申请后重新提交。"
    assert response.usage.total_tokens == 18
    await client.aclose()
