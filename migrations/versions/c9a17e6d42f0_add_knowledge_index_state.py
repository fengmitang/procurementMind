"""add knowledge index state

Revision ID: c9a17e6d42f0
Revises: b4f3a8c29d11
Create Date: 2026-08-07 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a17e6d42f0"
down_revision: str | Sequence[str] | None = "b4f3a8c29d11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_document",
        sa.Column(
            "index_status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "knowledge_document",
        sa.Column("index_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_document", "index_error")
    op.drop_column("knowledge_document", "indexed_at")
    op.drop_column("knowledge_document", "index_status")
