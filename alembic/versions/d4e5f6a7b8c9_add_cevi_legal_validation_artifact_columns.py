"""CEVI: legal validation status columns on reasoning_compiled_artifacts.

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a0
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "b2c3d4e5f6a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_legal_validation_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_required",
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_legal_validation_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_legal_validation_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_legal_validation_error", sa.Text(), nullable=True),
    )
    op.alter_column(
        "reasoning_compiled_artifacts",
        "cevi_legal_validation_status",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_error")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_completed_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_started_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_status")
