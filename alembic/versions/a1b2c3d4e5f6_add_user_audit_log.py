"""add user_audit_log table

Revision ID: a1b2c3d4e5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-03-30

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a1b2c3d4e5f6"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("event_metadata", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_audit_log_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_audit_log"),
    )
    op.create_index("ix_user_audit_log_user_id", "user_audit_log", ["user_id"])
    op.create_index("ix_user_audit_log_event_type", "user_audit_log", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_user_audit_log_event_type", table_name="user_audit_log")
    op.drop_index("ix_user_audit_log_user_id", table_name="user_audit_log")
    op.drop_table("user_audit_log")
