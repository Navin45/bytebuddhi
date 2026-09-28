"""Lease ownership columns for multi-worker execution.

Revision ID: d4e5f6a7b8c9
Revises: b1c2d3e4f5a6, c3d4e5f6a7b8
Create Date: 2026-09-25 17:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = ("b1c2d3e4f5a6", "c3d4e5f6a7b8")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("worker_id", sa.String(length=80), nullable=True))
    op.add_column("agent_runs", sa.Column("execution_attempt", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_runs", sa.Column("lease_token", sa.String(length=36), nullable=True))
    op.add_column("agent_runs", sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_agent_runs_status_lease_expires", "agent_runs", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_status_lease_expires", table_name="agent_runs")
    op.drop_column("agent_runs", "lease_expires_at")
    op.drop_column("agent_runs", "lease_acquired_at")
    op.drop_column("agent_runs", "lease_token")
    op.drop_column("agent_runs", "execution_attempt")
    op.drop_column("agent_runs", "worker_id")
