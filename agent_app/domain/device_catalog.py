from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.procurement import DEVICE_PROFESSIONS, DeviceType

CATALOG_PATH = Path(__file__).with_name("device_catalog.yaml")


class DeviceCatalogError(ValueError):
    """Raised when the device terminology catalog violates its contract."""


class DeviceProfessionTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=1)
    typical_terms: list[str]
    ambiguous_terms: list[str]
    notes: str = Field(min_length=1)

    @field_validator("description", "notes")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("目录说明不能为空")
        return normalized

    @field_validator("typical_terms", "ambiguous_terms")
    @classmethod
    def validate_terms(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("术语列表不能包含空字符串")
        if len(set(normalized)) != len(normalized):
            raise ValueError("同一术语列表不能包含重复值")
        return normalized


class DeviceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=1)
    professions: dict[str, DeviceProfessionTerms]

    @model_validator(mode="after")
    def professions_must_match_canonical_values(self) -> DeviceCatalog:
        actual = set(self.professions)
        expected = set(DEVICE_PROFESSIONS)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(f"设备类型目录与正式定义不一致：missing={missing}, extra={extra}")
        return self

    def typical_matches(self, text: str) -> dict[DeviceType, tuple[str, ...]]:
        return self._matches(text, "typical_terms")

    def ambiguous_matches(self, text: str) -> dict[DeviceType, tuple[str, ...]]:
        return self._matches(text, "ambiguous_terms")

    def _matches(
        self,
        text: str,
        field_name: str,
    ) -> dict[DeviceType, tuple[str, ...]]:
        normalized = text.casefold()
        matches: dict[DeviceType, tuple[str, ...]] = {}
        for profession in DEVICE_PROFESSIONS:
            terms = getattr(self.professions[profession], field_name)
            found = tuple(term for term in terms if term.casefold() in normalized)
            if found:
                matches[profession] = found
        return matches


def load_device_catalog(path: Path = CATALOG_PATH) -> DeviceCatalog:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DeviceCatalogError(f"无法加载设备术语目录 {path}: {exc}") from exc
    try:
        return DeviceCatalog.model_validate(raw)
    except ValueError as exc:
        raise DeviceCatalogError(f"设备术语目录校验失败 {path}: {exc}") from exc


@lru_cache(maxsize=1)
def get_device_catalog() -> DeviceCatalog:
    return load_device_catalog()


@lru_cache(maxsize=1)
def build_device_classification_context() -> str:
    catalog = get_device_catalog()
    sections = []
    for profession in DEVICE_PROFESSIONS:
        terms = catalog.professions[profession]
        sections.append(
            "\n".join(
                (
                    f"类别：{profession}",
                    f"说明：{terms.description}",
                    f"典型术语：{'、'.join(terms.typical_terms) or '无'}",
                    f"歧义术语：{'、'.join(terms.ambiguous_terms) or '无'}",
                    f"备注：{terms.notes}",
                )
            )
        )
    return "\n\n".join(sections)
