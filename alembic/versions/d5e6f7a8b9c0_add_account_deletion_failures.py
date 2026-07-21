"""Add account_deletion_failures dead-letter table.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("clerk_user_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_deletion_failures"),
    )
    op.create_index(
        "ix_account_deletion_failures_user_id",
        "account_deletion_failures",
        ["user_id"],
    )
    op.create_index(
        "ix_account_deletion_failures_clerk_user_id",
        "account_deletion_failures",
        ["clerk_user_id"],
    )
    op.create_index(
        "ix_account_deletion_failures_unresolved_clerk",
        "account_deletion_failures",
        ["clerk_user_id"],
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_deletion_failures_unresolved_clerk",
        table_name="account_deletion_failures",
    )
    op.drop_index(
        "ix_account_deletion_failures_clerk_user_id",
        table_name="account_deletion_failures",
    )
    op.drop_index("ix_account_deletion_failures_user_id", table_name="account_deletion_failures")
    op.drop_table("account_deletion_failures")
