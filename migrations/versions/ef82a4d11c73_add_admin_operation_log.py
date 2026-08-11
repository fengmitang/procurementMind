"""add admin operation log

Revision ID: ef82a4d11c73
Revises: c9a17e6d42f0
Create Date: 2026-08-11 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ef82a4d11c73"
down_revision: str | Sequence[str] | None = "c9a17e6d42f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_operation_log",
        sa.Column("operation_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("admin_employee_id", sa.BigInteger(), nullable=False),
        sa.Column("target_employee_id", sa.BigInteger(), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("action_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_employee_id"], ["employee.employee_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_employee_id"], ["employee.employee_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint("action_token", name="uq_admin_operation_log_action_token"),
    )
    op.create_index(
        "ix_admin_operation_log_admin_employee_id",
        "admin_operation_log",
        ["admin_employee_id"],
    )
    op.create_index(
        "ix_admin_operation_log_target_employee_id",
        "admin_operation_log",
        ["target_employee_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_operation_log_target_employee_id",
        table_name="admin_operation_log",
    )
    op.drop_index(
        "ix_admin_operation_log_admin_employee_id",
        table_name="admin_operation_log",
    )
    op.drop_table("admin_operation_log")
