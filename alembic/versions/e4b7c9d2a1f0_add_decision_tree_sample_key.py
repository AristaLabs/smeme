"""Add durable per-user sample decision-tree identity.

Revision ID: e4b7c9d2a1f0
Revises: d6a1f0e82c91
Create Date: 2026-09-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c9d2a1f0"
down_revision: Union[str, Sequence[str], None] = "d6a1f0e82c91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column("sample_key", sa.String(length=80), nullable=True),
    )
    op.create_unique_constraint(
        "uq_decision_trees_author_sample_key",
        "decision_trees",
        ["author_id", "sample_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_decision_trees_author_sample_key",
        "decision_trees",
        type_="unique",
    )
    op.drop_column("decision_trees", "sample_key")
