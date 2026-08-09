"""Run one real Dense + BM25 + RRF + Reranker knowledge retrieval."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.rag.models import initialize_local_rag_models  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from agent_app.rag.retriever import KnowledgeRetriever  # noqa: E402
from agent_app.rag.schemas import RetrievalFilters  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="要检索的知识问题")
    parser.add_argument(
        "--role",
        action="append",
        required=True,
        help="调用者角色代码，可重复，例如 APPLICANT",
    )
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--device-scope", action="append", default=[])
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict:
    settings = get_agent_settings()
    local_models = initialize_local_rag_models(settings)
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
        result = await retriever.retrieve(
            args.query,
            filters=RetrievalFilters(
                document_ids=args.document_id,
                allowed_roles=args.role,
                device_scopes=args.device_scope,
            ),
        )
        return {
            "query": result.original_query,
            "rewritten_query": result.rewritten_query,
            "candidate_counts": {
                "dense": len(result.dense_candidates),
                "sparse": len(result.sparse_candidates),
                "fusion": len(result.fusion_candidates),
                "reranked": len(result.evidences),
            },
            "answerable": result.answerable,
            "abstention_reason": result.abstention_reason,
            "evidences": [
                {
                    "child_id": evidence.payload.child_id,
                    "parent_id": evidence.payload.parent_id,
                    "document_id": evidence.payload.document_id,
                    "section_path": evidence.payload.section_path,
                    "chunk_type": evidence.payload.chunk_type,
                    "fusion_score": evidence.fusion_score,
                    "rerank_score": evidence.rerank_score,
                    "parent_expanded": evidence.parent_expanded,
                    "context_truncated": evidence.context_truncated,
                }
                for evidence in result.evidences
            ],
            "context_chars": len(result.context),
            "citations": [citation.model_dump(mode="json") for citation in result.citations],
            "trace_id": result.trace.trace_id,
        }
    finally:
        await store.close()
        await engine.dispose()


def main() -> int:
    print(json.dumps(asyncio.run(run(parse_args())), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
