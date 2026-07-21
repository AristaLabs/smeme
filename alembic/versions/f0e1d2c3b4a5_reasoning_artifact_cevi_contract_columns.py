"""Add nullable CEVI contract columns to reasoning_compiled_artifacts (Phase 2+ reserved).

Revision ID: f0e1d2c3b4a5
Revises: ff0011223344
Create Date: 2026-04-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, None] = "ff0011223344"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_contract_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_contract_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reasoning_compiled_artifacts", "cevi_contract_hash")
    op.drop_column("reasoning_compiled_artifacts", "cevi_contract_json")
