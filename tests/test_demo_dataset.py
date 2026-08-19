from collections import Counter

from app.schemas.procurement import DEVICE_PROFESSIONS
from scripts.seed_demo_dataset import (
    PROFESSION_COUNTS,
    STATUS_COUNTS,
    build_dataset,
    role_and_building_rows,
)

ROLE_IDS = {
    "APPLICANT": 1,
    "BUILDING_MANAGER": 2,
    "PURCHASER": 3,
    "WAREHOUSE_MANAGER": 4,
    "ADMIN": 5,
}
BUILDING_IDS = list(range(1, 10))


def dataset():
    return build_dataset(BUILDING_IDS, ROLE_IDS)


def test_demo_dataset_has_exact_status_and_profession_distribution():
    requests = dataset()["requests"]

    assert Counter(row["status"] for row in requests) == STATUS_COUNTS
    assert Counter(row["device_profession"] for row in requests) == PROFESSION_COUNTS
    assert set(PROFESSION_COUNTS) == set(DEVICE_PROFESSIONS)
    assert all(isinstance(row["quantity"], int) and row["quantity"] > 0 for row in requests)


def test_demo_dataset_workflow_relations_are_consistent():
    data = dataset()
    executions = {row["request_id"] for row in data["executions"]}
    receipts = {row["request_id"] for row in data["receipts"]}
    reviews = {row["request_id"]: row for row in data["reviews"]}

    for request in data["requests"]:
        request_id = request["request_id"]
        if request["status"] == "COMPLETED":
            assert request_id in executions and request_id in receipts
        if request["status"] == "PENDING_WAREHOUSE":
            assert request_id in executions and request_id not in receipts
        if request["status"] == "DRAFT":
            assert request_id not in executions and request_id not in reviews
        if request["status"] == "REJECTED":
            assert reviews[request_id]["review_result"] == "REJECTED"


def test_demo_operation_timeline_is_monotonic_and_uses_known_actions():
    allowed = {
        "CREATE_DRAFT",
        "SUBMIT_REVIEW",
        "REJECT",
        "SUBMIT_PURCHASER",
        "START_PURCHASE",
        "SUBMIT_WAREHOUSE",
        "COMPLETE",
    }
    logs_by_request = {}
    for row in dataset()["logs"]:
        logs_by_request.setdefault(row["request_id"], []).append(row)

    for logs in logs_by_request.values():
        assert [row["operated_at"] for row in logs] == sorted(row["operated_at"] for row in logs)
        assert {row["action_type"] for row in logs} <= allowed


def test_demo_has_multi_role_users_and_scoped_building_managers():
    roles, buildings = role_and_building_rows(ROLE_IDS, BUILDING_IDS)
    role_counts = Counter(row["employee_id"] for row in roles)
    building_counts = Counter(row["employee_id"] for row in buildings)

    assert sum(count > 1 for count in role_counts.values()) >= 3
    assert building_counts[8_100_002] == 2
    assert building_counts[8_100_011] == 3


def test_demo_server_history_supports_time_sensitive_recommendation():
    data = dataset()
    requests = {row["request_id"]: row for row in data["requests"]}
    history = [
        (requests[row["request_id"]], row)
        for row in data["executions"]
        if requests[row["request_id"]]["device_profession"] == "服务器"
    ]
    all_rank = Counter((request["brand"], request["model"]) for request, _ in history)
    recent_rank = Counter(
        (request["brand"], request["model"])
        for request, execution in history
        if execution["purchased_at"].date().isoformat() >= "2026-06-20"
    )

    assert all_rank.most_common(1)[0][0][0] == "浪潮"
    assert recent_rank.most_common(1)[0][0][0] == "华为"
