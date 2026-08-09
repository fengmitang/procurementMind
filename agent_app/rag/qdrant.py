from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from qdrant_client import AsyncQdrantClient, models

from agent_app.core.config import AgentSettings
from agent_app.rag.schemas import ChildChunkPayload, RetrievalFilters


class QdrantSchemaError(RuntimeError):
    """Raised when an existing collection is incompatible with the RAG contract."""


class QdrantCollectionClient(Protocol):
    async def collection_exists(self, collection_name: str) -> bool: ...

    async def create_collection(self, **kwargs: object) -> object: ...

    async def get_collection(self, collection_name: str) -> object: ...

    async def create_payload_index(self, **kwargs: object) -> object: ...

    async def delete(self, **kwargs: object) -> object: ...

    async def upsert(self, **kwargs: object) -> object: ...

    async def query_points(self, **kwargs: object) -> object: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class KnowledgeCollectionContract:
    collection_name: str
    dense_vector_name: str = "dense"
    sparse_vector_name: str = "bm25"
    dense_vector_size: int = 1024


class QdrantKnowledgeStore:
    PAYLOAD_INDEXES = {
        "child_id": models.PayloadSchemaType.KEYWORD,
        "parent_id": models.PayloadSchemaType.KEYWORD,
        "document_id": models.PayloadSchemaType.KEYWORD,
        "chunk_type": models.PayloadSchemaType.KEYWORD,
        "version": models.PayloadSchemaType.KEYWORD,
        "status": models.PayloadSchemaType.KEYWORD,
        "allowed_roles": models.PayloadSchemaType.KEYWORD,
        "device_scopes": models.PayloadSchemaType.KEYWORD,
    }

    def __init__(
        self,
        settings: AgentSettings,
        *,
        client: QdrantCollectionClient | None = None,
    ) -> None:
        self.contract = KnowledgeCollectionContract(
            collection_name=settings.qdrant_collection,
            dense_vector_name=settings.rag_dense_vector_name,
            sparse_vector_name=settings.rag_sparse_vector_name,
            dense_vector_size=settings.rag_dense_vector_size,
        )
        self._owns_client = client is None
        self.upsert_batch_size = settings.qdrant_upsert_batch_size
        self.client = client or AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=settings.qdrant_timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.close()

    async def ensure_collection(self) -> None:
        name = self.contract.collection_name
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                collection_name=name,
                vectors_config={
                    self.contract.dense_vector_name: models.VectorParams(
                        size=self.contract.dense_vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    self.contract.sparse_vector_name: models.SparseVectorParams(
                        modifier=models.Modifier.IDF
                    )
                },
            )
        else:
            await self._validate_collection()

        for field_name, field_schema in self.PAYLOAD_INDEXES.items():
            await self.client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    async def delete_document_children(self, document_id: str) -> None:
        await self.client.delete(
            collection_name=self.contract.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def upsert_children(
        self,
        payloads: Sequence[ChildChunkPayload],
        dense_vectors: Sequence[Sequence[float]],
        embedding_texts: Sequence[str],
    ) -> None:
        if not (len(payloads) == len(dense_vectors) == len(embedding_texts)):
            raise ValueError("Child、Dense vector 与 Embedding 文本数量必须一致")
        points: list[models.PointStruct] = []
        for payload, dense_vector, embedding_text in zip(
            payloads, dense_vectors, embedding_texts, strict=True
        ):
            if len(dense_vector) != self.contract.dense_vector_size:
                raise ValueError(
                    f"Child {payload.child_id} Dense 维度不是 {self.contract.dense_vector_size}"
                )
            points.append(
                models.PointStruct(
                    id=payload.child_id,
                    vector={
                        self.contract.dense_vector_name: list(dense_vector),
                        self.contract.sparse_vector_name: models.Document(
                            text=embedding_text,
                            model="qdrant/bm25",
                            options={"tokenizer": "multilingual"},
                        ),
                    },
                    payload=payload.model_dump(mode="json"),
                )
            )
        for offset in range(0, len(points), self.upsert_batch_size):
            await self.client.upsert(
                collection_name=self.contract.collection_name,
                points=points[offset : offset + self.upsert_batch_size],
                wait=True,
            )

    async def query_dense(
        self,
        query_vector: Sequence[float],
        *,
        query_filter: models.Filter,
        limit: int,
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            collection_name=self.contract.collection_name,
            query=list(query_vector),
            using=self.contract.dense_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(response.points)

    async def query_sparse(
        self,
        query_text: str,
        *,
        query_filter: models.Filter,
        limit: int,
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            collection_name=self.contract.collection_name,
            query=self._bm25_document(query_text),
            using=self.contract.sparse_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(response.points)

    async def query_hybrid(
        self,
        query_vector: Sequence[float],
        query_text: str,
        *,
        query_filter: models.Filter,
        dense_limit: int,
        sparse_limit: int,
        fusion_limit: int,
        rrf_k: int,
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            collection_name=self.contract.collection_name,
            prefetch=[
                models.Prefetch(
                    query=list(query_vector),
                    using=self.contract.dense_vector_name,
                    filter=query_filter,
                    limit=dense_limit,
                ),
                models.Prefetch(
                    query=self._bm25_document(query_text),
                    using=self.contract.sparse_vector_name,
                    filter=query_filter,
                    limit=sparse_limit,
                ),
            ],
            query=models.RrfQuery(rrf=models.Rrf(k=rrf_k)),
            query_filter=query_filter,
            limit=fusion_limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(response.points)

    @staticmethod
    def build_filter(filters: RetrievalFilters) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(key="status", match=models.MatchValue(value=filters.status))
        ]
        for key, values in (
            ("document_id", filters.document_ids),
            ("version", filters.versions),
            ("chunk_type", filters.chunk_types),
            ("allowed_roles", filters.allowed_roles),
        ):
            if values:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(values))))
        device_conditions: list[models.Condition] = [
            models.IsEmptyCondition(is_empty=models.PayloadField(key="device_scopes"))
        ]
        if filters.device_scopes:
            device_conditions.append(
                models.FieldCondition(
                    key="device_scopes",
                    match=models.MatchAny(any=list(filters.device_scopes)),
                )
            )
        must.append(models.Filter(should=device_conditions))
        return models.Filter(must=must)

    @staticmethod
    def _bm25_document(text: str) -> models.Document:
        if not text.strip():
            raise ValueError("BM25 query 不能为空")
        return models.Document(
            text=text,
            model="qdrant/bm25",
            options={"tokenizer": "multilingual"},
        )

    async def _validate_collection(self) -> None:
        info = await self.client.get_collection(self.contract.collection_name)
        vectors = info.config.params.vectors
        dense = vectors.get(self.contract.dense_vector_name) if isinstance(vectors, dict) else None
        sparse_vectors = info.config.params.sparse_vectors or {}
        sparse = sparse_vectors.get(self.contract.sparse_vector_name)
        if dense is None or dense.size != self.contract.dense_vector_size:
            raise QdrantSchemaError("现有 Qdrant collection 的 Dense 向量名称或维度与配置不一致")
        if dense.distance != models.Distance.COSINE:
            raise QdrantSchemaError("现有 Qdrant collection 未使用 Cosine Dense 距离")
        if sparse is None or sparse.modifier != models.Modifier.IDF:
            raise QdrantSchemaError("现有 Qdrant collection 缺少 IDF Sparse/BM25 向量")
