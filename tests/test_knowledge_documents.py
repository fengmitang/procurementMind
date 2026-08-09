from pathlib import Path

from agent_app.rag.documents import MarkdownKnowledgeParser

SOURCE = Path("knowledge/source")


def parse_all() -> list:
    parser = MarkdownKnowledgeParser()
    return [parser.parse(path, source_path=path.as_posix()) for path in sorted(SOURCE.glob("*.md"))]


def test_all_seven_markdown_sources_have_metadata_and_traceable_chunks() -> None:
    documents = parse_all()

    assert len(documents) == 7
    assert len({document.document.document_id for document in documents}) == 7
    assert all(document.document.content_hash for document in documents)
    assert all(document.document.version == "1.0" for document in documents)
    assert all(document.document.status == "ACTIVE" for document in documents)
    assert all(document.parents for document in documents)
    assert all(document.children for document in documents)
    assert all(
        child.payload.source_start_line <= child.payload.source_end_line
        for document in documents
        for child in document.children
    )


def test_faq_question_and_answer_remain_one_complete_child() -> None:
    path = SOURCE / "07-数据中心设备采购常见问题手册.md"
    document = MarkdownKnowledgeParser(child_max_chars=100).parse(path)
    target = next(parent for parent in document.parents if "草稿没有填完整" in parent.record.title)

    assert target.record.chunk_type == "faq"
    assert len(target.children) == 1
    assert "草稿允许暂时保存" in target.children[0].payload.content


def test_field_requirements_are_not_fragmented_by_soft_length_limit() -> None:
    path = SOURCE / "03-采购申请及各环节字段填写规范（试行）.md"
    document = MarkdownKnowledgeParser(child_max_chars=100).parse(path)
    target = next(parent for parent in document.parents if parent.record.title == "第三条 设备专业")

    assert target.record.chunk_type == "field"
    assert len(target.children) == 1
    assert "填写要求" in target.children[0].payload.content
    assert "是否必填" in target.children[0].payload.content


def test_embedding_text_contains_title_path_topic_and_body() -> None:
    document = parse_all()[0]
    child = document.children[0]

    assert f"文档标题：{document.document.title}" in child.embedding_text
    assert "章节路径：" in child.embedding_text
    assert f"主题：{child.payload.topic}" in child.embedding_text
    assert f"正文：{child.payload.content}" in child.embedding_text


def test_stable_ids_survive_content_change_but_hashes_change(tmp_path: Path) -> None:
    original_path = SOURCE / "01-数据中心设备采购业务管理与流程指引（试行）.md"
    original = MarkdownKnowledgeParser().parse(original_path, source_path="knowledge/source/01.md")
    changed_path = tmp_path / original_path.name
    changed_path.write_text(
        original_path.read_text(encoding="utf-8").replace(
            "统一系统内采购业务流转方式",
            "统一系统内采购业务流转方式并补充追溯要求",
        ),
        encoding="utf-8",
    )
    changed = MarkdownKnowledgeParser().parse(changed_path, source_path="knowledge/source/01.md")

    assert changed.document.document_id == original.document.document_id
    assert changed.document.content_hash != original.document.content_hash
    assert [parent.record.parent_id for parent in changed.parents] == [
        parent.record.parent_id for parent in original.parents
    ]
    assert [child.payload.child_id for child in changed.children] == [
        child.payload.child_id for child in original.children
    ]


def test_index_and_revision_sections_are_not_answer_evidence() -> None:
    for document in parse_all():
        titles = {parent.record.title for parent in document.parents}
        assert "关键词索引" not in titles
        assert "版本修订记录" not in titles
