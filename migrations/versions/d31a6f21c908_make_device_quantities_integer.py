"""make device quantities integer

Revision ID: d31a6f21c908
Revises: a7412d59c830
Create Date: 2026-08-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "d31a6f21c908"
down_revision: str | Sequence[str] | None = "a7412d59c830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reject_fractional_values(table: str, column: str) -> None:
    count = op.get_bind().execute(
        sa.text(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {column} IS NOT NULL AND {column} <> FLOOR({column})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot migrate {table}.{column}: found {count} fractional value(s)"
        )


def upgrade() -> None:
    _reject_fractional_values("purchase_request", "quantity")
    _reject_fractional_values("warehouse_receipt", "received_quantity")
    op.alter_column(
        "purchase_request",
        "quantity",
        existing_type=mysql.DECIMAL(precision=18, scale=3),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "warehouse_receipt",
        "received_quantity",
        existing_type=mysql.DECIMAL(precision=18, scale=3),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "warehouse_receipt",
        "received_quantity",
        existing_type=sa.BigInteger(),
        type_=mysql.DECIMAL(precision=18, scale=3),
        existing_nullable=False,
    )
    op.alter_column(
        "purchase_request",
        "quantity",
        existing_type=sa.BigInteger(),
        type_=mysql.DECIMAL(precision=18, scale=3),
        existing_nullable=True,
    )
