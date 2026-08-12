"""Run the fixed real-model RAG retrieval evaluation and save all retrieval traces."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.evaluation.rag import (  # noqa: E402
    RAGEvaluationBaseline,
    RAGEvaluationReport,
    RAGEvaluator,
    compare_rag_with_baseline,
    load_rag_evaluation_cases,
)
from agent_app.rag.models import initialize_rag_providers  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from agent_app.rag.retriever import KnowledgeRetriever  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "rag_evaluation_v0.1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "rag-evaluation" / "rag-evaluation-v0.1.json",
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "docs" / "baseline" / "rag-evaluation-baseline-v0.1.json",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict:
    settings = get_agent_settings()
    local_models = initialize_rag_providers(settings)
    if local_models is None:
        raise RuntimeError("Embedding/Reranker 本地模型尚未完整配置")
    store = QdrantKnowledgeStore(settings)
    retriever = KnowledgeRetriever(
        settings=settings,
        session_factory=async_session_factory,
        model_provider=local_models,
        qdrant_store=store,
    )
    try:
        await store.ensure_collection()
        report = await RAGEvaluator(evaluation_k=args.k).run(
            load_rag_evaluation_cases(args.cases),
            retriever,
        )
        payload = report.model_dump(mode="json")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload
    finally:
        await store.close()
        if local_models is not None:
            local_models.close()
        await engine.dispose()


def summary(payload: dict, output: Path, baseline_path: Path) -> dict:
    report = RAGEvaluationReport.model_validate(payload)
    baseline = RAGEvaluationBaseline.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    comparison = compare_rag_with_baseline(report, baseline)
    return {
        "report_version": payload["report_version"],
        "total_cases": payload["total_cases"],
        "evaluation_k": payload["evaluation_k"],
        "route_accuracy": payload["route_accuracy"],
        "citation_accuracy": payload["citation_accuracy"],
        "negative_accuracy": payload["negative_accuracy"],
        "strategies": payload["strategies"],
        "trace_output": str(output),
        "baseline": comparison.model_dump(mode="json"),
    }


def main() -> int:
    args = parse_args()
    payload = asyncio.run(run(args))
    result = summary(payload, args.output, args.baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["baseline"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
