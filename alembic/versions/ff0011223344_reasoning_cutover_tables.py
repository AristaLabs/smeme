"""reasoning_cutover — replace DTQ tables/column with reasoning_* (no data migration).

Revision ID: ff0011223344
Revises: e5f6a7b8c9d0
Create Date: 2026-04-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ff0011223344"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("dtq_evaluation_runs")
    op.drop_table("dtq_compiled_theories")
    op.drop_constraint("ck_qnrs_dtq_status_valid", "qnrs", type_="check")
    op.drop_index("ix_qnrs_dtq_status", table_name="qnrs")
    op.drop_column("qnrs", "dtq_status")

    op.add_column("qnrs", sa.Column("reasoning_status", sa.String(length=20), nullable=True))
    op.create_index("ix_qnrs_reasoning_status", "qnrs", ["reasoning_status"], unique=False)
    op.create_check_constraint(
        "ck_qnrs_reasoning_status_valid",
        "qnrs",
        "reasoning_status IS NULL OR reasoning_status IN ('pending', 'compiled', 'failed')",
    )

    op.create_table(
        "reasoning_compiled_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column(
            "ir_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("graph_hash", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=20), nullable=False),
        sa.Column("ir_format_version", sa.Integer(), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["qnr_id"],
            ["qnrs.id"],
            name="fk_reasoning_compiled_artifacts_qnr_id_qnrs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reasoning_compiled_artifacts"),
        sa.UniqueConstraint("qnr_id", name="uq_reasoning_compiled_artifacts_qnr_id"),
    )
    op.create_index(
        "ix_reasoning_compiled_artifacts_qnr_id",
        "reasoning_compiled_artifacts",
        ["qnr_id"],
        unique=False,
    )

    op.create_table(
        "reasoning_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("caller_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
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
            name="fk_reasoning_evaluation_runs_qnr_id_qnrs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["qnr_sessions.id"],
            name="fk_reasoning_evaluation_runs_session_id_qnr_sessions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["caller_user_id"],
            ["users.id"],
            name="fk_reasoning_evaluation_runs_caller_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reasoning_evaluation_runs"),
    )
    op.create_index(
        "ix_reasoning_evaluation_runs_qnr_id", "reasoning_evaluation_runs", ["qnr_id"], unique=False
    )
    op.create_index(
        "ix_reasoning_evaluation_runs_session_id",
        "reasoning_evaluation_runs",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_reasoning_evaluation_runs_outcome", "reasoning_evaluation_runs", ["outcome"], unique=False
    )
    op.create_index(
        "ix_reasoning_evaluation_runs_qnr_created",
        "reasoning_evaluation_runs",
        ["qnr_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reasoning_evaluation_runs_qnr_created", table_name="reasoning_evaluation_runs")
    op.drop_index("ix_reasoning_evaluation_runs_outcome", table_name="reasoning_evaluation_runs")
    op.drop_index("ix_reasoning_evaluation_runs_session_id", table_name="reasoning_evaluation_runs")
    op.drop_index("ix_reasoning_evaluation_runs_qnr_id", table_name="reasoning_evaluation_runs")
    op.drop_table("reasoning_evaluation_runs")

    op.drop_index("ix_reasoning_compiled_artifacts_qnr_id", table_name="reasoning_compiled_artifacts")
    op.drop_table("reasoning_compiled_artifacts")

    op.drop_constraint("ck_qnrs_reasoning_status_valid", "qnrs", type_="check")
    op.drop_index("ix_qnrs_reasoning_status", table_name="qnrs")
    op.drop_column("qnrs", "reasoning_status")

    op.add_column("qnrs", sa.Column("dtq_status", sa.String(length=20), nullable=True))
    op.create_index("ix_qnrs_dtq_status", "qnrs", ["dtq_status"], unique=False)
    op.create_check_constraint(
        "ck_qnrs_dtq_status_valid",
        "qnrs",
        "dtq_status IS NULL OR dtq_status IN ('pending', 'compiled', 'failed')",
    )

    op.create_table(
        "dtq_compiled_theories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column(
            "theory_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("graph_hash", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=20), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["qnr_id"],
            ["qnrs.id"],
            name="fk_dtq_compiled_theories_qnr_id_qnrs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dtq_compiled_theories"),
        sa.UniqueConstraint("qnr_id", name="uq_dtq_compiled_theories_qnr_id"),
    )
    op.create_index("ix_dtq_compiled_theories_qnr_id", "dtq_compiled_theories", ["qnr_id"], unique=False)

    op.create_table(
        "dtq_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("caller_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
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
