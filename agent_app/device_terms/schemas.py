from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.procurement import DeviceType


class DeviceTermSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_name: str = Field(min_length=1, max_length=200)
    device_profession: DeviceType
    source_count: int = Field(default=1, ge=1)


class DeviceTermPayload(DeviceTermSource):
    model_config = ConfigDict(extra="forbid")

    normalized_name: str = Field(min_length=1, max_length=200)
    search_text: str = Field(min_length=1, max_length=1000)


class DeviceTermCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_name: str
    device_profession: DeviceType
    score: float | None = None
    exact: bool = False


class DeviceTermLookupStatus(StrEnum):
    EXACT = "EXACT"
    SEMANTIC = "SEMANTIC"
    NO_MATCH = "NO_MATCH"
    FALLBACK = "FALLBACK"
    CLASSIFICATION_REQUIRED = "CLASSIFICATION_REQUIRED"
    SKIPPED = "SKIPPED"


class DeviceTermLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DeviceTermLookupStatus
    query_term: str
    device_profession: DeviceType | None = None
    exact_match: bool = False
    semantic_used: bool = False
    candidates: list[DeviceTermCandidate] = Field(default_factory=list)
    top_k: int = Field(ge=1)
    embedding_latency_ms: int = Field(default=0, ge=0)
    qdrant_latency_ms: int = Field(default=0, ge=0)
    total_latency_ms: int = Field(default=0, ge=0)
    fallback_triggered: bool = False
    error_code: str | None = None
    message: str | None = None

    @property
    def selected_names(self) -> list[str]:
        return list(dict.fromkeys(item.device_name for item in self.candidates))
