"""add teams_waitlist_signups table

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-06-10

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "teams_waitlist_signups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("workspaces", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("workspace_other", sa.String(length=200), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teams_waitlist_signups"),
    )
    op.create_index(
        "ix_teams_waitlist_signups_email",
        "teams_waitlist_signups",
        ["email"],
    )
    op.create_index(
        "ix_teams_waitlist_signups_created_at",
        "teams_waitlist_signups",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_teams_waitlist_signups_created_at", table_name="teams_waitlist_signups")
    op.drop_index("ix_teams_waitlist_signups_email", table_name="teams_waitlist_signups")
    op.drop_table("teams_waitlist_signups")
