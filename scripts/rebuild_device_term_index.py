"""Rebuild the independent historical device-name semantic index from MySQL."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.device_terms.service import DeviceTermIndexService  # noqa: E402
from agent_app.device_terms.store import QdrantDeviceTermStore  # noqa: E402
from agent_app.rag.models import initialize_rag_providers  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402
from app.repositories.device_terms import DeviceTermRepository  # noqa: E402


async def run() -> dict:
    settings = get_agent_settings()
    providers = initialize_rag_providers(settings)
    if providers is None:
        raise RuntimeError("Embedding Provider 尚未配置")
    store = QdrantDeviceTermStore(settings)
    try:
        async with async_session_factory() as session:
            sources = await DeviceTermRepository().list_distinct(session)
        payloads = await DeviceTermIndexService(
            embedding_provider=providers.embedding_provider,
            store=store,
            embedding_batch_size=settings.rag_embedding_batch_size,
            embedding_max_length=settings.rag_embedding_max_length,
        ).rebuild(sources)
        return {
            "collection": settings.device_term_qdrant_collection,
            "source_rows": sum(item.source_count for item in sources),
            "distinct_source_terms": len(sources),
            "indexed_terms": len(payloads),
            "embedding_provider": settings.rag_embedding_provider,
            "embedding_model": settings.rag_embedding_model,
            "dense_vector_size": settings.rag_dense_vector_size,
        }
    finally:
        await store.close()
        providers.close()
        await engine.dispose()


def main() -> int:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
