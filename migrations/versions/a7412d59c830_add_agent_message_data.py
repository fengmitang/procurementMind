"""add structured agent message data

Revision ID: a7412d59c830
Revises: ef82a4d11c73
Create Date: 2026-08-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7412d59c830"
down_revision: str | Sequence[str] | None = "ef82a4d11c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_message", sa.Column("message_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_message", "message_data")
