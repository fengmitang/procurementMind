from __future__ import annotations

import re
import unicodedata

from agent_app.domain.device_catalog import get_device_catalog
from app.schemas.procurement import DeviceType

_MAX_DESCRIPTION_CHARS = 180
_MAX_TYPICAL_TERMS = 6


def normalize_device_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", "", normalized)


def build_device_term_search_text(device_name: str, device_profession: DeviceType) -> str:
    terms = get_device_catalog().professions[device_profession]
    description = terms.description[:_MAX_DESCRIPTION_CHARS].rstrip()
    return (
        f"设备名称：{device_name.strip()}；设备类型：{device_profession}；"
        f"类别说明：{description}"
    )


def build_device_term_query(query_term: str, device_profession: DeviceType) -> str:
    terms = get_device_catalog().professions[device_profession]
    description = terms.description[:_MAX_DESCRIPTION_CHARS].rstrip()
    typical = "、".join(terms.typical_terms[:_MAX_TYPICAL_TERMS])
    parts = [
        f"查询设备：{query_term.strip()}",
        f"设备类型：{device_profession}",
        f"类别说明：{description}",
    ]
    if typical:
        parts.append(f"相关典型术语：{typical}")
    return "；".join(parts)
