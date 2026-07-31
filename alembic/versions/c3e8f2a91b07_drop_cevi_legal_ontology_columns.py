"""Drop dead CEVI legal-ontology columns.

Revision ID: c3e8f2a91b07
Revises: b1d026a0cce7
Create Date: 2026-07-31

Removes DecisionTree.cevi_legal and ReasoningCompiledArtifact
cevi_legal_validation_* scaffolding (ontology enrichment never shipped).
Recreates the D025 immutability trigger without those artifact columns.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8f2a91b07"
down_revision: Union[str, Sequence[str], None] = "b1d026a0cce7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IMMUTABLE_FN_WITHOUT_LEGAL = """
CREATE OR REPLACE FUNCTION reasoning_compiled_artifacts_immutable_payload()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.ir_json IS DISTINCT FROM OLD.ir_json
       OR NEW.graph_hash IS DISTINCT FROM OLD.graph_hash
       OR NEW.compiler_version IS DISTINCT FROM OLD.compiler_version
       OR NEW.ir_format_version IS DISTINCT FROM OLD.ir_format_version
       OR NEW.cevi_contract_json IS DISTINCT FROM OLD.cevi_contract_json
       OR NEW.cevi_contract_hash IS DISTINCT FROM OLD.cevi_contract_hash
       OR NEW.research_corpus_hash IS DISTINCT FROM OLD.research_corpus_hash
       OR NEW.ir_hash IS DISTINCT FROM OLD.ir_hash
       OR NEW.artifact_hash IS DISTINCT FROM OLD.artifact_hash
       OR NEW.artifact_version IS DISTINCT FROM OLD.artifact_version
       OR NEW.compiled_at IS DISTINCT FROM OLD.compiled_at
    THEN
      RAISE EXCEPTION 'reasoning_compiled_artifacts payload is immutable (D025)';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_IMMUTABLE_FN_WITH_LEGAL = """
CREATE OR REPLACE FUNCTION reasoning_compiled_artifacts_immutable_payload()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.ir_json IS DISTINCT FROM OLD.ir_json
       OR NEW.graph_hash IS DISTINCT FROM OLD.graph_hash
       OR NEW.compiler_version IS DISTINCT FROM OLD.compiler_version
       OR NEW.ir_format_version IS DISTINCT FROM OLD.ir_format_version
       OR NEW.cevi_contract_json IS DISTINCT FROM OLD.cevi_contract_json
       OR NEW.cevi_contract_hash IS DISTINCT FROM OLD.cevi_contract_hash
       OR NEW.research_corpus_hash IS DISTINCT FROM OLD.research_corpus_hash
       OR NEW.ir_hash IS DISTINCT FROM OLD.ir_hash
       OR NEW.artifact_hash IS DISTINCT FROM OLD.artifact_hash
       OR NEW.artifact_version IS DISTINCT FROM OLD.artifact_version
       OR NEW.cevi_legal_validation_status IS DISTINCT FROM OLD.cevi_legal_validation_status
       OR NEW.cevi_legal_validation_started_at IS DISTINCT FROM OLD.cevi_legal_validation_started_at
       OR NEW.cevi_legal_validation_completed_at IS DISTINCT FROM OLD.cevi_legal_validation_completed_at
       OR NEW.cevi_legal_validation_error IS DISTINCT FROM OLD.cevi_legal_validation_error
       OR NEW.compiled_at IS DISTINCT FROM OLD.compiled_at
    THEN
      RAISE EXCEPTION 'reasoning_compiled_artifacts payload is immutable (D025)';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_reasoning_compiled_artifacts_immutable_payload
BEFORE UPDATE ON reasoning_compiled_artifacts
FOR EACH ROW
EXECUTE FUNCTION reasoning_compiled_artifacts_immutable_payload();
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_reasoning_compiled_artifacts_immutable_payload "
            "ON reasoning_compiled_artifacts"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS reasoning_compiled_artifacts_immutable_payload()"))

    op.drop_column("decision_trees", "cevi_legal")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_error")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_completed_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_started_at")
    op.drop_column("reasoning_compiled_artifacts", "cevi_legal_validation_status")

    op.execute(sa.text(_IMMUTABLE_FN_WITHOUT_LEGAL))
    op.execute(sa.text(_IMMUTABLE_TRIGGER))


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_reasoning_compiled_artifacts_immutable_payload "
            "ON reasoning_compiled_artifacts"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS reasoning_compiled_artifacts_immutable_payload()"))

    op.add_column(
        "decision_trees",
        sa.Column(
            "cevi_legal",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_legal_validation_status",
            sa.String(length=20),
            server_default=sa.text("'not_required'"),
            nullable=False,
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_legal_validation_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column(
            "cevi_legal_validation_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("cevi_legal_validation_error", sa.Text(), nullable=True),
    )

    op.execute(sa.text(_IMMUTABLE_FN_WITH_LEGAL))
    op.execute(sa.text(_IMMUTABLE_TRIGGER))
