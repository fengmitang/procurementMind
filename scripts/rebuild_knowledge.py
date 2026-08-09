"""Incrementally rebuild one knowledge document or fully rebuild all sources."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_app.core.config import get_agent_settings  # noqa: E402
from agent_app.rag.documents import MarkdownKnowledgeParser  # noqa: E402
from agent_app.rag.models import initialize_local_rag_models  # noqa: E402
from agent_app.rag.qdrant import QdrantKnowledgeStore  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402
from app.services.knowledge_sync import (  # noqa: E402
    DocumentSyncResult,
    KnowledgeSyncReport,
    KnowledgeSyncService,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="全量重建并处理已移除源文件")
    mode.add_argument("--document", type=Path, help="增量同步指定 Markdown")
    parser.add_argument(
        "--force",
        action="store_true",
        help="单文档 content hash 未变化时仍重新构建",
    )
    return parser.parse_args()


def result_payload(report: KnowledgeSyncReport) -> dict:
    return {
        "rebuilt": report.rebuilt,
        "skipped": report.skipped,
        "retired": report.retired,
        "parents": report.parent_count,
        "children": report.child_count,
        "documents": [result.__dict__ for result in report.results],
    }


async def run(args: argparse.Namespace) -> dict:
    settings = get_agent_settings()
    source_directory = settings.knowledge_source_directory.resolve()
    models = initialize_local_rag_models(settings)
    if models is None:
        raise RuntimeError("Embedding/Reranker 本地模型尚未完整配置")
    store = QdrantKnowledgeStore(settings)
    service = KnowledgeSyncService(
        session_factory=async_session_factory,
        parser=MarkdownKnowledgeParser(
            child_max_chars=settings.rag_child_max_chars,
            child_hard_max_chars=settings.rag_child_hard_max_chars,
        ),
        embedding_provider=models,
        qdrant_store=store,
        embedding_batch_size=settings.rag_embedding_batch_size,
        embedding_max_length=settings.rag_embedding_max_length,
    )
    try:
        await store.ensure_collection()
        if args.all:
            report = await service.rebuild_all(source_directory)
        else:
            path = args.document.resolve()
            if path.suffix.lower() != ".md" or not path.is_file():
                raise ValueError(f"指定知识文档不是有效 Markdown：{path}")
            if not path.is_relative_to(source_directory):
                raise ValueError(f"指定知识文档不在知识源目录内：{path}")
            source_path = path.relative_to(Path.cwd()).as_posix()
            result: DocumentSyncResult = await service.sync_document(
                path,
                source_path=source_path,
                force=args.force,
            )
            report = KnowledgeSyncReport(results=(result,))
        return result_payload(report)
    finally:
        await store.close()
        await engine.dispose()


def main() -> int:
    args = parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
