"""Add mcp_tool_invocations for MCP metering and cost telemetry.

Revision ID: c4d5e6f7a8b9
Revises: b9c0d1e2f3a4, a1b2c3d4e5f6
Create Date: 2026-06-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = ("b9c0d1e2f3a4", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=True),
        sa.Column("oauth_client_id", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("reasoning_ms", sa.Integer(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=True),
        sa.Column("edge_count", sa.Integer(), nullable=True),
        sa.Column("answered_count", sa.Integer(), nullable=True),
        sa.Column("sat_calls", sa.Integer(), nullable=True),
        sa.Column("quota_weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("estimated_cost_usd_micros", sa.Integer(), nullable=True),
        sa.Column(
            "cost_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_mcp_tool_invocations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_tool_invocations"),
    )
    op.create_index(
        "ix_mcp_tool_invocations_user_id",
        "mcp_tool_invocations",
        ["user_id"],
    )
    op.create_index(
        "ix_mcp_tool_invocations_created_at",
        "mcp_tool_invocations",
        ["created_at"],
    )
    op.create_index(
        "ix_mcp_tool_invocations_tool_outcome",
        "mcp_tool_invocations",
        ["tool_name", "outcome"],
    )
    op.create_index(
        "ix_mcp_tool_invocations_user_created",
        "mcp_tool_invocations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_tool_invocations_user_created", table_name="mcp_tool_invocations")
    op.drop_index("ix_mcp_tool_invocations_tool_outcome", table_name="mcp_tool_invocations")
    op.drop_index("ix_mcp_tool_invocations_created_at", table_name="mcp_tool_invocations")
    op.drop_index("ix_mcp_tool_invocations_user_id", table_name="mcp_tool_invocations")
    op.drop_table("mcp_tool_invocations")
