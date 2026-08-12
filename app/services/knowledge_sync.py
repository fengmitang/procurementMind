from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agent_app.rag.documents import MarkdownKnowledgeParser, ParsedKnowledgeDocument
from agent_app.rag.qdrant import QdrantKnowledgeStore
from app.models.knowledge import KnowledgeDocument, KnowledgeParent
from app.repositories.knowledge import KnowledgeRepository


class DenseEmbeddingProvider(Protocol):
    def encode_dense(
        self, texts: list[str], *, batch_size: int, max_length: int
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class DocumentSyncResult:
    document_id: str
    source_path: str
    action: str
    parent_count: int = 0
    child_count: int = 0


@dataclass(frozen=True)
class KnowledgeSyncReport:
    results: tuple[DocumentSyncResult, ...]

    @property
    def rebuilt(self) -> int:
        return sum(result.action == "rebuilt" for result in self.results)

    @property
    def skipped(self) -> int:
        return sum(result.action == "skipped" for result in self.results)

    @property
    def retired(self) -> int:
        return sum(result.action == "retired" for result in self.results)

    @property
    def parent_count(self) -> int:
        return sum(result.parent_count for result in self.results)

    @property
    def child_count(self) -> int:
        return sum(result.child_count for result in self.results)


class KnowledgeSyncService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        parser: MarkdownKnowledgeParser,
        embedding_provider: DenseEmbeddingProvider,
        qdrant_store: QdrantKnowledgeStore,
        repository: KnowledgeRepository | None = None,
        embedding_batch_size: int = 4,
        embedding_max_length: int = 512,
    ) -> None:
        self.session_factory = session_factory
        self.parser = parser
        self.embedding_provider = embedding_provider
        self.qdrant_store = qdrant_store
        self.repository = repository or KnowledgeRepository()
        self.embedding_batch_size = embedding_batch_size
        self.embedding_max_length = embedding_max_length
        provider_identity = getattr(
            embedding_provider,
            "embedding_cache_identity",
            type(embedding_provider).__name__,
        )
        contract = getattr(qdrant_store, "contract", None)
        collection_name = getattr(contract, "collection_name", type(qdrant_store).__name__)
        self.index_identity = f"{provider_identity}|collection={collection_name}"

    async def sync_document(
        self,
        path: Path,
        *,
        source_path: str,
        force: bool = False,
    ) -> DocumentSyncResult:
        parsed = self.parser.parse(path, source_path=source_path)
        if not force and await self._is_current(parsed):
            return DocumentSyncResult(
                document_id=parsed.document.document_id,
                source_path=source_path,
                action="skipped",
            )

        embedding_texts = [child.embedding_text for child in parsed.children]
        dense_vectors = await asyncio.to_thread(
            self.embedding_provider.encode_dense,
            embedding_texts,
            batch_size=self.embedding_batch_size,
            max_length=self.embedding_max_length,
        )
        await self._save_indexing_snapshot(parsed)
        try:
            await self.qdrant_store.delete_document_children(parsed.document.document_id)
            await self.qdrant_store.upsert_children(
                [child.payload for child in parsed.children],
                dense_vectors,
                embedding_texts,
            )
        except Exception as exc:
            await self._mark_index_error(parsed.document.document_id, str(exc))
            raise
        await self._mark_index_ready(parsed.document.document_id)
        return DocumentSyncResult(
            document_id=parsed.document.document_id,
            source_path=source_path,
            action="rebuilt",
            parent_count=len(parsed.parents),
            child_count=len(parsed.children),
        )

    async def rebuild_all(self, source_directory: Path) -> KnowledgeSyncReport:
        sources = await asyncio.to_thread(self._source_files, source_directory)
        if not sources:
            raise ValueError(f"知识源目录中没有 Markdown：{source_directory}")
        results: list[DocumentSyncResult] = []
        active_source_paths: set[str] = set()
        for path, source_path in sources:
            active_source_paths.add(source_path)
            results.append(await self.sync_document(path, source_path=source_path, force=True))
        results.extend(await self._retire_missing(active_source_paths))
        return KnowledgeSyncReport(results=tuple(results))

    @staticmethod
    def _source_files(source_directory: Path) -> list[tuple[Path, str]]:
        resolved = source_directory.resolve()
        cwd = Path.cwd()
        return [(path, path.relative_to(cwd).as_posix()) for path in sorted(resolved.glob("*.md"))]

    async def _is_current(self, parsed: ParsedKnowledgeDocument) -> bool:
        async with self.session_factory() as session:
            existing = await self.repository.get_document(session, parsed.document.document_id)
            return bool(
                existing
                and existing.content_hash == parsed.document.content_hash
                and existing.index_status == "READY"
                and existing.status == parsed.document.status
                and (existing.metadata_json or {}).get("_rag_index_identity") == self.index_identity
            )

    async def _save_indexing_snapshot(self, parsed: ParsedKnowledgeDocument) -> None:
        async with self.session_factory() as session, session.begin():
            existing = await self.repository.get_document(
                session, parsed.document.document_id, for_update=True
            )
            by_source = await self.repository.get_document_by_source_path(
                session, parsed.document.source_path, for_update=True
            )
            if by_source is not None and by_source.document_id != parsed.document.document_id:
                raise ValueError(f"source_path 已属于其他知识文档：{parsed.document.source_path}")
            document = existing or KnowledgeDocument(document_id=parsed.document.document_id)
            self._apply_document(document, parsed)
            if existing is None:
                session.add(document)
            parents = [self._parent_model(parent.record) for parent in parsed.parents]
            await self.repository.replace_parents(session, parsed.document.document_id, parents)

    async def _mark_index_ready(self, document_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            document = await self.repository.get_document(session, document_id, for_update=True)
            if document is None:
                raise RuntimeError(f"知识文档索引完成时记录不存在：{document_id}")
            document.index_status = "READY"
            document.indexed_at = datetime.now().replace(microsecond=0)
            document.index_error = None

    async def _mark_index_error(self, document_id: str, error: str) -> None:
        async with self.session_factory() as session, session.begin():
            document = await self.repository.get_document(session, document_id, for_update=True)
            if document is not None:
                document.index_status = "ERROR"
                document.index_error = error[:4000]

    async def _retire_missing(self, active_source_paths: set[str]) -> Sequence[DocumentSyncResult]:
        async with self.session_factory() as session:
            missing = [
                document
                for document in await self.repository.list_documents(session)
                if document.source_path not in active_source_paths and document.status != "RETIRED"
            ]
        results: list[DocumentSyncResult] = []
        for document in missing:
            async with self.session_factory() as session, session.begin():
                current = await self.repository.get_document(
                    session, document.document_id, for_update=True
                )
                if current is None:
                    continue
                current.status = "RETIRED"
                current.index_status = "INDEXING"
                current.index_error = None
                await self.repository.delete_parents(session, current.document_id)
            try:
                await self.qdrant_store.delete_document_children(document.document_id)
            except Exception as exc:
                await self._mark_index_error(document.document_id, str(exc))
                raise
            await self._mark_index_ready(document.document_id)
            results.append(
                DocumentSyncResult(
                    document_id=document.document_id,
                    source_path=document.source_path,
                    action="retired",
                )
            )
        return results

    def _apply_document(self, model: KnowledgeDocument, parsed: ParsedKnowledgeDocument) -> None:
        record = parsed.document
        model.title = record.title
        model.document_type = record.document_type
        model.version = record.version
        model.status = record.status
        model.source_path = record.source_path
        model.content_hash = record.content_hash
        model.effective_at = record.effective_at
        model.allowed_roles = record.allowed_roles
        model.device_scopes = record.device_scopes
        model.metadata_json = {
            **(record.metadata or {}),
            "_rag_index_identity": self.index_identity,
        }
        model.index_status = "INDEXING"
        model.index_error = None

    @staticmethod
    def _parent_model(record) -> KnowledgeParent:
        return KnowledgeParent(
            parent_id=record.parent_id,
            document_id=record.document_id,
            ordinal=record.ordinal,
            title=record.title,
            section_path=record.section_path,
            topic=record.topic,
            chunk_type=record.chunk_type,
            version=record.version,
            status=record.status,
            content=record.content,
            content_hash=record.content_hash,
            source_start_line=record.source_start_line,
            source_end_line=record.source_end_line,
            metadata_json=record.metadata,
        )
