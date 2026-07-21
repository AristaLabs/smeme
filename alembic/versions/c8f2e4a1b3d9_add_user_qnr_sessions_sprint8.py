"""add_user_qnr_sessions_sprint8

Revision ID: c8f2e4a1b3d9
Revises: bb8be63c9012
Create Date: 2026-02-13

Sprint 8: user_qnr_sessions table for revenue tracking and first-free source of truth.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8f2e4a1b3d9"
down_revision: Union[str, None] = "bb8be63c9012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_qnr_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("first_session_id", sa.Uuid(), nullable=True),
        sa.Column("session_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_qnr_sessions_user_id_users"),
        sa.ForeignKeyConstraint(["qnr_id"], ["qnrs.id"], name="fk_user_qnr_sessions_qnr_id_qnrs"),
        sa.ForeignKeyConstraint(
            ["first_session_id"], ["qnr_sessions.id"], name="fk_user_qnr_sessions_first_session_id_qnr_sessions"
        ),
        sa.PrimaryKeyConstraint("user_id", "qnr_id", name="pk_user_qnr_sessions"),
    )

    # Backfill from qnr_sessions: one row per (user_id, qnr_id) with first_session_id and session_count
    op.execute(
        sa.text("""
        INSERT INTO user_qnr_sessions (user_id, qnr_id, first_session_id, session_count, created_at, updated_at)
        SELECT
            s.user_id,
            s.qnr_id,
            (SELECT id FROM qnr_sessions s2
             WHERE s2.user_id = s.user_id AND s2.qnr_id = s.qnr_id
             ORDER BY s2.created_at ASC
             LIMIT 1),
            COUNT(*)::integer,
            MIN(s.created_at),
            NOW()
        FROM qnr_sessions s
        GROUP BY s.user_id, s.qnr_id
        """)
    )


def downgrade() -> None:
    op.drop_table("user_qnr_sessions")
