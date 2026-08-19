from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

QUANTITY_UNITS = ("台", "套", "个", "批", "件")


class QuantityParseStatus(StrEnum):
    ABSENT = "ABSENT"
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class QuantityParseResult:
    status: QuantityParseStatus
    quantity: int | None = None
    unit: str | None = None


_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_UNIT_PATTERN = "|".join(QUANTITY_UNITS)
_ARABIC_PATTERN = re.compile(rf"(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})")
_CHINESE_PATTERN = re.compile(rf"([零〇一二两三四五六七八九十百千万]+)\s*({_UNIT_PATTERN})")
_FUZZY_PATTERN = re.compile(
    rf"(?:大约|约|差不多)\s*[零〇一二两三四五六七八九十百千万\d]*\s*(?:{_UNIT_PATTERN})"
    rf"|[零〇一二两三四五六七八九十百千万\d]+\s*(?:{_UNIT_PATTERN})\s*左右"
    rf"|(?:若干|几|十几|几十|两三|三四)\s*(?:{_UNIT_PATTERN})"
)


def parse_chinese_integer(value: str) -> int | None:
    """Parse an unambiguous Chinese positive integer up to 99999."""
    allowed = set(_DIGITS) | set(_SMALL_UNITS) | {"万"}
    if not value or any(char not in allowed for char in value):
        return None
    if not any(char in _SMALL_UNITS or char == "万" for char in value):
        if len(value) != 1:
            return None
        result = _DIGITS[value]
        return result if result > 0 else None

    total = 0
    section = 0
    number = 0
    previous_small_unit = 10000
    for char in value:
        if char in _DIGITS:
            number = _DIGITS[char]
        elif char in _SMALL_UNITS:
            unit = _SMALL_UNITS[char]
            if unit >= previous_small_unit:
                return None
            section += (number or 1) * unit
            number = 0
            previous_small_unit = unit
        else:
            section += number
            if total or section <= 0:
                return None
            total = section * 10000
            section = 0
            number = 0
            previous_small_unit = 10000
    result = total + section + number
    return result if 0 < result <= 99999 else None


def parse_quantity_with_unit(message: str) -> QuantityParseResult:
    """Extract an exact positive integer device quantity without guessing fuzzy values."""
    if _FUZZY_PATTERN.search(message):
        return QuantityParseResult(QuantityParseStatus.INVALID)

    arabic = _ARABIC_PATTERN.search(message)
    if arabic:
        raw, unit = arabic.groups()
        if "." in raw:
            return QuantityParseResult(QuantityParseStatus.INVALID, unit=unit)
        quantity = int(raw)
        if quantity <= 0:
            return QuantityParseResult(QuantityParseStatus.INVALID, unit=unit)
        return QuantityParseResult(QuantityParseStatus.VALID, quantity, unit)

    chinese = _CHINESE_PATTERN.search(message)
    if chinese:
        raw, unit = chinese.groups()
        quantity = parse_chinese_integer(raw)
        if quantity is None:
            return QuantityParseResult(QuantityParseStatus.INVALID, unit=unit)
        return QuantityParseResult(QuantityParseStatus.VALID, quantity, unit)

    return QuantityParseResult(QuantityParseStatus.ABSENT)
