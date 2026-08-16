from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_app.core.config import AgentSettings
from agent_app.device_terms.schemas import (
    DeviceTermCandidate,
    DeviceTermLookupResult,
    DeviceTermLookupStatus,
    DeviceTermPayload,
    DeviceTermSource,
)
from agent_app.device_terms.service import DeviceTermIndexService, DeviceTermSearchService
from agent_app.device_terms.store import QdrantDeviceTermStore
from agent_app.device_terms.text import build_device_term_query, build_device_term_search_text
from agent_app.evaluation.device_terms import (
    DeviceTermEvaluationCase,
    DeviceTermEvaluator,
)

FIXTURE = Path(__file__).parent / "fixtures" / "device_term_evaluation_v0.1.json"


class FakeEmbedding:
    embedding_cache_identity = "fake-device-embedding"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def encode_dense(self, texts: list[str], **_kwargs) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise TimeoutError("embedding timeout")
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(texts)]


class FakeStore:
    def __init__(self) -> None:
        self.recreate_count = 0
        self.upserts: list[tuple[list[DeviceTermPayload], list[list[float]]]] = []
        self.exact: DeviceTermCandidate | None = None
        self.candidates: list[DeviceTermCandidate] = []
        self.fail_search = False
        self.search_professions: list[str] = []
        self.search_limits: list[int] = []

    async def recreate_collection(self) -> None:
        self.recreate_count += 1

    async def upsert_terms(self, payloads, vectors) -> None:
        self.upserts.append((list(payloads), list(vectors)))

    async def find_exact(self, _normalized_name, _profession):
        return self.exact

    async def search(self, _vector, profession, *, limit):
        self.search_professions.append(profession)
        self.search_limits.append(limit)
        if self.fail_search:
            raise RuntimeError("qdrant unavailable")
        return self.candidates[:limit]


def settings(**updates: object) -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="device-term-test-secret",
        **updates,
    )


def test_query_expansion_uses_only_selected_profession_context() -> None:
    expanded = build_device_term_query("功率模块", "UPS")

    assert "设备类型：UPS" in expanded
    assert "模块化UPS" in expanded
    assert "服务器" not in expanded
    assert "核心交换机" not in expanded
    assert "功率模块" in expanded


def test_index_text_is_stable_and_scoped_to_one_profession() -> None:
    text = build_device_term_search_text("UPS模块", "UPS")

    assert text.startswith("设备名称：UPS模块；设备类型：UPS；类别说明：")
    assert "服务器" not in text


@pytest.mark.asyncio
async def test_index_rebuild_deduplicates_and_is_idempotent() -> None:
    store = FakeStore()
    service = DeviceTermIndexService(
        embedding_provider=FakeEmbedding(),
        store=store,
        embedding_batch_size=20,
        embedding_max_length=512,
    )
    sources = [
        DeviceTermSource(device_name="UPS 模块", device_profession="UPS", source_count=2),
        DeviceTermSource(device_name="UPS模块", device_profession="UPS", source_count=3),
        DeviceTermSource(device_name="核心交换机", device_profession="传输", source_count=1),
    ]

    first = await service.rebuild(sources)
    second = await service.rebuild(sources)

    assert len(first) == len(second) == 2
    assert store.recreate_count == 2
    assert len(store.upserts[0][0]) == 2
    ups = next(item for item in first if item.device_profession == "UPS")
    assert ups.normalized_name == "ups模块"
    assert ups.source_count == 5


@pytest.mark.asyncio
async def test_exact_fast_path_skips_embedding() -> None:
    store = FakeStore()
    store.exact = DeviceTermCandidate(
        device_name="UPS模块", device_profession="UPS", exact=True
    )
    embedding = FakeEmbedding()
    service = DeviceTermSearchService(
        embedding_provider=embedding,
        store=store,
        top_k=5,
    )

    result = await service.lookup("UPS模块", "UPS")

    assert result.status is DeviceTermLookupStatus.EXACT
    assert result.exact_match is True
    assert result.selected_names == ["UPS模块"]
    assert embedding.calls == []


