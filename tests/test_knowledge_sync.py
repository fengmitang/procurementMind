from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from agent_app.rag.documents import MarkdownKnowledgeParser
from app.db.session import async_session_factory
from app.models.knowledge import KnowledgeDocument, KnowledgeParent
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge_sync import KnowledgeSyncService


def markdown(document_id: str) -> str:
    return f"""# 测试采购规则

| 项目 | 内容 |
|---|---|
| 文件编号 | {document_id} |
| 版本号 | 1.0 |
| 版本状态 | 试行 |
| 适用对象 | 全体系统用户 |
| 生效日期 | 2026年8月7日 |
| 文件性质 | 内部业务指引 |

## 第一章 申请

### 第一条 提交要求

提交前应补齐设备名称、数量和申请原因。
"""


class FakeEmbedding:
    def __init__(self) -> None:
        self.calls = 0

    def encode_dense(
        self, texts: list[str], *, batch_size: int, max_length: int
    ) -> list[list[float]]:
        self.calls += 1
        assert batch_size == 2
        assert max_length == 512
        return [[1.0] + [0.0] * 1023 for _ in texts]


class FakeQdrantStore:
    def __init__(self, *, fail_upsert: bool = False) -> None:
        self.fail_upsert = fail_upsert
        self.deleted: list[str] = []
        self.upserted: list[str] = []

    async def delete_document_children(self, document_id: str) -> None:
        self.deleted.append(document_id)

    async def upsert_children(self, payloads, dense_vectors, embedding_texts) -> None:
        if self.fail_upsert:
            raise RuntimeError("qdrant unavailable")
        assert len(payloads) == len(dense_vectors) == len(embedding_texts)
        self.upserted.extend(payload.child_id for payload in payloads)


async def cleanup(document_id: str) -> None:
    async with async_session_factory() as session, session.begin():
        await session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.document_id == document_id)
        )


def service(embedding: FakeEmbedding, store: FakeQdrantStore) -> KnowledgeSyncService:
    return KnowledgeSyncService(
        session_factory=async_session_factory,
        parser=MarkdownKnowledgeParser(),
        embedding_provider=embedding,
        qdrant_store=store,
        embedding_batch_size=2,
        embedding_max_length=512,
    )


@pytest.mark.asyncio
async def test_incremental_sync_skips_unchanged_ready_document(tmp_path: Path) -> None:
    document_id = "TEST-KNOWLEDGE-INCREMENTAL"
    path = tmp_path / "incremental.md"
    path.write_text(markdown(document_id), encoding="utf-8")
    embedding = FakeEmbedding()
    store = FakeQdrantStore()
    sync = service(embedding, store)
    await cleanup(document_id)
    try:
        first = await sync.sync_document(path, source_path="knowledge/source/test-incremental.md")
        second = await sync.sync_document(path, source_path="knowledge/source/test-incremental.md")

        assert first.action == "rebuilt"
        assert first.parent_count == 1
        assert first.child_count == 1
        assert second.action == "skipped"
        assert embedding.calls == 1
        async with async_session_factory() as session:
            document = await KnowledgeRepository().get_document(session, document_id)
            assert document is not None
            assert document.index_status == "READY"
            assert document.index_error is None
            repository = KnowledgeRepository()
            parents = await repository.list_parents(session, document_id)
            assert len(parents) == 1
            ready_parents = await repository.get_ready_parents_by_ids(
                session, [parents[0].parent_id]
            )
            assert len(ready_parents) == 1
    finally:
        await cleanup(document_id)


@pytest.mark.asyncio
async def test_failed_qdrant_write_is_retryable_and_not_marked_ready(tmp_path: Path) -> None:
    document_id = "TEST-KNOWLEDGE-RECOVERY"
    path = tmp_path / "recovery.md"
    path.write_text(markdown(document_id), encoding="utf-8")
    embedding = FakeEmbedding()
    store = FakeQdrantStore(fail_upsert=True)
    sync = service(embedding, store)
    await cleanup(document_id)
    try:
        with pytest.raises(RuntimeError, match="qdrant unavailable"):
            await sync.sync_document(path, source_path="knowledge/source/test-recovery.md")
        async with async_session_factory() as session:
            failed = await KnowledgeRepository().get_document(session, document_id)
            assert failed is not None
            assert failed.index_status == "ERROR"
            assert "qdrant unavailable" in failed.index_error
            parents = await KnowledgeRepository().list_parents(session, document_id)
            assert parents
            assert (
                await KnowledgeRepository().get_ready_parents_by_ids(
                    session, [parents[0].parent_id]
                )
                == []
            )

        store.fail_upsert = False
        recovered = await sync.sync_document(path, source_path="knowledge/source/test-recovery.md")
        assert recovered.action == "rebuilt"
        async with async_session_factory() as session:
            ready = await KnowledgeRepository().get_document(session, document_id)
            assert ready is not None
            assert ready.index_status == "READY"
            assert ready.index_error is None
    finally:
        await cleanup(document_id)


@pytest.mark.asyncio
async def test_missing_source_is_retired_and_parent_content_removed(tmp_path: Path) -> None:
    document_id = "TEST-KNOWLEDGE-RETIRED"
    path = tmp_path / "retired.md"
    path.write_text(markdown(document_id), encoding="utf-8")
    embedding = FakeEmbedding()
    store = FakeQdrantStore()
    sync = service(embedding, store)
    await cleanup(document_id)
    try:
        await sync.sync_document(path, source_path="knowledge/source/test-retired.md")
        async with async_session_factory() as session:
            documents = await KnowledgeRepository().list_documents(session)
            retained_sources = {
                document.source_path
                for document in documents
                if document.document_id != document_id
            }
        retired = await sync._retire_missing(retained_sources)

        assert [item.document_id for item in retired] == [document_id]
        assert retired[0].action == "retired"
        assert store.deleted.count(document_id) == 2
        async with async_session_factory() as session:
            document = await KnowledgeRepository().get_document(session, document_id)
            parent_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeParent)
                .where(KnowledgeParent.document_id == document_id)
            )
            assert document is not None
            assert document.status == "RETIRED"
            assert document.index_status == "READY"
            assert parent_count == 0
    finally:
        await cleanup(document_id)
