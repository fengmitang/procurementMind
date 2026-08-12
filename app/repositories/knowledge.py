import hashlib
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeParent


class KnowledgeRepository:
    async def get_ready_knowledge_version(self, session: AsyncSession) -> str:
        rows = (
            await session.execute(
                select(
                    KnowledgeDocument.document_id,
                    KnowledgeDocument.version,
                    KnowledgeDocument.content_hash,
                    KnowledgeDocument.indexed_at,
                )
                .where(
                    KnowledgeDocument.status == "ACTIVE",
                    KnowledgeDocument.index_status == "READY",
                )
                .order_by(KnowledgeDocument.document_id)
            )
        ).all()
        payload = "\n".join(
            "|".join(
                (
                    str(document_id),
                    str(version),
                    str(content_hash),
                    indexed_at.isoformat() if indexed_at is not None else "",
                )
            )
            for document_id, version, content_hash, indexed_at in rows
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def list_documents(self, session: AsyncSession) -> Sequence[KnowledgeDocument]:
        return (
            await session.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.source_path))
        ).all()

    async def get_document(
        self, session: AsyncSession, document_id: str, *, for_update: bool = False
    ) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(KnowledgeDocument.document_id == document_id)
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_document_by_source_path(
        self, session: AsyncSession, source_path: str, *, for_update: bool = False
    ) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(KnowledgeDocument.source_path == source_path)
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def list_parents(
        self, session: AsyncSession, document_id: str
    ) -> Sequence[KnowledgeParent]:
        return (
            await session.scalars(
                select(KnowledgeParent)
                .where(KnowledgeParent.document_id == document_id)
                .order_by(KnowledgeParent.ordinal)
            )
        ).all()

    async def get_parents_by_ids(
        self, session: AsyncSession, parent_ids: Sequence[str]
    ) -> Sequence[KnowledgeParent]:
        if not parent_ids:
            return []
        parents = (
            await session.scalars(
                select(KnowledgeParent).where(KnowledgeParent.parent_id.in_(parent_ids))
            )
        ).all()
        positions = {parent_id: index for index, parent_id in enumerate(parent_ids)}
        return sorted(parents, key=lambda parent: positions[parent.parent_id])

    async def get_ready_parents_by_ids(
        self, session: AsyncSession, parent_ids: Sequence[str]
    ) -> Sequence[KnowledgeParent]:
        if not parent_ids:
            return []
        parents = (
            await session.scalars(
                select(KnowledgeParent)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.document_id == KnowledgeParent.document_id,
                )
                .where(
                    KnowledgeParent.parent_id.in_(parent_ids),
                    KnowledgeParent.status == "ACTIVE",
                    KnowledgeDocument.status == "ACTIVE",
                    KnowledgeDocument.index_status == "READY",
                )
            )
        ).all()
        positions = {parent_id: index for index, parent_id in enumerate(parent_ids)}
        return sorted(parents, key=lambda parent: positions[parent.parent_id])

    async def replace_parents(
        self,
        session: AsyncSession,
        document_id: str,
        parents: Sequence[KnowledgeParent],
    ) -> None:
        await session.execute(
            delete(KnowledgeParent).where(KnowledgeParent.document_id == document_id)
        )
        session.add_all(parents)

    async def delete_parents(self, session: AsyncSession, document_id: str) -> None:
        await session.execute(
            delete(KnowledgeParent).where(KnowledgeParent.document_id == document_id)
        )