@pytest.mark.asyncio
async def test_semantic_search_filters_profession_and_limits_top_k() -> None:
    store = FakeStore()
    store.candidates = [
        DeviceTermCandidate(device_name=f"UPS候选{index}", device_profession="UPS", score=0.9)
        for index in range(8)
    ]
    service = DeviceTermSearchService(
        embedding_provider=FakeEmbedding(), store=store, top_k=3
    )

    result = await service.lookup("功率单元", "UPS")

    assert result.status is DeviceTermLookupStatus.SEMANTIC
    assert len(result.candidates) == 3
    assert store.search_professions == ["UPS"]
    assert store.search_limits == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["embedding", "qdrant"])
async def test_semantic_failure_returns_explicit_fallback(failure: str) -> None:
    store = FakeStore()
    store.fail_search = failure == "qdrant"
    service = DeviceTermSearchService(
        embedding_provider=FakeEmbedding(fail=failure == "embedding"),
        store=store,
        top_k=5,
    )

    result = await service.lookup("功率模块", "UPS")

    assert result.status is DeviceTermLookupStatus.FALLBACK
    assert result.fallback_triggered is True
    assert result.error_code
    assert result.selected_names == []


class FakeQdrantClient:
    def __init__(self) -> None:
        self.queries = []

    async def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    score=0.8,
                    payload=DeviceTermPayload(
                        device_name="UPS模块",
                        device_profession="UPS",
                        normalized_name="ups模块",
                        search_text="设备名称：UPS模块",
                    ).model_dump(mode="json"),
                )
            ]
        )


@pytest.mark.asyncio
async def test_qdrant_search_uses_profession_metadata_filter() -> None:
    client = FakeQdrantClient()
    store = QdrantDeviceTermStore(settings(), client=client)

    candidates = await store.search([0.0] * 1024, "UPS", limit=5)

    query = client.queries[0]
    condition = query["query_filter"].must[0]
    assert condition.key == "device_profession"
    assert condition.match.value == "UPS"
    assert query["limit"] == 5
    assert [item.device_profession for item in candidates] == ["UPS"]


class LifecycleQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.indexes: list[dict] = []

    async def collection_exists(self, _collection_name: str) -> bool:
        return self.exists

    async def create_collection(self, **kwargs):
        self.created.append(kwargs)
        self.exists = True

    async def delete_collection(self, collection_name: str):
        self.deleted.append(collection_name)
        self.exists = False

    async def create_payload_index(self, **kwargs):
        self.indexes.append(kwargs)


@pytest.mark.asyncio
async def test_device_term_collection_is_independent_dense_only_and_rebuildable() -> None:
    client = LifecycleQdrantClient()
    store = QdrantDeviceTermStore(settings(), client=client)

    await store.ensure_collection()
    await store.recreate_collection()

    assert len(client.created) == 2
    assert all(
        item["collection_name"] == "procurement_device_terms" for item in client.created
    )
    assert all("sparse_vectors_config" not in item for item in client.created)
    assert set(client.created[0]["vectors_config"]) == {"dense"}
    assert client.deleted == ["procurement_device_terms"]
    assert {item["field_name"] for item in client.indexes} == {
        "device_name",
        "normalized_name",
        "device_profession",
    }


class EvaluationSearch:
    top_k = 5

    def __init__(self, targets: dict[str, str]) -> None:
        self.targets = targets

    async def lookup(self, query, profession):
        target = self.targets[query]
        return DeviceTermLookupResult(
            status=DeviceTermLookupStatus.SEMANTIC,
            query_term=query,
            device_profession=profession,
            semantic_used=True,
            candidates=[
                DeviceTermCandidate(
                    device_name=target,
                    device_profession=profession,
                    score=0.9,
                )
            ],
            top_k=5,
        )


@pytest.mark.asyncio
async def test_device_term_evaluator_compares_like_and_semantic_metrics() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = [DeviceTermEvaluationCase.model_validate(item) for item in payload["cases"]]
    targets = {case.query: case.target for case in cases}

    report = await DeviceTermEvaluator(EvaluationSearch(targets)).run(cases)

    assert report.total_cases == 8
    assert report.like_hit_rate < 1
    assert report.semantic_top1_hit_rate == 1
    assert report.semantic_top3_hit_rate == 1
    assert report.semantic_top5_hit_rate == 1
