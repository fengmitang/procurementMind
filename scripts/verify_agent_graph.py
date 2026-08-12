import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.graph.schemas import GraphRunRequest  # noqa: E402
from agent_app.graph.service import ProcurementGraphService  # noqa: E402
from agent_app.rag.models import initialize_rag_providers  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from agent_app.rag.retriever import KnowledgeRetriever  # noqa: E402
from agent_app.schemas.backend import (  # noqa: E402
    BackendIdentity,
    CurrentUserData,
    UserRoleData,
)
from app.db.session import async_session_factory, engine  # noqa: E402


async def verify(query: str, role: str) -> dict:
    settings = get_agent_settings()
    models = await asyncio.to_thread(initialize_rag_providers, settings)
    if models is None:
        raise RuntimeError("本地 RAG 模型尚未配置")
    store = QdrantKnowledgeStore(settings)
    try:
        graph = ProcurementGraphService(
            settings,
            knowledge_retriever=KnowledgeRetriever(
                settings=settings,
                session_factory=async_session_factory,
                model_provider=models,
                qdrant_store=store,
            ),
        )
        identity = BackendIdentity(
            platform_type="TEST_PLATFORM",
            platform_user_id="rag-graph-verifier",
        )
        result = await graph.run(
            GraphRunRequest(
                task_id=uuid4(),
                trace_id=f"verify-agent-graph-{uuid4()}",
                conversation_id=1,
                identity=identity,
                current_user=CurrentUserData(
                    employee_id=1,
                    employee_no="VERIFY-RAG",
                    name="RAG 验证用户",
                    mobile=None,
                    status="ACTIVE",
                    platform_type=identity.platform_type,
                    platform_user_id=identity.platform_user_id,
                    roles=[UserRoleData(role_id=1, role_code=role, role_name=role)],
                    buildings=[],
                ),
                message=query,
            )
        )
        return {
            "route": result.route.value,
            "answerable": bool(result.knowledge and result.knowledge.answerable),
            "evidence_sufficient": result.evidence_sufficient,
            "citation_ids": (
                [item.citation_id for item in result.knowledge.citations]
                if result.knowledge
                else []
            ),
            "review_passed": result.review.passed if result.review else None,
            "trace_nodes": [item.name for item in result.trace_events],
            "reply": result.reply,
        }
    finally:
        await store.close()
        if models is not None:
            models.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="验证真实本地 RAG 到 LangGraph 的知识链路")
    parser.add_argument("--query", required=True)
    parser.add_argument("--role", default="APPLICANT")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.query, args.role)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
