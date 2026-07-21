"""drop raw_blob from dtq_evaluation_runs

Revision ID: e5f6a7b8c9d0
Revises: c1d2e3f4a5b6
Create Date: 2026-04-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("dtq_evaluation_runs", "raw_blob")


def downgrade() -> None:
    op.add_column(
        "dtq_evaluation_runs",
        sa.Column("raw_blob", sa.Text(), nullable=True),
    )
