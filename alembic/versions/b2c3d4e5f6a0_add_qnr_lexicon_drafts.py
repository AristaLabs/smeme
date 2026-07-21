"""CEVI: qnr_lexicon_drafts for author Lexicon overlay (keyed by atom id server-side).

Revision ID: b2c3d4e5f6a0
Revises: a9b8c7d6e5f4
Create Date: 2026-04-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a0"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qnr_lexicon_drafts",
        sa.Column(
            "qnr_id",
            sa.Uuid(),
            sa.ForeignKey("qnrs.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "body_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("lexicon_hash", sa.String(length=64), nullable=True),
        sa.Column("graph_hash_at_save", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("qnr_lexicon_drafts")
