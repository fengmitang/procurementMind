"""Measure live Embedding and Rerank API latency without exposing credentials."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.rag.models import initialize_rag_providers  # noqa: E402

QUERY = "采购申请被驳回后应如何处理？"
DOCUMENTS = [
    "申请被驳回后，申请人应根据驳回意见修改申请内容，然后重新提交审批。",
    "采购经办人应核对供应商资质、报价有效期和黑名单状态。",
    "仓库管理员负责登记设备实收数量、序列号和入库位置。",
    "审批人发现预算或技术参数不完整时，可以驳回采购申请并说明原因。",
    "设备验收完成后应保存验收记录和相关引用材料。",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts" / "performance" / "rag-api-latency.json",
    )
    return parser.parse_args()


def percentile(samples: list[float], quantile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return round(ordered[index], 2)


def run(args: argparse.Namespace) -> dict:
    if args.repeats < 1:
        raise ValueError("repeats 必须大于 0")
    settings = get_agent_settings()
    providers = initialize_rag_providers(settings)
    if providers is None:
        raise RuntimeError("RAG Provider 尚未完整配置")
    embedding_samples: list[float] = []
    rerank_samples: list[float] = []
    embedding_tokens = 0
    rerank_tokens = 0
    vector_dimension = 0
    top_indexes: list[int] = []
    try:
        for _ in range(args.repeats):
            started = time.perf_counter()
            vectors = providers.encode_dense(
                [QUERY],
                batch_size=settings.rag_embedding_batch_size,
                max_length=settings.rag_embedding_max_length,
            )
            embedding_samples.append(round((time.perf_counter() - started) * 1000, 2))
            vector_dimension = len(vectors[0])
            usage = getattr(providers.embedding_provider, "last_usage", None)
            embedding_tokens += int(getattr(usage, "total_tokens", 0))

            started = time.perf_counter()
            scores = providers.rerank(
                QUERY,
                DOCUMENTS,
                batch_size=settings.rag_reranker_batch_size,
            )
            rerank_samples.append(round((time.perf_counter() - started) * 1000, 2))
            usage = getattr(providers.rerank_provider, "last_usage", None)
            rerank_tokens += int(getattr(usage, "total_tokens", 0))
            top_indexes = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    finally:
        providers.close()

    return {
        "embedding": {
            "provider": settings.rag_embedding_provider,
            "model": settings.rag_embedding_model,
            "dimension": vector_dimension,
            "samples_ms": embedding_samples,
            "median_ms": round(statistics.median(embedding_samples), 2),
            "p95_ms": percentile(embedding_samples, 0.95),
            "total_tokens": embedding_tokens,
        },
        "rerank": {
            "provider": settings.rag_rerank_provider,
            "model": settings.rag_rerank_model,
            "candidate_count": len(DOCUMENTS),
            "samples_ms": rerank_samples,
            "median_ms": round(statistics.median(rerank_samples), 2),
            "p95_ms": percentile(rerank_samples, 0.95),
            "total_tokens": rerank_tokens,
            "top_indexes": top_indexes,
        },
    }


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
