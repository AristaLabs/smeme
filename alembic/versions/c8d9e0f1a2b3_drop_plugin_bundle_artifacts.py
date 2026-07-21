"""Drop retired Cowork plugin bundle gate and manifest table.

Revision ID: c8d9e0f1a2b3
Revises: f7a8b9c0d1e3
Create Date: 2026-07-18

Installable plugin zip distribution was retired (connector + guidance only).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "f7a8b9c0d1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_plugin_bundle_releases_single_active", table_name="plugin_bundle_releases")
    op.drop_index(
        "ix_plugin_bundle_releases_active_effective_at", table_name="plugin_bundle_releases"
    )
    op.drop_table("plugin_bundle_releases")
    op.drop_column("users", "plugin_bundle_unlock_email_sent_at")
    op.drop_column("users", "plugin_bundle_gate_unlocked_at")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("plugin_bundle_gate_unlocked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("plugin_bundle_unlock_email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "plugin_bundle_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semver", sa.String(length=64), nullable=False),
        sa.Column("artifact_url", sa.String(length=2048), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plugin_bundle_releases"),
    )
    op.create_index(
        "ix_plugin_bundle_releases_active_effective_at",
        "plugin_bundle_releases",
        ["is_active", "effective_at"],
        unique=False,
    )
    op.create_index(
        "uq_plugin_bundle_releases_single_active",
        "plugin_bundle_releases",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
