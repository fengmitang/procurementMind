"""Evaluate SQL LIKE versus domain-enhanced device-term embedding retrieval."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from qdrant_client import AsyncQdrantClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.device_terms.schemas import DeviceTermSource  # noqa: E402
from agent_app.device_terms.service import (  # noqa: E402
    DeviceTermIndexService,
    DeviceTermSearchService,
)
from agent_app.device_terms.store import QdrantDeviceTermStore  # noqa: E402
from agent_app.evaluation.device_terms import (  # noqa: E402
    DeviceTermEvaluationCase,
    DeviceTermEvaluator,
)
from agent_app.rag.models import initialize_rag_providers  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "device_term_evaluation_v0.1.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def run(path: Path) -> dict:
    content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    payload = json.loads(content)
    terms = [DeviceTermSource.model_validate(item) for item in payload["terms"]]
    cases = [DeviceTermEvaluationCase.model_validate(item) for item in payload["cases"]]
    settings = get_agent_settings().model_copy(
        update={"device_term_qdrant_collection": "procurement_device_terms_evaluation"}
    )
    providers = initialize_rag_providers(settings)
    if providers is None:
        raise RuntimeError("Embedding Provider 尚未配置")
    client = AsyncQdrantClient(location=":memory:")
    store = QdrantDeviceTermStore(settings, client=client)
    try:
        await DeviceTermIndexService(
            embedding_provider=providers.embedding_provider,
            store=store,
            embedding_batch_size=settings.rag_embedding_batch_size,
            embedding_max_length=settings.rag_embedding_max_length,
        ).rebuild(terms)
        report = await DeviceTermEvaluator(
            DeviceTermSearchService(
                embedding_provider=providers.embedding_provider,
                store=store,
                top_k=settings.device_term_top_k,
                embedding_batch_size=settings.rag_embedding_batch_size,
                embedding_max_length=settings.rag_embedding_max_length,
            )
        ).run(cases)
        result = report.model_dump(mode="json")
        result.update(
            {
                "embedding_provider": settings.rag_embedding_provider,
                "embedding_model": settings.rag_embedding_model,
                "indexed_terms": len(terms),
            }
        )
        return result
    finally:
        await client.close()
        providers.close()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run(args.cases.resolve()))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
