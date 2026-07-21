"""billing_downgrade_lifecycle

Revision ID: f7a8b9c0d1e3
Revises: e6f7a8b9c0d2
Create Date: 2026-06-15

Phase 5: subscription cancel/downgrade fields and per-root dormant flag.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a8b9c0d1e3"
down_revision: Union[str, None] = "e6f7a8b9c0d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "subscription_cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "cancellation_explainer_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "cancellation_explainer_acknowledged_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "workflow_pick_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("live_workflow_root_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("free_usage_epoch", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_live_workflow_root_id_qnrs",
        "users",
        "qnrs",
        ["live_workflow_root_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "qnrs",
        sa.Column(
            "billing_dormant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(op.f("ix_qnrs_billing_dormant"), "qnrs", ["billing_dormant"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_qnrs_billing_dormant"), table_name="qnrs", if_exists=True)
    op.drop_column("qnrs", "billing_dormant")
    op.drop_constraint("fk_users_live_workflow_root_id_qnrs", "users", type_="foreignkey")
    op.drop_column("users", "free_usage_epoch")
    op.drop_column("users", "live_workflow_root_id")
    op.drop_column("users", "workflow_pick_required")
    op.drop_column("users", "cancellation_explainer_acknowledged_at")
    op.drop_column("users", "cancellation_explainer_pending")
    op.drop_column("users", "subscription_cancel_at_period_end")
