"""add_dtq_evaluation_runs_dr2

DR-2: persist DTQ evaluation runs (audit + outcome).

Revision ID: e2b3c4d5f6a7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2b3c4d5f6a7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dtq_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("caller_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("raw_blob", sa.Text(), nullable=True),
        sa.Column(
            "evidence_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("conflict_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("user_resolutions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "final_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("permissive_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "triggered_edges",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("minimal_repairs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["qnr_id"],
            ["qnrs.id"],
            name="fk_dtq_evaluation_runs_qnr_id_qnrs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["qnr_sessions.id"],
            name="fk_dtq_evaluation_runs_session_id_qnr_sessions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["caller_user_id"],
            ["users.id"],
            name="fk_dtq_evaluation_runs_caller_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dtq_evaluation_runs"),
    )
    op.create_index("ix_dtq_evaluation_runs_qnr_id", "dtq_evaluation_runs", ["qnr_id"], unique=False)
    op.create_index(
        "ix_dtq_evaluation_runs_session_id", "dtq_evaluation_runs", ["session_id"], unique=False
    )
    op.create_index("ix_dtq_evaluation_runs_outcome", "dtq_evaluation_runs", ["outcome"], unique=False)
    op.create_index(
        "ix_dtq_evaluation_runs_qnr_created",
        "dtq_evaluation_runs",
        ["qnr_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dtq_evaluation_runs_qnr_created", table_name="dtq_evaluation_runs")
    op.drop_index("ix_dtq_evaluation_runs_outcome", table_name="dtq_evaluation_runs")
    op.drop_index("ix_dtq_evaluation_runs_session_id", table_name="dtq_evaluation_runs")
    op.drop_index("ix_dtq_evaluation_runs_qnr_id", table_name="dtq_evaluation_runs")
    op.drop_table("dtq_evaluation_runs")
