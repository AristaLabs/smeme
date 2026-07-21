"""Add mcp_discoverable flag for assistant-tools list + evaluate gate.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-01

Product choice: default **false** (strict opt-in). Existing compiled QNRs do not
appear in assistant-tool list or evaluate until the author enables discoverability
on /qnr/mcp — no one-time backfill to true.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qnrs",
        sa.Column(
            "mcp_discoverable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(op.f("ix_qnrs_mcp_discoverable"), "qnrs", ["mcp_discoverable"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_qnrs_mcp_discoverable"), table_name="qnrs")
    op.drop_column("qnrs", "mcp_discoverable")
