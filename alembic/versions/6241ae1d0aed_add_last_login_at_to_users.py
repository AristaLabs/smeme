"""Add last_login_at to users

Revision ID: 6241ae1d0aed
Revises: 4c3c382470ce
Create Date: 2026-02-11 18:15:51.704219

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6241ae1d0aed"
down_revision: Union[str, None] = "4c3c382470ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive only: nullable column, no server_default (existing rows get NULL).
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
