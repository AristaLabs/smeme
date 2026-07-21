"""add_stripe_billing_fields

Revision ID: bb8be63c9012
Revises: aa7ad52a8902
Create Date: 2026-02-13

Sprint 7: Stripe Premium + Payment Infrastructure
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "bb8be63c9012"
down_revision: Union[str, None] = "aa7ad52a8902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User: Stripe billing fields
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("stripe_subscription_id", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("subscription_status", sa.String(30), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_premium", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )

    # QNR: per-session price (cents)
    op.add_column(
        "qnrs",
        sa.Column("price_cents", sa.Integer(), nullable=True, server_default="1000"),
    )

    # QNRSession: payment tracking
    op.add_column(
        "qnr_sessions",
        sa.Column("payment_status", sa.String(20), nullable=True, server_default="free"),
    )
    op.add_column(
        "qnr_sessions",
        sa.Column("stripe_checkout_session_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_qnr_sessions_stripe_checkout_session_id",
        "qnr_sessions",
        ["stripe_checkout_session_id"],
        unique=False,
    )

    # stripe_events: webhook idempotency
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("type", sa.String(100), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_index(
        "ix_qnr_sessions_stripe_checkout_session_id",
        table_name="qnr_sessions",
    )
    op.drop_column("qnr_sessions", "stripe_checkout_session_id")
    op.drop_column("qnr_sessions", "payment_status")
    op.drop_column("qnrs", "price_cents")
    op.drop_column("users", "is_premium")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
