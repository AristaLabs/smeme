"""CEVI: research corpus table, qnr.cevi_legal, artifact.research_corpus_hash.

Revision ID: a9b8c7d6e5f4
Revises: f0e1d2c3b4a5
Create Date: 2026-04-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f0e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "qnrs",
        sa.Column(
            "cevi_legal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "qnr_research_corpora",
        sa.Column("qnr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["qnr_id"], ["qnrs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("qnr_id"),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("research_corpus_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reasoning_compiled_artifacts", "research_corpus_hash")
    op.drop_table("qnr_research_corpora")
    op.drop_column("qnrs", "cevi_legal")
