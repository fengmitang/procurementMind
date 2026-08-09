from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_app.rag.schemas import (
    ChildChunkPayload,
    ChunkType,
    KnowledgeDocumentRecord,
    KnowledgeParentRecord,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")
_CHINESE_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_TOPIC_PREFIX = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇0-9]+(?:条|章|节)|[一二三四五六七八九十0-9]+[、.])\s*"
)
_SKIPPED_SECTIONS = {"关键词索引", "版本修订记录"}
_ROLE_CODES = {
    "需求人": "APPLICANT",
    "楼长": "BUILDING_MANAGER",
    "采购员": "PURCHASER",
    "仓库管理员": "WAREHOUSE_MANAGER",
    "系统管理员": "ADMIN",
}


@dataclass(frozen=True)
class ParsedChild:
    payload: ChildChunkPayload
    embedding_text: str


@dataclass(frozen=True)
class ParsedParent:
    record: KnowledgeParentRecord
    children: tuple[ParsedChild, ...]


@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    document: KnowledgeDocumentRecord
    parents: tuple[ParsedParent, ...]

    @property
    def children(self) -> tuple[ParsedChild, ...]:
        return tuple(child for parent in self.parents for child in parent.children)


@dataclass(frozen=True)
class _HeadingLocation:
    level: int
    title: str
    line_index: int


