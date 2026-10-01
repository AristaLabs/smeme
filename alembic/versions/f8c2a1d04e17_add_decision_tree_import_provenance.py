"""Add nullable import-copy provenance on decision trees.

Revision ID: f8c2a1d04e17
Revises: e4b7c9d2a1f0
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c2a1d04e17"
down_revision: Union[str, Sequence[str], None] = "e4b7c9d2a1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column("import_filename", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "decision_trees",
        sa.Column("import_export_version", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "decision_trees",
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("decision_trees", "imported_at")
    op.drop_column("decision_trees", "import_export_version")
    op.drop_column("decision_trees", "import_filename")
