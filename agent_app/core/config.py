from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.docker", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    agent_app_name: str = "Procurement Mind Agent"
    agent_app_env: str = "development"
    agent_debug: bool = False
    agent_log_level: str = "INFO"
    agent_host: str = "127.0.0.1"
    agent_port: int = Field(default=8100, ge=1, le=65535)
    agent_api_v1_prefix: str = "/api/v1"

    procurement_backend_url: str = "http://127.0.0.1:8000"
    procurement_backend_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    procurement_backend_max_retries: int = Field(default=1, ge=0, le=3)
    procurement_backend_retry_delay_seconds: float = Field(default=0.1, ge=0, le=5)
    identity_gateway_secret: str = Field(repr=False, min_length=16)
    mcp_startup_timeout_seconds: float = Field(default=60.0, gt=0, le=180)
    mcp_tool_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    mcp_server_module: str = "agent_app.mcp.server"
    mcp_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    mcp_circuit_recovery_timeout_seconds: float = Field(default=30.0, gt=0, le=600)

    model_provider: str | None = None
    model_api_key: SecretStr | None = Field(default=None, repr=False)
    model_base_url: str | None = None
    primary_model: str | None = None
    fallback_model: str | None = None
    embedding_model_path: Path | None = None
    reranker_model_path: Path | None = None
    rag_model_device: Literal["auto", "cpu", "cuda"] = "auto"
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "procurement_knowledge_child"
    qdrant_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    rag_dense_vector_size: int = Field(default=1024, gt=0, le=65536)
    rag_dense_vector_name: str = "dense"
    rag_sparse_vector_name: str = "bm25"
    knowledge_source_directory: Path = Path("knowledge/source")
    rag_child_max_chars: int = Field(default=800, ge=100, le=10000)
    rag_child_hard_max_chars: int = Field(default=2000, ge=100, le=20000)
    rag_embedding_batch_size: int = Field(default=4, ge=1, le=128)
    rag_embedding_max_length: int = Field(default=512, ge=64, le=8192)
    qdrant_upsert_batch_size: int = Field(default=32, ge=1, le=256)
    rag_dense_top_k: int = Field(default=15, ge=1, le=100)
    rag_sparse_top_k: int = Field(default=15, ge=1, le=100)
    rag_fusion_top_k: int = Field(default=12, ge=1, le=100)
    rag_rerank_top_k: int = Field(default=5, ge=1, le=50)
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_reranker_batch_size: int = Field(default=4, ge=1, le=128)
    rag_rerank_min_score: float = Field(default=0.2, ge=0, le=1)
    rag_context_max_chars: int = Field(default=6000, ge=500, le=50000)
    rag_parent_max_chars: int = Field(default=2400, ge=200, le=20000)
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    model_structured_output_retries: int = Field(default=1, ge=0, le=3)
    model_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    model_circuit_recovery_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    chroma_persist_directory: Path = Path(".data/chroma")
    max_tool_calls: int = Field(default=8, ge=1, le=50)
    max_execution_steps: int = Field(default=12, ge=1, le=100)
    task_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    rag_top_k: int = Field(default=5, ge=1, le=50)
    review_enabled: bool = True
    trace_enabled: bool = True

    @field_validator("procurement_backend_url")
    @classmethod
    def normalize_backend_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("procurement_backend_url 必须使用 http 或 https")
        return normalized

    @field_validator(
        "model_provider",
        "model_base_url",
        "primary_model",
        "fallback_model",
        "qdrant_url",
        "qdrant_collection",
        "rag_dense_vector_name",
        "rag_sparse_vector_name",
        mode="before",
    )
    @classmethod
    def blank_optional_text_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("model_api_key", mode="before")
    @classmethod
    def blank_model_key_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def model_configured(self) -> bool:
        return bool(self.model_provider and self.primary_model and self.model_api_key)

    @property
    def rag_models_configured(self) -> bool:
        return bool(self.embedding_model_path and self.reranker_model_path)

    @model_validator(mode="after")
    def validate_rag_chunk_limits(self) -> "AgentSettings":
        if self.rag_child_hard_max_chars < self.rag_child_max_chars:
            raise ValueError("RAG_CHILD_HARD_MAX_CHARS 不能小于 RAG_CHILD_MAX_CHARS")
        if self.rag_fusion_top_k > self.rag_dense_top_k + self.rag_sparse_top_k:
            raise ValueError("RAG_FUSION_TOP_K 不能大于 Dense 与 Sparse 候选总数")
        if self.rag_rerank_top_k > self.rag_fusion_top_k:
            raise ValueError("RAG_RERANK_TOP_K 不能大于 RAG_FUSION_TOP_K")
        if self.rag_parent_max_chars > self.rag_context_max_chars:
            raise ValueError("RAG_PARENT_MAX_CHARS 不能大于 RAG_CONTEXT_MAX_CHARS")
        return self


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
