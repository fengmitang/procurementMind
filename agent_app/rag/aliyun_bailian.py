from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class RAGProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = request_id


@dataclass(frozen=True)
class RAGAPIUsage:
    request_count: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    request_id: str | None = None


def _endpoint(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("百炼 Base URL 必须是有效的 HTTP(S) 地址")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class _BailianHTTPProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("百炼 RAG API Key 未配置")
        self._api_key = api_key
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._owns_client = http_client is None
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(10.0, timeout_seconds),
            pool=min(10.0, timeout_seconds),
        )
        self._client = http_client or httpx.Client(timeout=timeout)
        self.last_usage = RAGAPIUsage()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        request_count = 0
        for attempt in range(self._max_retries + 1):
            request_count += 1
            try:
                response = self._client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    continue
                raise RAGProviderError(
                    "RAG_API_TIMEOUT",
                    "百炼 RAG API 请求超时",
                    retryable=True,
                ) from exc
            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    continue
                raise RAGProviderError(
                    "RAG_API_TRANSPORT_ERROR",
                    "百炼 RAG API 网络请求失败",
                    retryable=True,
                ) from exc

            try:
                body = self._json_body(response)
            except RAGProviderError as exc:
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        self._backoff(attempt, response.headers.get("retry-after"))
                        continue
                    raise self._response_error(response, {}) from exc
                raise
            if response.is_success:
                request_id = self._request_id(body, response)
                usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                total_tokens = usage.get("total_tokens", 0)
                self.last_usage = RAGAPIUsage(
                    request_count=request_count,
                    total_tokens=total_tokens if isinstance(total_tokens, int) else 0,
                    latency_ms=max(0, round((time.perf_counter() - started) * 1000)),
                    request_id=request_id,
                )
                return body
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                self._backoff(attempt, response.headers.get("retry-after"))
                continue
            raise self._response_error(response, body)
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                delay = min(float(retry_after), 30.0)
            except ValueError:
                delay = 0.0
        else:
            delay = 0.0
        if delay <= 0:
            delay = self._retry_base_seconds * (2**attempt) + random.uniform(0, 0.1)
        time.sleep(delay)

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise RAGProviderError(
                "RAG_API_PROTOCOL_ERROR",
                "百炼 RAG API 返回了非 JSON 响应",
                retryable=False,
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, dict):
            raise RAGProviderError(
                "RAG_API_PROTOCOL_ERROR",
                "百炼 RAG API 响应不是 JSON 对象",
                retryable=False,
                status_code=response.status_code,
            )
        return body

    @staticmethod
    def _request_id(body: dict[str, Any], response: httpx.Response) -> str | None:
        value = body.get("id") or body.get("request_id") or response.headers.get("x-request-id")
        return str(value) if value else None

    def _response_error(
        self,
        response: httpx.Response,
        body: dict[str, Any],
    ) -> RAGProviderError:
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        upstream_code = error.get("code") if isinstance(error, dict) else None
        status = response.status_code
        if status in {401, 403}:
            code, message, retryable = (
                "RAG_API_AUTH_FAILED",
                "百炼 RAG API 认证或模型权限校验失败",
                False,
            )
        elif status == 429:
            code, message, retryable = "RAG_API_RATE_LIMITED", "百炼 RAG API 请求被限流", True
        elif status in {408, 500, 502, 503, 504}:
            code, message, retryable = (
                "RAG_API_UPSTREAM_UNAVAILABLE",
                "百炼 RAG API 暂时不可用",
                True,
            )
        elif status == 404:
            code, message, retryable = (
                "RAG_API_ENDPOINT_OR_MODEL_NOT_FOUND",
                "百炼 RAG Endpoint、Workspace 或模型不存在",
                False,
            )
        else:
            code, message, retryable = "RAG_API_REQUEST_REJECTED", "百炼 RAG API 拒绝了请求", False
        if upstream_code:
            message = f"{message}（{upstream_code}）"
        return RAGProviderError(
            code,
            message,
            retryable=retryable,
            status_code=status,
            request_id=self._request_id(body, response),
        )


