"""Benchmark CPU embedding and reranker settings without changing retrieval data."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import AgentSettings  # noqa: E402
from agent_app.rag.models import initialize_local_rag_models  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from agent_app.rag.retriever import KnowledgeRetriever  # noqa: E402
from agent_app.rag.schemas import ChildChunkPayload, RetrievalFilters  # noqa: E402

QUERY = "采购申请被楼长驳回后应该怎么办？"


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, nargs="+", default=[2, 4, 6, 8])
    parser.add_argument("--fusion-top-k", type=int, nargs="+", default=[12, 8, 6])
    parser.add_argument("--batch-size", type=int, nargs="+", default=[4, 8, 12])
    parser.add_argument("--embedding-repeats", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "performance" / "rag-cpu-matrix.json",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict:
    settings = AgentSettings()
    models = initialize_local_rag_models(settings)
    if models is None:
        raise RuntimeError("RAG local models are not configured")
    store = QdrantKnowledgeStore(settings)
    try:
        embedding_results = []
        vectors: dict[int, list[float]] = {}
        for threads in args.threads:
            torch.set_num_threads(threads)
            samples = []
            for _ in range(args.embedding_repeats):
                started = time.perf_counter()
                vector = models.encode_dense(
                    [QUERY],
                    batch_size=settings.rag_embedding_batch_size,
                    max_length=settings.rag_embedding_max_length,
                )[0]
                samples.append(elapsed_ms(started))
                vectors[threads] = vector
            embedding_results.append(
                {
                    "threads": threads,
                    "samples_ms": samples,
                    "median_ms": round(statistics.median(samples), 2),
                }
            )

        best_embedding_threads = min(embedding_results, key=lambda item: item["median_ms"])[
            "threads"
        ]
        query_filter = store.build_filter(RetrievalFilters(allowed_roles=["APPLICANT"]))
        fusion_points = await store.query_hybrid(
            vectors[best_embedding_threads],
            QUERY,
            query_filter=query_filter,
            dense_limit=settings.rag_dense_top_k,
            sparse_limit=settings.rag_sparse_top_k,
            fusion_limit=max(args.fusion_top_k),
            rrf_k=settings.rag_rrf_k,
        )
        payloads = [ChildChunkPayload.model_validate(point.payload) for point in fusion_points]
        documents = [KnowledgeRetriever._rerank_text(payload) for payload in payloads]

        thread_results = []
        for threads in args.threads:
            torch.set_num_threads(threads)
            started = time.perf_counter()
            models.rerank(
                QUERY,
                documents,
                normalize=True,
                batch_size=max(args.batch_size),
            )
            thread_results.append({"threads": threads, "duration_ms": elapsed_ms(started)})
        best_rerank_threads = min(thread_results, key=lambda item: item["duration_ms"])["threads"]

        torch.set_num_threads(best_rerank_threads)
        matrix = []
        for fusion_top_k in args.fusion_top_k:
            selected_documents = documents[:fusion_top_k]
            selected_payloads = payloads[:fusion_top_k]
            for batch_size in args.batch_size:
                started = time.perf_counter()
                scores = models.rerank(
                    QUERY,
                    selected_documents,
                    normalize=True,
                    batch_size=batch_size,
                )
                duration_ms = elapsed_ms(started)
                ranked = sorted(
                    zip(selected_payloads, scores, strict=True),
                    key=lambda item: item[1],
                    reverse=True,
                )
                matrix.append(
                    {
                        "fusion_top_k": fusion_top_k,
                        "batch_size": batch_size,
                        "threads": best_rerank_threads,
                        "duration_ms": duration_ms,
                        "top_parent_ids": [item.parent_id for item, _ in ranked[:5]],
                        "top_scores": [round(float(score), 6) for _, score in ranked[:5]],
                    }
                )
        return {
            "query": QUERY,
            "device": models.device,
            "embedding": embedding_results,
            "embedding_best_threads": best_embedding_threads,
            "reranker_threads": thread_results,
            "reranker_best_threads": best_rerank_threads,
            "matrix": matrix,
        }
    finally:
        await store.close()


def main() -> int:
    args = parse_args()
    payload = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
