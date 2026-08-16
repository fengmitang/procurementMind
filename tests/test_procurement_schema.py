from typing import get_args

import pytest
from pydantic import ValidationError

from app.schemas.analytics import PurchaseQueryRequest
from app.schemas.procurement import ApplicantFields, DeviceType
from scripts.seed_demo_data import request_rows

EXPECTED_DEVICE_TYPES = (
    "10kV开关柜",
    "变压器",
    "400V配电柜",
    "UPS",
    "高压直流",
    "蓄电池",
    "监控",
    "冷水机组",
    "SHU",
    "冷却塔",
    "冷却泵",
    "机房环境",
    "水系统",
    "传输",
    "服务器",
    "运维工具",
    "列间空调",
)


def test_device_type_definition_matches_formal_catalog() -> None:
    assert get_args(DeviceType) == EXPECTED_DEVICE_TYPES


@pytest.mark.parametrize(
    "device_type",
    EXPECTED_DEVICE_TYPES,
)
def test_applicant_fields_accept_supported_device_types(device_type: str) -> None:
    fields = ApplicantFields(device_profession=device_type)

    assert fields.device_profession == device_type


@pytest.mark.parametrize("device_type", EXPECTED_DEVICE_TYPES)
def test_analytics_query_accepts_supported_device_types(device_type: str) -> None:
    query = PurchaseQueryRequest(device_professions=[device_type])

    assert query.device_professions == [device_type]


def test_applicant_fields_reject_unsupported_device_type() -> None:
    with pytest.raises(ValidationError):
        ApplicantFields(device_profession="未定义设备类型")


def test_seeded_device_professions_are_supported() -> None:
    supported = set(get_args(DeviceType))

    assert {row["device_profession"] for row in request_rows()} <= supported
