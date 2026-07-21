"""CEVI: LLM Lexicon enrichment lifecycle columns on reasoning_compiled_artifacts.

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_llm_enrichment_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_required",
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_llm_enrichment_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_llm_enrichment_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_llm_enrichment_error", sa.Text(), nullable=True),
    )
    op.alter_column(
        "reasoning_compiled_artifacts",
        "cevi_llm_enrichment_status",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("reasoning_compiled_artifacts", "cevi_llm_enrichment_error")
    op.drop_column("reasoning_compiled_artifacts", "cevi_llm_enrichment_completed_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_llm_enrichment_started_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_llm_enrichment_status")
