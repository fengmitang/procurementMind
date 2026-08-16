from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid5

from qdrant_client import AsyncQdrantClient, models

from agent_app.core.config import AgentSettings
from agent_app.device_terms.schemas import DeviceTermCandidate, DeviceTermPayload
from app.schemas.procurement import DeviceType

_POINT_NAMESPACE = UUID("2baa65bf-6f31-53a4-b10a-e63c175f4518")


class DeviceTermCollectionClient(Protocol):
    async def collection_exists(self, collection_name: str) -> bool: ...

    async def create_collection(self, **kwargs: object) -> object: ...

    async def delete_collection(self, collection_name: str) -> object: ...

    async def get_collection(self, collection_name: str) -> object: ...

    async def create_payload_index(self, **kwargs: object) -> object: ...

    async def upsert(self, **kwargs: object) -> object: ...

    async def query_points(self, **kwargs: object) -> object: ...

    async def scroll(self, **kwargs: object) -> tuple[list[object], object]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class DeviceTermCollectionContract:
    collection_name: str
    dense_vector_name: str = "dense"
    dense_vector_size: int = 1024


class QdrantDeviceTermStore:
    PAYLOAD_INDEXES = {
        "device_name": models.PayloadSchemaType.KEYWORD,
        "normalized_name": models.PayloadSchemaType.KEYWORD,
        "device_profession": models.PayloadSchemaType.KEYWORD,
    }

    def __init__(
        self,
        settings: AgentSettings,
        *,
        client: DeviceTermCollectionClient | None = None,
    ) -> None:
        self.contract = DeviceTermCollectionContract(
            collection_name=settings.device_term_qdrant_collection,
            dense_vector_name=settings.rag_dense_vector_name,
            dense_vector_size=settings.rag_dense_vector_size,
        )
        self.upsert_batch_size = settings.qdrant_upsert_batch_size
        self._owns_client = client is None
        self.client = client or AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=settings.qdrant_timeout_seconds,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.close()

    async def ensure_collection(self) -> None:
        if not await self.client.collection_exists(self.contract.collection_name):
            await self._create_collection()
        else:
            await self._validate_collection()
        await self._ensure_payload_indexes()

    async def recreate_collection(self) -> None:
        if await self.client.collection_exists(self.contract.collection_name):
            await self.client.delete_collection(self.contract.collection_name)
        await self._create_collection()
        await self._ensure_payload_indexes()

    async def upsert_terms(
        self,
        payloads: Sequence[DeviceTermPayload],
        dense_vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(payloads) != len(dense_vectors):
            raise ValueError("设备术语与 Dense vector 数量必须一致")
        points: list[models.PointStruct] = []
        for payload, vector in zip(payloads, dense_vectors, strict=True):
            if len(vector) != self.contract.dense_vector_size:
                raise ValueError(
                    f"设备术语 {payload.device_name} Dense 维度不是 "
                    f"{self.contract.dense_vector_size}"
                )
            point_id = str(
                uuid5(
                    _POINT_NAMESPACE,
                    f"{payload.device_profession}\0{payload.normalized_name}",
                )
            )
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={self.contract.dense_vector_name: list(vector)},
                    payload=payload.model_dump(mode="json"),
                )
            )
        for offset in range(0, len(points), self.upsert_batch_size):
            await self.client.upsert(
                collection_name=self.contract.collection_name,
                points=points[offset : offset + self.upsert_batch_size],
                wait=True,
            )

    async def find_exact(
        self,
        normalized_name: str,
        device_profession: DeviceType,
    ) -> DeviceTermCandidate | None:
        records, _ = await self.client.scroll(
            collection_name=self.contract.collection_name,
            scroll_filter=self._filter(device_profession, normalized_name=normalized_name),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return None
        payload = DeviceTermPayload.model_validate(records[0].payload)
        return DeviceTermCandidate(
            device_name=payload.device_name,
            device_profession=payload.device_profession,
            exact=True,
        )

    async def search(
        self,
        vector: Sequence[float],
        device_profession: DeviceType,
        *,
        limit: int,
    ) -> list[DeviceTermCandidate]:
        response = await self.client.query_points(
            collection_name=self.contract.collection_name,
            query=list(vector),
            using=self.contract.dense_vector_name,
            query_filter=self._filter(device_profession),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        candidates = []
        for point in response.points:
            payload = DeviceTermPayload.model_validate(point.payload)
            if payload.device_profession != device_profession:
                continue
            candidates.append(
                DeviceTermCandidate(
                    device_name=payload.device_name,
                    device_profession=payload.device_profession,
                    score=float(point.score),
                )
            )
        return candidates[:limit]

    async def _create_collection(self) -> None:
        await self.client.create_collection(
            collection_name=self.contract.collection_name,
            vectors_config={
                self.contract.dense_vector_name: models.VectorParams(
                    size=self.contract.dense_vector_size,
                    distance=models.Distance.COSINE,
                )
            },
        )

    async def _ensure_payload_indexes(self) -> None:
        for field_name, field_schema in self.PAYLOAD_INDEXES.items():
            await self.client.create_payload_index(
                collection_name=self.contract.collection_name,
                field_name=field_name,
                field_schema=field_schema,
                wait=True,
            )

    async def _validate_collection(self) -> None:
        info = await self.client.get_collection(self.contract.collection_name)
        vectors = info.config.params.vectors
        dense = vectors.get(self.contract.dense_vector_name) if isinstance(vectors, dict) else None
        if dense is None or dense.size != self.contract.dense_vector_size:
            raise RuntimeError("设备术语 Collection 的 Dense 向量名称或维度与配置不一致")
        if dense.distance != models.Distance.COSINE:
            raise RuntimeError("设备术语 Collection 未使用 Cosine Dense 距离")

    @staticmethod
    def _filter(
        device_profession: DeviceType,
        *,
        normalized_name: str | None = None,
    ) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(
                key="device_profession",
                match=models.MatchValue(value=device_profession),
            )
        ]
        if normalized_name is not None:
            must.append(
                models.FieldCondition(
                    key="normalized_name",
                    match=models.MatchValue(value=normalized_name),
                )
            )
        return models.Filter(must=must)
