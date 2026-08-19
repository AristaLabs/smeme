"""Inquire Phase 6: durable inquiry sessions.

Revision ID: d6a1f0e82c91
Revises: c3e8f2a91b07
Create Date: 2026-08-18

Adds inquiry_sessions + admitted/verified rows, mutation receipts, and
typed session events. Artifact FK is nullable ON DELETE SET NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6a1f0e82c91"
down_revision: Union[str, Sequence[str], None] = "c3e8f2a91b07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inquiry_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("decision_tree_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_identity", sa.String(length=64), nullable=False),
        sa.Column("worksheet_catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pv_version", sa.String(length=255), nullable=False),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stop_reason", sa.String(length=80), nullable=True),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["reasoning_compiled_artifacts.id"],
            name=op.f("fk_inquiry_sessions_artifact_id_reasoning_compiled_artifacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decision_tree_id"],
            ["decision_trees.id"],
            name=op.f("fk_inquiry_sessions_decision_tree_id_decision_trees"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_inquiry_sessions_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_sessions")),
    )
    op.create_index(
        op.f("ix_inquiry_sessions_artifact_id"),
        "inquiry_sessions",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inquiry_sessions_decision_tree_id"),
        "inquiry_sessions",
        ["decision_tree_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inquiry_sessions_owner_user_id"),
        "inquiry_sessions",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inquiry_sessions_status"),
        "inquiry_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_inquiry_sessions_owner_status",
        "inquiry_sessions",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_inquiry_sessions_tree_created",
        "inquiry_sessions",
        ["decision_tree_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "inquiry_admitted_assertions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.String(length=255), nullable=False),
        sa.Column("option", sa.String(length=512), nullable=False),
        sa.Column("provenance_id", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["inquiry_sessions.id"],
            name=op.f("fk_inquiry_admitted_assertions_session_id_inquiry_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_admitted_assertions")),
        sa.UniqueConstraint(
            "session_id",
            "question_id",
            name="uq_inquiry_admitted_assertions_session_question",
        ),
    )
    op.create_index(
        op.f("ix_inquiry_admitted_assertions_session_id"),
        "inquiry_admitted_assertions",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "inquiry_verified_assertions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_identity", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=255), nullable=False),
        sa.Column("option", sa.String(length=512), nullable=False),
        sa.Column("provenance_identity", sa.String(length=512), nullable=False),
        sa.Column("pv_version", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["inquiry_sessions.id"],
            name=op.f("fk_inquiry_verified_assertions_session_id_inquiry_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_verified_assertions")),
        sa.UniqueConstraint(
            "session_id",
            "artifact_identity",
            "question_id",
            "option",
            "provenance_identity",
            "pv_version",
            name="uq_inquiry_verified_assertions_key",
        ),
    )
    op.create_index(
        op.f("ix_inquiry_verified_assertions_session_id"),
        "inquiry_verified_assertions",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "inquiry_mutation_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["inquiry_sessions.id"],
            name=op.f("fk_inquiry_mutation_receipts_session_id_inquiry_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_mutation_receipts")),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_inquiry_mutation_receipts_session_key",
        ),
    )
    op.create_index(
        op.f("ix_inquiry_mutation_receipts_session_id"),
        "inquiry_mutation_receipts",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "inquiry_session_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["inquiry_mutation_receipts.id"],
            name=op.f("fk_inquiry_session_events_receipt_id_inquiry_mutation_receipts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["inquiry_sessions.id"],
            name=op.f("fk_inquiry_session_events_session_id_inquiry_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inquiry_session_events")),
    )
    op.create_index(
        op.f("ix_inquiry_session_events_session_id"),
        "inquiry_session_events",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_inquiry_session_events_session_created",
        "inquiry_session_events",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inquiry_session_events_session_created",
        table_name="inquiry_session_events",
    )
    op.drop_index(
        op.f("ix_inquiry_session_events_session_id"),
        table_name="inquiry_session_events",
    )
    op.drop_table("inquiry_session_events")
    op.drop_index(
        op.f("ix_inquiry_mutation_receipts_session_id"),
        table_name="inquiry_mutation_receipts",
    )
    op.drop_table("inquiry_mutation_receipts")
    op.drop_index(
        op.f("ix_inquiry_verified_assertions_session_id"),
        table_name="inquiry_verified_assertions",
    )
    op.drop_table("inquiry_verified_assertions")
    op.drop_index(
        op.f("ix_inquiry_admitted_assertions_session_id"),
        table_name="inquiry_admitted_assertions",
    )
    op.drop_table("inquiry_admitted_assertions")
    op.drop_index("ix_inquiry_sessions_tree_created", table_name="inquiry_sessions")
    op.drop_index("ix_inquiry_sessions_owner_status", table_name="inquiry_sessions")
    op.drop_index(op.f("ix_inquiry_sessions_status"), table_name="inquiry_sessions")
    op.drop_index(op.f("ix_inquiry_sessions_owner_user_id"), table_name="inquiry_sessions")
    op.drop_index(op.f("ix_inquiry_sessions_decision_tree_id"), table_name="inquiry_sessions")
    op.drop_index(op.f("ix_inquiry_sessions_artifact_id"), table_name="inquiry_sessions")
    op.drop_table("inquiry_sessions")
