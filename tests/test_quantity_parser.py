from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_app.domain.quantity_parser import (
    QuantityParseStatus,
    parse_chinese_integer,
    parse_quantity_with_unit,
)
from agent_app.models.role_schemas import DeviceClassificationStatus, FormExtractOutput
from app.schemas.procurement import ApplicantFields, PurchaseFieldsValidation, WarehouseFields


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一", 1),
        ("两", 2),
        ("十", 10),
        ("十二", 12),
        ("二十", 20),
        ("二十一", 21),
        ("三十五", 35),
        ("一百", 100),
        ("一百零二", 102),
        ("两百", 200),
        ("两百五十", 250),
        ("一千", 1000),
        ("一千零二", 1002),
        ("两千三百", 2300),
        ("一万零二", 10002),
    ],
)
def test_parse_chinese_integer(text: str, expected: int) -> None:
    assert parse_chinese_integer(text) == expected


@pytest.mark.parametrize(
    ("message", "quantity", "unit"),
    [
        ("两台服务器", 2, "台"),
        ("采购三个UPS模块", 3, "个"),
        ("买十二个功率模块", 12, "个"),
        ("采购二十套设备", 20, "套"),
        ("采购二十五件工具", 25, "件"),
        ("采购一百台服务器", 100, "台"),
        ("采购一百零二个模块", 102, "个"),
        ("采购两百套设备", 200, "套"),
        ("采购2台服务器", 2, "台"),
        ("采购12个模块", 12, "个"),
    ],
)
def test_parse_exact_quantity_with_unit(message: str, quantity: int, unit: str) -> None:
    result = parse_quantity_with_unit(message)

    assert result.status is QuantityParseStatus.VALID
    assert result.quantity == quantity
    assert result.unit == unit
    assert isinstance(result.quantity, int)


@pytest.mark.parametrize(
    "message",
    [
        "采购2.5台服务器",
        "采购1.2个模块",
        "采购0台服务器",
        "采购-1台服务器",
        "买几台服务器",
        "买十几台服务器",
        "买几十台服务器",
        "买两三台服务器",
        "买一批左右服务器",
        "大约五台服务器",
        "采购若干台服务器",
    ],
)
def test_reject_invalid_or_fuzzy_quantity(message: str) -> None:
    result = parse_quantity_with_unit(message)

    assert result.status is QuantityParseStatus.INVALID
    assert result.quantity is None


@pytest.mark.parametrize("value", [0, -1, 2.5, Decimal("1.5")])
def test_device_quantity_schemas_reject_non_positive_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        ApplicantFields(quantity=value)
    with pytest.raises(ValidationError):
        WarehouseFields(warehouse_location="A-01", received_quantity=value)


def test_form_extract_output_uses_integer_quantity() -> None:
    output = FormExtractOutput(
        classification_status=DeviceClassificationStatus.CONFIDENT,
        device_profession="服务器",
        device_name="服务器",
        quantity=2,
        unit="台",
    )
    assert output.quantity == 2
    assert isinstance(output.quantity, int)
    with pytest.raises(ValidationError):
        FormExtractOutput(
            classification_status=DeviceClassificationStatus.CONFIDENT,
            device_profession="服务器",
            quantity=2.5,
        )


def test_integer_quantity_keeps_decimal_amount_precision() -> None:
    validation = PurchaseFieldsValidation(
        quantity=3,
        unit_price=Decimal("9999.99"),
        supplied_total=Decimal("29999.97"),
    )

    assert validation.quantity == 3
