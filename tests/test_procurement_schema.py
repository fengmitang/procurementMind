import pytest
from pydantic import ValidationError

from app.schemas.procurement import ApplicantFields


@pytest.mark.parametrize(
    "device_type",
    ("电气", "暖通", "弱电", "机房环境", "工器具", "算力服务器", "IDC网络", "其他"),
)
def test_applicant_fields_accept_supported_device_types(device_type: str) -> None:
    fields = ApplicantFields(device_profession=device_type)

    assert fields.device_profession == device_type


def test_applicant_fields_reject_unsupported_device_type() -> None:
    with pytest.raises(ValidationError):
        ApplicantFields(device_profession="服务器")
