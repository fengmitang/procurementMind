from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from qdrant_client import models

import app.models  # noqa: F401
from agent_app.core.config import AgentSettings
from agent_app.rag.qdrant import QdrantKnowledgeStore, QdrantSchemaError
from agent_app.rag.schemas import ChildChunkPayload, KnowledgeParentRecord, RetrievalFilters
from app.db.base import Base


def settings(**updates: object) -> AgentSettings:
    return AgentSettings(
        _env_file=None,
        identity_gateway_secret="knowledge-storage-test-secret",
        **updates,
    )


class FakeQdrantClient:
    def __init__(self, *, exists: bool = False, info: object | None = None) -> None:
        self.exists = exists
        self.info = info
        self.created: list[dict] = []
        self.indexes: list[dict] = []
        self.deletes: list[dict] = []
        self.upserts: list[dict] = []
        self.queries: list[dict] = []
        self.query_responses: list[object] = []
        self.closed = False

    async def collection_exists(self, collection_name: str) -> bool:
        assert collection_name == "procurement_knowledge_child"
        return self.exists

    async def create_collection(self, **kwargs: object) -> bool:
        self.created.append(kwargs)
        return True

    async def get_collection(self, collection_name: str) -> object:
        assert collection_name == "procurement_knowledge_child"
        return self.info

    async def create_payload_index(self, **kwargs: object) -> bool:
        self.indexes.append(kwargs)
        return True

    async def delete(self, **kwargs: object) -> bool:
        self.deletes.append(kwargs)
        return True

    async def upsert(self, **kwargs: object) -> bool:
        self.upserts.append(kwargs)
        return True

    async def query_points(self, **kwargs: object) -> object:
        self.queries.append(kwargs)
        if self.query_responses:
            return self.query_responses.pop(0)
        return SimpleNamespace(points=[])

    async def close(self) -> None:
        self.closed = True


def collection_info(
    *, dense_size: int = 1024, sparse_modifier: models.Modifier = models.Modifier.IDF
) -> object:
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={
                    "dense": models.VectorParams(
                        size=dense_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors={"bm25": models.SparseVectorParams(modifier=sparse_modifier)},
            )
        )
    )


@pytest.mark.asyncio
async def test_qdrant_collection_uses_dense_and_idf_sparse_vectors() -> None:
    client = FakeQdrantClient()
    store = QdrantKnowledgeStore(settings(), client=client)

    await store.ensure_collection()

    assert len(client.created) == 1
    dense = client.created[0]["vectors_config"]["dense"]
    sparse = client.created[0]["sparse_vectors_config"]["bm25"]
    assert dense.size == 1024
    assert dense.distance == models.Distance.COSINE
    assert sparse.modifier == models.Modifier.IDF
    assert {item["field_name"] for item in client.indexes} == {
        "child_id",
        "parent_id",
        "document_id",
        "chunk_type",
        "version",
        "status",
        "allowed_roles",
        "device_scopes",
    }


@pytest.mark.asyncio
async def test_existing_compatible_collection_is_not_recreated() -> None:
    client = FakeQdrantClient(exists=True, info=collection_info())
    store = QdrantKnowledgeStore(settings(), client=client)

    await store.ensure_collection()

    assert client.created == []
    assert len(client.indexes) == len(store.PAYLOAD_INDEXES)


@pytest.mark.asyncio
async def test_existing_incompatible_collection_fails_without_replacement() -> None:
    client = FakeQdrantClient(exists=True, info=collection_info(dense_size=384))
    store = QdrantKnowledgeStore(settings(), client=client)

    with pytest.raises(QdrantSchemaError, match="维度"):
        await store.ensure_collection()

    assert client.created == []


def test_knowledge_mysql_metadata_matches_storage_contract() -> None:
    document = Base.metadata.tables["knowledge_document"]
    parent = Base.metadata.tables["knowledge_parent"]

    assert document.primary_key.columns.keys() == ["document_id"]
    assert parent.primary_key.columns.keys() == ["parent_id"]
    assert parent.c.document_id.foreign_keys
    foreign_key = next(iter(parent.c.document_id.foreign_keys))
    assert foreign_key.target_fullname == "knowledge_document.document_id"
    assert foreign_key.ondelete == "CASCADE"
    assert {
        "title",
        "document_type",
        "version",
        "status",
        "source_path",
        "content_hash",
        "effective_at",
        "updated_at",
    }.issubset(document.c.keys())
    assert {"section_path", "topic", "chunk_type", "content"}.issubset(parent.c.keys())


def test_child_payload_keeps_complete_source_metadata() -> None:
    payload = ChildChunkPayload(
        child_id="child-1",
        parent_id="parent-1",
        document_id="document-1",
        title="采购申请字段填写规范",
        section_path=["需求人申请阶段", "设备名称"],
        topic="设备名称填写要求",
        chunk_type="field",
        version="1.0",
        status="ACTIVE",
        content="设备名称应使用能够识别采购对象的标准名称。",
        source_path="knowledge/source/03-fields.md",
        source_start_line=40,
        source_end_line=48,
    )

    assert payload.section_path[-1] == "设备名称"
    assert payload.status == "ACTIVE"


