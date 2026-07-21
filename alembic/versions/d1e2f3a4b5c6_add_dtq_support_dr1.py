"""add_dtq_support_dr1

DR-1: dtq_status on qnrs, dtq_compiled_theories (serialized compile artifact + graph_hash).

Revision ID: d1e2f3a4b5c6
Revises: c8f2e4a1b3d9
Create Date: 2026-03-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c8f2e4a1b3d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("qnrs", sa.Column("dtq_status", sa.String(length=20), nullable=True))
    op.create_index("ix_qnrs_dtq_status", "qnrs", ["dtq_status"], unique=False)
    op.create_check_constraint(
        "ck_qnrs_dtq_status_valid",
        "qnrs",
        "dtq_status IS NULL OR dtq_status IN ('pending', 'compiled', 'failed')",
    )
    op.create_table(
        "dtq_compiled_theories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("qnr_id", sa.Uuid(), nullable=False),
        sa.Column("theory_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("graph_hash", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=20), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(
            ["qnr_id"],
            ["qnrs.id"],
            name="fk_dtq_compiled_theories_qnr_id_qnrs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dtq_compiled_theories"),
        sa.UniqueConstraint("qnr_id", name="uq_dtq_compiled_theories_qnr_id"),
    )
    op.create_index("ix_dtq_compiled_theories_qnr_id", "dtq_compiled_theories", ["qnr_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dtq_compiled_theories_qnr_id", table_name="dtq_compiled_theories")
    op.drop_table("dtq_compiled_theories")
    op.drop_constraint("ck_qnrs_dtq_status_valid", "qnrs", type_="check")
    op.drop_index("ix_qnrs_dtq_status", table_name="qnrs")
    op.drop_column("qnrs", "dtq_status")