class BailianEmbeddingProvider(_BailianHTTPProvider):
    MAX_BATCH_SIZE = 20

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
            http_client=http_client,
        )
        self.model = model
        self.dimension = dimension
        self.endpoint = _endpoint(base_url, "/compatible-mode/v1/embeddings")

    @property
    def embedding_cache_identity(self) -> str:
        return f"aliyun-bailian|{self.model}|dense|dimension={self.dimension}|v1"

    def encode_dense(
        self,
        texts: list[str],
        *,
        batch_size: int = 4,
        max_length: int = 512,
    ) -> list[list[float]]:
        del max_length
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 文本不能为空")
        effective_batch_size = min(batch_size, self.MAX_BATCH_SIZE)
        vectors: list[list[float]] = []
        total_tokens = 0
        request_count = 0
        total_latency_ms = 0
        last_request_id: str | None = None
        for offset in range(0, len(texts), effective_batch_size):
            batch = texts[offset : offset + effective_batch_size]
            body = self._post(
                self.endpoint,
                {
                    "model": self.model,
                    "input": batch,
                    "dimensions": self.dimension,
                    "encoding_format": "float",
                },
            )
            vectors.extend(self._vectors(body, len(batch)))
            total_tokens += self.last_usage.total_tokens
            request_count += self.last_usage.request_count
            total_latency_ms += self.last_usage.latency_ms
            last_request_id = self.last_usage.request_id
        self.last_usage = RAGAPIUsage(
            request_count=request_count,
            total_tokens=total_tokens,
            latency_ms=total_latency_ms,
            request_id=last_request_id,
        )
        return vectors

    def _vectors(self, body: dict[str, Any], expected: int) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise RAGProviderError(
                "RAG_EMBEDDING_PROTOCOL_ERROR",
                "百炼 Embedding 响应数量与请求不一致",
                retryable=False,
            )
        ordered: list[list[float] | None] = [None] * expected
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                raise RAGProviderError(
                    "RAG_EMBEDDING_PROTOCOL_ERROR", "百炼 Embedding 响应项无效", retryable=False
                )
            index = item.get("index", position)
            vector = item.get("embedding")
            if (
                not isinstance(index, int)
                or not 0 <= index < expected
                or not isinstance(vector, list)
            ):
                raise RAGProviderError(
                    "RAG_EMBEDDING_PROTOCOL_ERROR", "百炼 Embedding 响应结构无效", retryable=False
                )
            values = [float(value) for value in vector]
            if len(values) != self.dimension or any(not math.isfinite(value) for value in values):
                raise RAGProviderError(
                    "RAG_EMBEDDING_DIMENSION_ERROR",
                    "百炼 Embedding 返回了错误维度或无效数值",
                    retryable=False,
                )
            ordered[index] = values
        if any(vector is None for vector in ordered):
            raise RAGProviderError(
                "RAG_EMBEDDING_PROTOCOL_ERROR", "百炼 Embedding 响应索引不完整", retryable=False
            )
        return [vector for vector in ordered if vector is not None]


class BailianRerankProvider(_BailianHTTPProvider):
    MAX_DOCUMENTS = 500

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        instruct: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
            http_client=http_client,
        )
        self.model = model
        self.instruct = instruct
        self.endpoint = _endpoint(base_url, "/compatible-api/v1/reranks")

    @property
    def reranker_cache_identity(self) -> str:
        return f"aliyun-bailian|{self.model}|{self.instruct}|v1"

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        normalize: bool = True,
        batch_size: int = 4,
    ) -> list[float]:
        del normalize, batch_size
        if (
            not query.strip()
            or not documents
            or any(not document.strip() for document in documents)
        ):
            raise ValueError("Reranker query 和 documents 不能为空")
        if len(documents) > self.MAX_DOCUMENTS:
            raise ValueError(f"qwen3-rerank 单次最多支持 {self.MAX_DOCUMENTS} 个文档")
        body = self._post(
            self.endpoint,
            {
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
                "instruct": self.instruct,
            },
        )
        results = body.get("results")
        if not isinstance(results, list) or len(results) != len(documents):
            raise RAGProviderError(
                "RAG_RERANK_PROTOCOL_ERROR", "百炼 Rerank 响应数量与请求不一致", retryable=False
            )
        scores: list[float | None] = [None] * len(documents)
        for result in results:
            if not isinstance(result, dict):
                raise RAGProviderError(
                    "RAG_RERANK_PROTOCOL_ERROR", "百炼 Rerank 响应项无效", retryable=False
                )
            index = result.get("index")
            score = result.get("relevance_score")
            if (
                not isinstance(index, int)
                or not 0 <= index < len(documents)
                or not isinstance(score, (int, float))
            ):
                raise RAGProviderError(
                    "RAG_RERANK_PROTOCOL_ERROR", "百炼 Rerank 响应结构无效", retryable=False
                )
            value = float(score)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise RAGProviderError(
                    "RAG_RERANK_SCORE_ERROR", "百炼 Rerank 返回了无效相关性分数", retryable=False
                )
            scores[index] = value
        if any(score is None for score in scores):
            raise RAGProviderError(
                "RAG_RERANK_PROTOCOL_ERROR", "百炼 Rerank 响应索引不完整", retryable=False
            )
        return [score for score in scores if score is not None]