def test_parent_rejects_reversed_source_lines() -> None:
    with pytest.raises(ValidationError, match="source_end_line"):
        KnowledgeParentRecord(
            parent_id="parent-1",
            document_id="document-1",
            ordinal=0,
            title="字段规范",
            section_path=["字段规范"],
            topic="字段规范",
            chunk_type="field",
            version="1.0",
            status="ACTIVE",
            content="完整字段规范。",
            content_hash="a" * 64,
            source_start_line=20,
            source_end_line=10,
        )


def test_qdrant_configuration_replaces_legacy_chroma_setting() -> None:
    value = settings(
        qdrant_url="http://qdrant:6333",
        qdrant_collection="procurement_knowledge_child",
    )
    example = Path(".env.example").read_text(encoding="utf-8")

    assert value.qdrant_url == "http://qdrant:6333"
    assert value.rag_dense_vector_size == 1024
    assert "QDRANT_URL=" in example
    assert "CHROMA_" not in example


@pytest.mark.asyncio
async def test_qdrant_replaces_only_one_documents_children_with_dense_and_bm25() -> None:
    client = FakeQdrantClient()
    store = QdrantKnowledgeStore(settings(qdrant_upsert_batch_size=1), client=client)
    payload = ChildChunkPayload(
        child_id="4f79b9a6-263d-523b-b73c-13adb0c44251",
        parent_id="parent-1",
        document_id="CGXT-ZY-01",
        title="采购流程指引",
        section_path=["草稿与申请提交", "提交前检查"],
        topic="提交前检查",
        chunk_type="rule",
        version="1.0",
        status="ACTIVE",
        content="提交前应补齐必填字段。",
        source_path="knowledge/source/01.md",
        source_start_line=10,
        source_end_line=12,
    )

    await store.delete_document_children("CGXT-ZY-01")
    await store.upsert_children([payload], [[0.0] * 1024], ["采购提交前检查"])

    condition = client.deletes[0]["points_selector"].filter.must[0]
    assert condition.key == "document_id"
    assert condition.match.value == "CGXT-ZY-01"
    point = client.upserts[0]["points"][0]
    assert point.id == payload.child_id
    assert len(point.vector["dense"]) == 1024
    assert point.vector["bm25"].model == "qdrant/bm25"
    assert point.vector["bm25"].options == {"tokenizer": "multilingual"}
    assert point.payload["parent_id"] == "parent-1"


@pytest.mark.asyncio
async def test_qdrant_rejects_wrong_dense_dimension_before_upsert() -> None:
    client = FakeQdrantClient()
    store = QdrantKnowledgeStore(settings(), client=client)
    payload = ChildChunkPayload(
        child_id="4f79b9a6-263d-523b-b73c-13adb0c44251",
        parent_id="parent-1",
        document_id="CGXT-ZY-01",
        title="采购流程指引",
        section_path=["提交"],
        topic="提交",
        chunk_type="rule",
        version="1.0",
        status="ACTIVE",
        content="提交要求。",
        source_path="knowledge/source/01.md",
        source_start_line=1,
        source_end_line=2,
    )

    with pytest.raises(ValueError, match="Dense 维度"):
        await store.upsert_children([payload], [[0.0] * 384], ["提交要求"])

    assert client.upserts == []


@pytest.mark.asyncio
async def test_qdrant_hybrid_query_uses_server_side_rrf_and_shared_filter() -> None:
    client = FakeQdrantClient()
    store = QdrantKnowledgeStore(settings(), client=client)
    filters = store.build_filter(
        RetrievalFilters(
            document_ids=["CGXT-ZY-01"],
            allowed_roles=["APPLICANT"],
            device_scopes=["server"],
        )
    )

    await store.query_hybrid(
        [0.0] * 1024,
        "采购申请如何提交",
        query_filter=filters,
        dense_limit=15,
        sparse_limit=15,
        fusion_limit=12,
        rrf_k=60,
    )

    query = client.queries[0]
    assert query["query"].rrf.k == 60
    assert query["prefetch"][0].using == "dense"
    assert query["prefetch"][1].using == "bm25"
    assert query["prefetch"][1].query.model == "qdrant/bm25"
    assert query["prefetch"][1].query.options == {"tokenizer": "multilingual"}
    assert query["prefetch"][0].filter == filters
    assert query["prefetch"][1].filter == filters
    assert query["query_filter"] == filters


def test_qdrant_metadata_filter_includes_visibility_and_global_device_scope() -> None:
    filters = QdrantKnowledgeStore.build_filter(
        RetrievalFilters(
            versions=["1.0"],
            chunk_types=["faq"],
            allowed_roles=["PURCHASER", "ADMIN"],
            device_scopes=["network"],
        )
    )

    assert filters.must is not None
    conditions = list(filters.must)
    assert conditions[0].key == "status"
    assert conditions[0].match.value == "ACTIVE"
    fields = {condition.key for condition in conditions[1:4]}
    assert fields == {"version", "chunk_type", "allowed_roles"}
    device_filter = conditions[4]
    assert device_filter.should[0].is_empty.key == "device_scopes"
    assert device_filter.should[1].match.any == ["network"]
