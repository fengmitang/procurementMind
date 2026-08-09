"""add knowledge document and parent

Revision ID: b4f3a8c29d11
Revises: 816575c8be0c
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b4f3a8c29d11"
down_revision: str | Sequence[str] | None = "816575c8be0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("allowed_roles", mysql.JSON(), nullable=True),
        sa.Column("device_scopes", mysql.JSON(), nullable=True),
        sa.Column("metadata", mysql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_knowledge_document")),
        sa.UniqueConstraint("source_path", name="uq_knowledge_document_source_path"),
    )
    op.create_index(
        "ix_knowledge_document_status_effective",
        "knowledge_document",
        ["status", "effective_at"],
    )
    op.create_index(
        "ix_knowledge_document_type_version",
        "knowledge_document",
        ["document_type", "version"],
    )

    op.create_table(
        "knowledge_parent",
        sa.Column("parent_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("section_path", mysql.JSON(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("chunk_type", sa.String(length=30), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content", mysql.LONGTEXT(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_start_line", sa.BigInteger(), nullable=False),
        sa.Column("source_end_line", sa.BigInteger(), nullable=False),
        sa.Column("metadata", mysql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_document.document_id"],
            name=op.f("fk_knowledge_parent_document_id_knowledge_document"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("parent_id", name=op.f("pk_knowledge_parent")),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_knowledge_parent_document_ordinal",
        ),
    )
    op.create_index(
        "ix_knowledge_parent_document_status",
        "knowledge_parent",
        ["document_id", "status"],
    )
    op.create_index("ix_knowledge_parent_topic", "knowledge_parent", ["topic"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_parent_topic", table_name="knowledge_parent")
    op.drop_index("ix_knowledge_parent_document_status", table_name="knowledge_parent")
    op.drop_table("knowledge_parent")
    op.drop_index("ix_knowledge_document_type_version", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_status_effective", table_name="knowledge_document")
    op.drop_table("knowledge_document")
