"""Align users.is_premium and reasoning_compiled_artifacts qnr_id with SQLModel.

Revision ID: c0d1e2f3a4b7
Revises: a8b9c0d1e2f3
Create Date: 2026-05-07

- users.is_premium: NOT NULL + server default (matches User model).
- reasoning_compiled_artifacts: single unique index on qnr_id (drops redundant
  UniqueConstraint + non-unique index left from ff0011223344).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b7"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET is_premium = false WHERE is_premium IS NULL"))
    op.alter_column(
        "users",
        "is_premium",
        existing_type=sa.Boolean(),
        existing_nullable=True,
        nullable=False,
        server_default=sa.false(),
    )

    op.drop_constraint(
        "uq_reasoning_compiled_artifacts_qnr_id",
        "reasoning_compiled_artifacts",
        type_="unique",
    )
    op.drop_index("ix_reasoning_compiled_artifacts_qnr_id", table_name="reasoning_compiled_artifacts")
    op.create_index(
        "ix_reasoning_compiled_artifacts_qnr_id",
        "reasoning_compiled_artifacts",
        ["qnr_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_reasoning_compiled_artifacts_qnr_id", table_name="reasoning_compiled_artifacts")
    op.create_index(
        "ix_reasoning_compiled_artifacts_qnr_id",
        "reasoning_compiled_artifacts",
        ["qnr_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_reasoning_compiled_artifacts_qnr_id",
        "reasoning_compiled_artifacts",
        ["qnr_id"],
    )

    op.alter_column(
        "users",
        "is_premium",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        nullable=True,
        server_default=sa.false(),
    )
