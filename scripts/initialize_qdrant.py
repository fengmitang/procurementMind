"""Create or validate the procurement knowledge Qdrant collection."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402


async def initialize() -> None:
    store = QdrantKnowledgeStore(get_agent_settings())
    try:
        await store.ensure_collection()
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(initialize())
