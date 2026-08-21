from types import SimpleNamespace

from agent_app.api.routes.chat import _business_results
from agent_app.graph.schemas import ToolExecution


def tool_execution(
    name: str,
    data: dict | None,
    *,
    success: bool = True,
) -> ToolExecution:
    return ToolExecution(
        name=name,
        arguments={},
        success=success,
        code="OK" if success else "TOOL_FAILED",
        source="/api/v1/test",
        trace_id="trace-business-results",
        duration_ms=1,
        data=data,
    )


def result(*tools: ToolExecution, analysis=None):
    return SimpleNamespace(analysis=analysis, tool_results=list(tools))


def test_get_purchase_request_projects_public_business_result() -> None:
    raw = {
        "requirement_id": 101,
        "requirement_no": "SYNTHETIC-PR-101",
        "status": "COMPLETED",
        "current_handler": None,
        "applicant_fields": {
            "device_name": "合成测试设备",
            "brand": "SYNTHETIC-BRAND",
            "model": "SYNTHETIC-MODEL",
            "quantity": 4,
            "unit": "台",
            "application_reason": "不得公开的测试原因",
        },
        "warehouse_receipt": {
            "received_quantity": 5,
            "warehouse_location": "不得公开的测试库位",
        },
        "allowed_actions": ["INTERNAL_ACTION"],
        "review_records": [{"internal": True}],
    }

    projected = _business_results(result(tool_execution("get_purchase_request", raw)))

    assert [item.model_dump(mode="json") for item in projected] == [
        {
            "kind": "PURCHASE_REQUIREMENTS",
            "title": "采购申请",
            "items": [
                {
                    "requirement_id": 101,
                    "requirement_no": "SYNTHETIC-PR-101",
                    "status": "COMPLETED",
                    "device_name": "合成测试设备",
                    "brand": "SYNTHETIC-BRAND",
                    "model": "SYNTHETIC-MODEL",
                    "quantity": 4,
                    "unit": "台",
                    "current_handler_name": None,
                    "received_quantity": 5,
                }
            ],
            "total": 1,
        }
    ]


def test_get_purchase_request_omits_missing_optional_fields_without_invention() -> None:
    projected = _business_results(
        result(
            tool_execution(
                "get_purchase_request",
                {"requirement_id": 102, "applicant_fields": None},
            )
        )
    )

    assert projected[0].items == [{"requirement_id": 102}]


def test_failed_get_purchase_request_is_not_projected() -> None:
    projected = _business_results(
        result(
            tool_execution(
                "get_purchase_request",
                {"requirement_id": 103},
                success=False,
            )
        )
    )

    assert projected == []


def test_same_requirement_id_uses_latest_public_fields_at_first_position() -> None:
    first = {
        "requirement_id": 104,
        "requirement_no": "SYNTHETIC-PR-104",
        "status": "PURCHASING",
        "applicant_fields": {"quantity": 2, "unit": "台"},
    }
    latest = {
        "requirement_id": 104,
        "requirement_no": "SYNTHETIC-PR-104",
        "status": "WAREHOUSE_PENDING",
        "warehouse_receipt": {"received_quantity": 2},
    }

    projected = _business_results(
        result(
            tool_execution("get_purchase_request", first),
            tool_execution("get_purchase_request", latest),
        )
    )

    assert [item.items for item in projected] == [
        [
            {
                "requirement_id": 104,
                "requirement_no": "SYNTHETIC-PR-104",
                "status": "WAREHOUSE_PENDING",
                "quantity": 2,
                "unit": "台",
                "received_quantity": 2,
            }
        ]
    ]


def test_different_requirement_ids_are_not_deduplicated() -> None:
    first = {"requirement_id": 105, "status": "COMPLETED"}
    second = {"requirement_id": 106, "status": "COMPLETED"}

    projected = _business_results(
        result(
            tool_execution("get_purchase_request", first),
            tool_execution("get_purchase_request", second),
        )
    )

    assert [item.items for item in projected] == [
        [{"requirement_id": 105, "status": "COMPLETED"}],
        [{"requirement_id": 106, "status": "COMPLETED"}],
    ]


def test_requirement_no_is_identity_when_requirement_id_is_missing() -> None:
    first = {"requirement_no": "SYNTHETIC-REQ-A", "status": "PURCHASING"}
    latest = {"requirement_no": "SYNTHETIC-REQ-A", "status": "COMPLETED"}

    projected = _business_results(
        result(
            tool_execution("get_purchase_request", first),
            tool_execution("get_purchase_request", latest),
        )
    )

    assert [item.items for item in projected] == [
        [{"requirement_no": "SYNTHETIC-REQ-A", "status": "COMPLETED"}]
    ]


def test_repeated_identity_keeps_first_position_and_updates_latest_fields() -> None:
    first_a = {"requirement_id": 107, "status": "PURCHASING"}
    only_b = {"requirement_id": 108, "status": "DRAFT"}
    latest_a = {"requirement_id": 107, "status": "COMPLETED"}

    projected = _business_results(
        result(
            tool_execution("get_purchase_request", first_a),
            tool_execution("get_purchase_request", only_b),
            tool_execution("get_purchase_request", latest_a),
        )
    )

    assert [item.items for item in projected] == [
        [{"requirement_id": 107, "status": "COMPLETED"}],
        [{"requirement_id": 108, "status": "DRAFT"}],
    ]


def test_anonymous_results_are_not_mistaken_for_the_same_request() -> None:
    projected = _business_results(
        result(
            tool_execution("get_purchase_request", {"status": "DRAFT"}),
            tool_execution("get_purchase_request", {"status": "COMPLETED"}),
        )
    )

    assert [item.items for item in projected] == [
        [{"status": "DRAFT"}],
        [{"status": "COMPLETED"}],
    ]


def test_existing_search_purchase_records_projection_is_unchanged() -> None:
    search = tool_execution(
        "search_purchase_records",
        {
            "items": [
                {
                    "requirement_id": 106,
                    "requirement_no": "SYNTHETIC-PR-106",
                    "quantity": 2,
                    "internal_value": "not-public",
                }
            ],
            "total": 1,
        },
    )

    projected = _business_results(result(search))

    assert projected[0].items == [
        {
            "requirement_id": 106,
            "requirement_no": "SYNTHETIC-PR-106",
            "quantity": 2,
        }
    ]
    assert projected[0].total == 1


def test_existing_analysis_projection_remains_first() -> None:
    analysis = SimpleNamespace(
        table=SimpleNamespace(
            rows=[
                {
                    "requirement_id": 107,
                    "requirement_no": "SYNTHETIC-PR-107",
                    "status": "DRAFT",
                }
            ],
            total=1,
        )
    )
    detail = tool_execution(
        "get_purchase_request",
        {"requirement_id": 108, "status": "COMPLETED"},
    )

    projected = _business_results(result(detail, analysis=analysis))

    assert [item.items for item in projected] == [
        [
            {
                "requirement_id": 107,
                "requirement_no": "SYNTHETIC-PR-107",
                "status": "DRAFT",
            }
        ],
        [{"requirement_id": 108, "status": "COMPLETED"}],
    ]
