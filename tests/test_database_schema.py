from collections.abc import Iterable

import pytest
from sqlalchemy import inspect, text

from app.db.session import engine

BUSINESS_TABLES = {
    "agent_conversation",
    "agent_message",
    "agent_session_state",
    "building",
    "employee",
    "employee_building",
    "employee_external_identity",
    "employee_role",
    "notification_outbox",
    "purchase_execution",
    "purchase_operation_log",
    "purchase_request",
    "purchase_review",
    "role",
    "supplier",
    "supplier_blacklist",
    "warehouse_receipt",
}

EXPECTED_ROLES = [
    (1, "APPLICANT", "需求人"),
    (2, "BUILDING_MANAGER", "楼长"),
    (3, "PURCHASER", "采购员"),
    (4, "WAREHOUSE_MANAGER", "仓库管理员"),
    (5, "ADMIN", "系统管理员"),
]

EXPECTED_BUILDINGS = [
    (1, "一号楼"),
    (2, "二号楼"),
    (3, "三号楼"),
    (4, "四号楼"),
    (5, "五号楼"),
    (6, "六号楼"),
]


def _table_names(sync_connection) -> Iterable[str]:
    return inspect(sync_connection).get_table_names()


@pytest.mark.asyncio
async def test_initial_database_schema_and_seed_data() -> None:
    async with engine.connect() as connection:
        table_names = set(await connection.run_sync(_table_names))
        current_user = await connection.scalar(text("SELECT CURRENT_USER()"))
        roles = (
            (
                await connection.execute(
                    text("SELECT role_id, role_code, role_name FROM role ORDER BY role_id")
                )
            )
            .tuples()
            .all()
        )
        buildings = (
            (
                await connection.execute(
                    text("SELECT building_id, building_name FROM building ORDER BY building_id")
                )
            )
            .tuples()
            .all()
        )

    assert table_names == BUSINESS_TABLES | {"alembic_version"}
    assert current_user is not None
    assert current_user.startswith("procurement_agent_app@")
    assert roles == EXPECTED_ROLES
    assert buildings == EXPECTED_BUILDINGS
