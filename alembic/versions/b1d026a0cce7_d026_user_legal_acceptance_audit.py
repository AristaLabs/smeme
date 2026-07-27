"""D026: nullable legal-acceptance audit columns on users.

Revision ID: b1d026a0cce7
Revises: a7c3e9f1b204
Create Date: 2026-07-26

Additive only. Existing rows keep NULL audit fields (grandfather policy).
Do not backfill or tighten to NOT NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1d026a0cce7"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("legal_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("terms_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("privacy_version", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "privacy_version")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "legal_accepted_at")
