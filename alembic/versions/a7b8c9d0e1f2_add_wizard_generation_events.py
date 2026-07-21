"""Add wizard_generation_events table for Spike 1 funnel telemetry.

Revision ID: a7b8c9d0e1f2
Revises: f3a4b5c6d7e8
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wizard_generation_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=True),
        sa.Column("generation_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "event_metadata",
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
            name="fk_wizard_generation_events_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wizard_generation_events"),
    )
    op.create_index(
        "ix_wizard_generation_events_user_id",
        "wizard_generation_events",
        ["user_id"],
    )
    op.create_index(
        "ix_wizard_generation_events_created_at",
        "wizard_generation_events",
        ["created_at"],
    )
    op.create_index(
        "ix_wizard_generation_events_thread_id",
        "wizard_generation_events",
        ["thread_id"],
    )
    op.create_index(
        "ix_wizard_generation_events_event_phase",
        "wizard_generation_events",
        ["event_type", "phase"],
    )


def downgrade() -> None:
    op.drop_index("ix_wizard_generation_events_event_phase", table_name="wizard_generation_events")
    op.drop_index("ix_wizard_generation_events_thread_id", table_name="wizard_generation_events")
    op.drop_index("ix_wizard_generation_events_created_at", table_name="wizard_generation_events")
    op.drop_index("ix_wizard_generation_events_user_id", table_name="wizard_generation_events")
    op.drop_table("wizard_generation_events")
