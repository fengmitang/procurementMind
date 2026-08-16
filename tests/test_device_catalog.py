from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from agent_app.domain.device_catalog import (
    CATALOG_PATH,
    DeviceCatalogError,
    build_device_classification_context,
    get_device_catalog,
    load_device_catalog,
)
from app.schemas.procurement import DEVICE_PROFESSIONS


def catalog_payload() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def write_catalog(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_catalog_has_exactly_the_canonical_17_professions() -> None:
    catalog = get_device_catalog()

    assert len(catalog.professions) == 17
    assert set(catalog.professions) == set(DEVICE_PROFESSIONS)
    assert get_device_catalog() is catalog
    context = build_device_classification_context()
    assert all(f"类别：{profession}" in context for profession in DEVICE_PROFESSIONS)


def test_catalog_missing_profession_fails_fast(tmp_path: Path) -> None:
    payload = catalog_payload()
    payload["professions"].pop("UPS")

    with pytest.raises(DeviceCatalogError, match="missing"):
        load_device_catalog(write_catalog(tmp_path / "missing.yaml", payload))


def test_catalog_extra_profession_fails_fast(tmp_path: Path) -> None:
    payload = catalog_payload()
    payload["professions"]["额外类别"] = deepcopy(payload["professions"]["UPS"])

    with pytest.raises(DeviceCatalogError, match="extra"):
        load_device_catalog(write_catalog(tmp_path / "extra.yaml", payload))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["professions"]["UPS"].update(description="   "),
        lambda payload: payload["professions"]["UPS"].update(typical_terms="UPS"),
        lambda payload: payload["professions"]["UPS"].update(ambiguous_terms={"UPS": True}),
    ],
)
def test_catalog_invalid_format_fails_fast(tmp_path: Path, mutate) -> None:
    payload = catalog_payload()
    mutate(payload)

    with pytest.raises(DeviceCatalogError):
        load_device_catalog(write_catalog(tmp_path / "invalid.yaml", payload))