class MarkdownKnowledgeParser:
    def __init__(self, *, child_max_chars: int = 800, child_hard_max_chars: int = 2000) -> None:
        if child_max_chars < 100 or child_hard_max_chars < child_max_chars:
            raise ValueError("Child 长度配置无效")
        self.child_max_chars = child_max_chars
        self.child_hard_max_chars = child_hard_max_chars

    def parse(self, path: Path, *, source_path: str | None = None) -> ParsedKnowledgeDocument:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        headings = self._headings(lines)
        if not headings or headings[0].level != 1:
            raise ValueError(f"知识文档缺少一级标题：{path}")

        title = headings[0].title
        metadata = self._metadata(lines, headings)
        document_id = metadata.get("文件编号")
        version = metadata.get("版本号")
        if not document_id or not version:
            raise ValueError(f"知识文档缺少文件编号或版本号：{path}")
        relative_path = source_path or path.as_posix()
        status = self._document_status(metadata.get("版本状态", ""))
        document = KnowledgeDocumentRecord(
            document_id=document_id,
            title=title,
            document_type=metadata.get("文件性质", "知识文档"),
            version=version,
            status=status,
            source_path=relative_path,
            content_hash=hashlib.sha256(raw).hexdigest(),
            effective_at=self._effective_at(metadata.get("生效日期")),
            allowed_roles=self._allowed_roles(metadata.get("适用对象", "")),
            metadata={"source_metadata": metadata},
        )

        parents: list[ParsedParent] = []
        ordinal = 0
        level_two = [heading for heading in headings if heading.level == 2]
        for section_index, section in enumerate(level_two):
            section_end = (
                level_two[section_index + 1].line_index
                if section_index + 1 < len(level_two)
                else len(lines)
            )
            if section.title in _SKIPPED_SECTIONS:
                continue
            children_headings = [
                heading
                for heading in headings
                if heading.level == 3 and section.line_index < heading.line_index < section_end
            ]
            if not children_headings:
                parsed = self._build_parent(
                    document,
                    lines,
                    ordinal,
                    [section.title],
                    section,
                    section_end,
                )
                if parsed is not None:
                    parents.append(parsed)
                    ordinal += 1
                continue

            preamble = self._meaningful_body(
                lines, section.line_index + 1, children_headings[0].line_index
            )
            if preamble:
                parsed = self._build_parent(
                    document,
                    lines,
                    ordinal,
                    [section.title],
                    section,
                    children_headings[0].line_index,
                )
                if parsed is not None:
                    parents.append(parsed)
                    ordinal += 1

            for child_index, child_heading in enumerate(children_headings):
                child_end = (
                    children_headings[child_index + 1].line_index
                    if child_index + 1 < len(children_headings)
                    else section_end
                )
                parsed = self._build_parent(
                    document,
                    lines,
                    ordinal,
                    [section.title, child_heading.title],
                    child_heading,
                    child_end,
                )
                if parsed is not None:
                    parents.append(parsed)
                    ordinal += 1

        if not parents:
            raise ValueError(f"知识文档未解析出有效业务主题：{path}")
        return ParsedKnowledgeDocument(document=document, parents=tuple(parents))

    @staticmethod
    def _headings(lines: list[str]) -> list[_HeadingLocation]:
        result: list[_HeadingLocation] = []
        for index, line in enumerate(lines):
            match = _HEADING.match(line)
            if match:
                result.append(
                    _HeadingLocation(
                        level=len(match.group(1)),
                        title=match.group(2).strip(),
                        line_index=index,
                    )
                )
        return result

    @staticmethod
    def _metadata(lines: list[str], headings: list[_HeadingLocation]) -> dict[str, str]:
        first_section = next(
            (heading.line_index for heading in headings if heading.level == 2), len(lines)
        )
        result: dict[str, str] = {}
        for line in lines[:first_section]:
            match = _TABLE_ROW.match(line.strip())
            if not match:
                continue
            key, value = match.groups()
            if key not in {"项目", "---"} and value != "---":
                result[key] = value
        return result

    def _build_parent(
        self,
        document: KnowledgeDocumentRecord,
        lines: list[str],
        ordinal: int,
        section_path: list[str],
        heading: _HeadingLocation,
        end_index: int,
    ) -> ParsedParent | None:
        content = self._meaningful_body(lines, heading.line_index + 1, end_index)
        if not content:
            return None
        end_line = end_index
        while end_line > heading.line_index + 1 and not lines[end_line - 1].strip():
            end_line -= 1
        topic = _TOPIC_PREFIX.sub("", heading.title).strip() or heading.title
        chunk_type = self._chunk_type(document, section_path, topic)
        parent_id = self._stable_uuid(document.document_id, "parent", *section_path)
        parent = KnowledgeParentRecord(
            parent_id=parent_id,
            document_id=document.document_id,
            ordinal=ordinal,
            title=heading.title,
            section_path=section_path,
            topic=topic,
            chunk_type=chunk_type,
            version=document.version,
            status=document.status,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_start_line=heading.line_index + 1,
            source_end_line=end_line,
            metadata={},
        )
        child_contents = self._split_child_content(content, chunk_type)
        children: list[ParsedChild] = []
        for child_ordinal, child_content in enumerate(child_contents):
            child_id = self._stable_uuid(parent_id, "child", str(child_ordinal))
            child_topic = topic if len(child_contents) == 1 else f"{topic}（{child_ordinal + 1}）"
            payload = ChildChunkPayload(
                child_id=child_id,
                parent_id=parent_id,
                document_id=document.document_id,
                title=document.title,
                section_path=section_path,
                topic=child_topic,
                chunk_type=chunk_type,
                version=document.version,
                status=document.status,
                content=child_content,
                source_path=document.source_path,
                source_start_line=parent.source_start_line,
                source_end_line=parent.source_end_line,
                allowed_roles=document.allowed_roles,
                device_scopes=document.device_scopes,
            )
            children.append(
                ParsedChild(
                    payload=payload,
                    embedding_text=self._embedding_text(document, payload),
                )
            )
        return ParsedParent(record=parent, children=tuple(children))

    def _split_child_content(self, content: str, chunk_type: ChunkType) -> list[str]:
        if len(content) <= self.child_max_chars:
            return [content]
        if chunk_type in {"field", "faq", "risk"} and len(content) <= self.child_hard_max_chars:
            return [content]

        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        chunks: list[str] = []
        current = ""
        for block in blocks:
            candidate = f"{current}\n\n{block}".strip() if current else block
            if current and len(candidate) > self.child_max_chars:
                chunks.append(current)
                current = block
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks or [content]

    @staticmethod
    def _meaningful_body(lines: list[str], start: int, end: int) -> str:
        body = "\n".join(lines[start:end]).strip()
        return body

    @staticmethod
    def _embedding_text(document: KnowledgeDocumentRecord, payload: ChildChunkPayload) -> str:
        return (
            f"文档标题：{document.title}\n"
            f"章节路径：{' > '.join(payload.section_path)}\n"
            f"主题：{payload.topic}\n"
            f"正文：{payload.content}"
        )

    @staticmethod
    def _chunk_type(
        document: KnowledgeDocumentRecord, section_path: list[str], topic: str
    ) -> ChunkType:
        combined = " ".join([document.document_type, *section_path, topic])
        if "常见问题" in document.document_type or topic.endswith("？"):
            return "faq"
        if "字段" in document.title or "填写规范" in document.title:
            return "field"
        if "风险" in combined or "核实事项" in combined:
            return "risk"
        if "操作手册" in document.document_type or "操作" in combined:
            return "step"
        if len(section_path) == 1:
            return "section"
        return "rule"

    @staticmethod
    def _stable_uuid(*parts: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "procurement-mind/" + "/".join(parts)))

    @staticmethod
    def _document_status(value: str) -> str:
        normalized = value.strip().upper()
        if normalized in {"废止", "失效", "RETIRED"}:
            return "RETIRED"
        if normalized in {"草稿", "DRAFT"}:
            return "DRAFT"
        return "ACTIVE"

    @staticmethod
    def _effective_at(value: str | None) -> datetime | None:
        if not value:
            return None
        match = _CHINESE_DATE.match(value.strip())
        if not match:
            raise ValueError(f"无法解析知识文档生效日期：{value}")
        return datetime(*(int(part) for part in match.groups()))

    @staticmethod
    def _allowed_roles(value: str) -> list[str]:
        if "全体系统用户" in value:
            return list(_ROLE_CODES.values())
        return [code for label, code in _ROLE_CODES.items() if label in value]
