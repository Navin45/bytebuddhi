"""add_memory_items_table

Revision ID: 7a8e102b345c
Revises: 36144d2c114a
Create Date: 2026-09-10 14:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a8e102b345c"
down_revision: str | Sequence[str] | None = "36144d2c114a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("scope_id", sa.String(length=100), nullable=False),
        sa.Column("memory_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_memory_items_scope_scope_id", "memory_items", ["scope", "scope_id"], unique=False)
    op.create_index("ix_memory_items_type", "memory_items", ["memory_type"], unique=False)
    op.create_index("ix_memory_items_importance", "memory_items", ["importance"], unique=False)
    op.create_index("ix_memory_items_expires_at", "memory_items", ["expires_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_memory_items_expires_at", table_name="memory_items")
    op.drop_index("ix_memory_items_importance", table_name="memory_items")
    op.drop_index("ix_memory_items_type", table_name="memory_items")
    op.drop_index("ix_memory_items_scope_scope_id", table_name="memory_items")
    op.drop_table("memory_items")
