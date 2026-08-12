from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KnowledgeStatus = Literal["DRAFT", "ACTIVE", "RETIRED"]
ChunkType = Literal["rule", "field", "step", "faq", "risk", "section"]


class KnowledgeDocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=50)
    version: str = Field(min_length=1, max_length=50)
    status: KnowledgeStatus
    source_path: str = Field(min_length=1, max_length=500)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_at: datetime | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    device_scopes: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class KnowledgeParentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    ordinal: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=255)
    section_path: list[str] = Field(min_length=1)
    topic: str = Field(min_length=1, max_length=255)
    chunk_type: ChunkType
    version: str = Field(min_length=1, max_length=50)
    status: KnowledgeStatus
    content: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    metadata: dict = Field(default_factory=dict)

    @field_validator("source_end_line")
    @classmethod
    def end_line_must_follow_start(cls, value: int, info) -> int:
        start = info.data.get("source_start_line")
        if start is not None and value < start:
            raise ValueError("source_end_line 不能小于 source_start_line")
        return value


class ChildChunkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str = Field(min_length=1, max_length=64)
    parent_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    section_path: list[str] = Field(min_length=1)
    topic: str = Field(min_length=1, max_length=255)
    chunk_type: ChunkType
    version: str = Field(min_length=1, max_length=50)
    status: KnowledgeStatus
    content: str = Field(min_length=1)
    source_path: str = Field(min_length=1, max_length=500)
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)
    allowed_roles: list[str] = Field(default_factory=list)
    device_scopes: list[str] = Field(default_factory=list)

    @field_validator("source_end_line")
    @classmethod
    def end_line_must_follow_start(cls, value: int, info) -> int:
        start = info.data.get("source_start_line")
        if start is not None and value < start:
            raise ValueError("source_end_line 不能小于 source_start_line")
        return value


class RetrievalFilters(BaseModel):
    """Caller-controlled retrieval scope; business facts never belong here."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(default_factory=list, max_length=50)
    versions: list[str] = Field(default_factory=list, max_length=20)
    chunk_types: list[ChunkType] = Field(default_factory=list, max_length=20)
    allowed_roles: list[str] = Field(min_length=1, max_length=20)
    device_scopes: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["ACTIVE"] = "ACTIVE"


class RetrievalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: ChildChunkPayload
    score: float


class KnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^K[1-9][0-9]*$")
    child_id: str
    parent_id: str
    document_id: str
    document_title: str
    version: str
    section_path: list[str] = Field(min_length=1)
    source_path: str
    source_start_line: int = Field(ge=1)
    source_end_line: int = Field(ge=1)


class RetrievedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: ChildChunkPayload
    fusion_score: float
    rerank_score: float
    context_content: str
    citation: KnowledgeCitation
    parent_expanded: bool = False
    context_truncated: bool = False


class RerankTraceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str
    fusion_score: float
    rerank_score: float


class ParentLookupTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: str
    child_id: str
    found_ready: bool
    expanded: bool


class RetrievalTimings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_version_ms: int = Field(default=0, ge=0)
    rewrite_ms: int = Field(default=0, ge=0)
    embedding_ms: int = Field(default=0, ge=0)
    filter_build_ms: int = Field(default=0, ge=0)
    dense_query_ms: int = Field(default=0, ge=0)
    sparse_query_ms: int = Field(default=0, ge=0)
    hybrid_query_ms: int = Field(default=0, ge=0)
    retrieval_wall_ms: int = Field(default=0, ge=0)
    candidate_conversion_ms: int = Field(default=0, ge=0)
    rerank_ms: int = Field(default=0, ge=0)
    parent_db_ms: int = Field(default=0, ge=0)
    context_build_ms: int = Field(default=0, ge=0)
    total_ms: int = Field(default=0, ge=0)


class RetrievalTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=128)
    original_query: str
    rewritten_query: str
    rewrite_applied: bool
    rewrite_error: str | None = None
    filters: RetrievalFilters
    dense_candidates: list[RetrievalCandidate]
    sparse_candidates: list[RetrievalCandidate]
    rrf_candidates: list[RetrievalCandidate]
    rerank_candidates: list[RerankTraceItem]
    final_evidence_ids: list[str]
    parent_lookups: list[ParentLookupTrace]
    citations: list[KnowledgeCitation]
    duration_ms: int = Field(ge=0)
    timings: RetrievalTimings = Field(default_factory=RetrievalTimings)
    rewrite_skipped: bool = False
    rewrite_cache_hit: bool = False
    embedding_cache_hit: bool = False
    retrieval_cache_hit: bool = False
    knowledge_version: str | None = None


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_query: str = Field(min_length=1)
    rewritten_query: str = Field(min_length=1)
    rewrite_applied: bool = False
    rewrite_error: str | None = None
    dense_candidates: list[RetrievalCandidate]
    sparse_candidates: list[RetrievalCandidate]
    fusion_candidates: list[RetrievalCandidate]
    evidences: list[RetrievedEvidence]
    citations: list[KnowledgeCitation]
    context: str
    answerable: bool
    abstention_reason: str | None = None
    trace: RetrievalTrace
