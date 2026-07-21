"""add_subscription_period_columns

Revision ID: e6f7a8b9c0d2
Revises: d5e6f7a8b9c0
Create Date: 2026-06-12

Stripe billing period boundaries for Pro quota windows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e6f7a8b9c0d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("subscription_period_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("subscription_period_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_period_end")
    op.drop_column("users", "subscription_period_start")
