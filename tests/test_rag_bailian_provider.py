from __future__ import annotations

import json

import httpx
import pytest

from agent_app.rag.aliyun_bailian import (
    BailianEmbeddingProvider,
    BailianRerankProvider,
    RAGProviderError,
)

BASE_URL = "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def embedding_provider(http_client: httpx.Client, **updates: object) -> BailianEmbeddingProvider:
    values = {
        "api_key": "unit-test-placeholder",
        "base_url": BASE_URL,
        "model": "qwen3.7-text-embedding",
        "dimension": 3,
        "timeout_seconds": 10,
        "max_retries": 0,
        "retry_base_seconds": 0,
        "http_client": http_client,
    }
    values.update(updates)
    return BailianEmbeddingProvider(**values)


def rerank_provider(http_client: httpx.Client, **updates: object) -> BailianRerankProvider:
    values = {
        "api_key": "unit-test-placeholder",
        "base_url": BASE_URL,
        "model": "qwen3-rerank",
        "timeout_seconds": 10,
        "max_retries": 0,
        "retry_base_seconds": 0,
        "instruct": "Retrieve passages that answer the query.",
        "http_client": http_client,
    }
    values.update(updates)
    return BailianRerankProvider(**values)


def test_embedding_uses_official_endpoint_payload_and_preserves_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/compatible-mode/v1/embeddings"
        payload = json.loads(request.content)
        assert payload == {
            "model": "qwen3.7-text-embedding",
            "input": ["first", "second"],
            "dimensions": 3,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
                "id": "request-1",
            },
        )

    provider = embedding_provider(client(handler))
    assert provider.encode_dense(["first", "second"], batch_size=20) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    assert provider.last_usage.total_tokens == 2
    assert provider.last_usage.request_id == "request-1"


def test_embedding_splits_batches_at_official_limit() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(len(payload["input"]))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [1.0, 0.0, 0.0]}
                    for index in range(len(payload["input"]))
                ],
                "usage": {"total_tokens": len(payload["input"])},
            },
        )

    provider = embedding_provider(client(handler))
    vectors = provider.encode_dense([f"text-{index}" for index in range(21)], batch_size=128)
    assert len(vectors) == 21
    assert calls == [20, 1]
    assert provider.last_usage.total_tokens == 21


def test_embedding_rejects_wrong_dimension_instead_of_returning_fake_vector() -> None:
    provider = embedding_provider(
        client(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
            )
        )
    )
    with pytest.raises(RAGProviderError, match="维度"):
        provider.encode_dense(["text"])


def test_rerank_uses_dedicated_endpoint_and_maps_scores_to_original_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/compatible-api/v1/reranks"
        payload = json.loads(request.content)
        assert payload["top_n"] == 3
        assert payload["documents"] == ["a", "b", "c"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.1},
                ],
                "usage": {"total_tokens": 12},
                "id": "rerank-request",
            },
        )

    provider = rerank_provider(client(handler))
    assert provider.rerank("query", ["a", "b", "c"]) == [0.5, 0.1, 0.9]
    assert provider.last_usage.total_tokens == 12


def test_auth_error_is_clear_and_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"error": {"code": "invalid_api_key", "message": "invalid"}},
        )

    provider = embedding_provider(client(handler), max_retries=2)
    with pytest.raises(RAGProviderError) as exc_info:
        provider.encode_dense(["text"])
    assert exc_info.value.code == "RAG_API_AUTH_FAILED"
    assert exc_info.value.retryable is False
    assert calls == 1


def test_rate_limit_is_retried_with_a_bound() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, json={"code": "Throttling.RateQuota"})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]},
        )

    provider = embedding_provider(client(handler), max_retries=2)
    assert provider.encode_dense(["text"]) == [[1.0, 0.0, 0.0]]
    assert calls == 3


def test_non_json_upstream_failure_is_retried_but_never_faked() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="temporary upstream failure")

    provider = embedding_provider(client(handler), max_retries=1)
    with pytest.raises(RAGProviderError) as exc_info:
        provider.encode_dense(["text"])
    assert exc_info.value.code == "RAG_API_UPSTREAM_UNAVAILABLE"
    assert exc_info.value.retryable is True
    assert calls == 2
