"""remove_session_pay_columns

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30

Phase 1.5: Drop per-session payment columns and the user_qnr_sessions table.
All session-pay code was removed in Phase 1 (code-only). This migration
removes the DB artefacts.

Downgrade recreates the schema with empty tables / nulled columns — it does
NOT restore any payment data that existed before upgrade.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop user_qnr_sessions (Sprint 8 revenue-attribution table)
    op.drop_table("user_qnr_sessions")

    # Drop payment-tracking columns from qnr_sessions (Sprint 7)
    op.drop_index(
        "ix_qnrsession_stripe_checkout_session_id",
        table_name="qnr_sessions",
        if_exists=True,
    )
    op.drop_column("qnr_sessions", "stripe_checkout_session_id")
    op.drop_column("qnr_sessions", "payment_status")

    # Drop per-session price from qnrs (Sprint 7)
    op.drop_column("qnrs", "price_cents")


def downgrade() -> None:
    # Restore price_cents on qnrs (nullable so existing rows get NULL)
    op.add_column(
        "qnrs",
        sa.Column(
            "price_cents",
            sa.Integer(),
            nullable=True,
            server_default="1000",
        ),
    )

    # Restore payment columns on qnr_sessions
    op.add_column(
        "qnr_sessions",
        sa.Column(
            "payment_status",
            sa.String(20),
            nullable=False,
            server_default="free",
        ),
    )
    op.add_column(
        "qnr_sessions",
        sa.Column(
            "stripe_checkout_session_id",
            sa.String(255),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_qnrsession_stripe_checkout_session_id",
        "qnr_sessions",
        ["stripe_checkout_session_id"],
    )

    # Recreate user_qnr_sessions (empty — downgrade does NOT restore data)
    op.create_table(
        "user_qnr_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("first_session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "session_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_qnr_sessions_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["qnr_id"], ["qnrs.id"], name="fk_user_qnr_sessions_qnr_id_qnrs"
        ),
        sa.ForeignKeyConstraint(
            ["first_session_id"],
            ["qnr_sessions.id"],
            name="fk_user_qnr_sessions_first_session_id_qnr_sessions",
        ),
        sa.PrimaryKeyConstraint("user_id", "qnr_id", name="pk_user_qnr_sessions"),
    )
