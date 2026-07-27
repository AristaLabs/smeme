"""D025 append-only artifact identity and evaluation stamps.

Revision ID: a7c3e9f1b204
Revises: d8829c1bb096
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c3e9f1b204"
down_revision = "d8829c1bb096"
branch_labels = None
depends_on = None


def _backfill_artifact_identity(connection: sa.Connection) -> None:
    from smeme.reasoning.artifact_identity import (
        ArtifactIntegrityError,
        compute_identity_fields_from_stored_artifact,
    )
    from smeme.core.models import ReasoningCompiledArtifact

    rows = connection.execute(
        sa.text(
            """
            SELECT id, decision_tree_id, ir_json, graph_hash, compiler_version,
                   ir_format_version, cevi_contract_json, cevi_contract_hash,
                   research_corpus_hash, cevi_legal_validation_status,
                   cevi_legal_validation_started_at, cevi_legal_validation_completed_at,
                   cevi_legal_validation_error, compiled_at
            FROM reasoning_compiled_artifacts
            """
        )
    ).mappings().all()

    per_tree = Counter(row["decision_tree_id"] for row in rows)
    adopted_by_tree: dict[UUID, UUID] = {}

    for row in rows:
        artifact = ReasoningCompiledArtifact(
            id=row["id"],
            decision_tree_id=row["decision_tree_id"],
            ir_json=row["ir_json"],
            graph_hash=row["graph_hash"],
            compiler_version=row["compiler_version"],
            ir_format_version=row["ir_format_version"],
            cevi_contract_json=row["cevi_contract_json"],
            cevi_contract_hash=row["cevi_contract_hash"],
            research_corpus_hash=row["research_corpus_hash"],
            cevi_legal_validation_status=row["cevi_legal_validation_status"],
            cevi_legal_validation_started_at=row["cevi_legal_validation_started_at"],
            cevi_legal_validation_completed_at=row["cevi_legal_validation_completed_at"],
            cevi_legal_validation_error=row["cevi_legal_validation_error"],
            compiled_at=row["compiled_at"],
        )
        try:
            ir_hash, artifact_hash = compute_identity_fields_from_stored_artifact(artifact)
        except ArtifactIntegrityError:
            continue
        connection.execute(
            sa.text(
                """
                UPDATE reasoning_compiled_artifacts
                SET ir_hash = :ir_hash,
                    artifact_hash = :artifact_hash,
                    artifact_version = 1
                WHERE id = :id
                """
            ),
            {"id": row["id"], "ir_hash": ir_hash, "artifact_hash": artifact_hash},
        )
        if per_tree[row["decision_tree_id"]] == 1:
            adopted_by_tree[row["decision_tree_id"]] = row["id"]

    for tree_id, artifact_id in adopted_by_tree.items():
        connection.execute(
            sa.text(
                """
                UPDATE decision_trees
                SET current_artifact_id = :artifact_id
                WHERE id = :tree_id
                """
            ),
            {"tree_id": tree_id, "artifact_id": artifact_id},
        )


def upgrade() -> None:
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("ir_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("artifact_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "reasoning_compiled_artifacts",
        sa.Column("artifact_version", sa.BigInteger(), nullable=True),
    )

    op.add_column(
        "decision_trees",
        sa.Column("current_artifact_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_decision_trees_current_artifact_id"),
        "decision_trees",
        ["current_artifact_id"],
        unique=False,
    )

    op.add_column(
        "reasoning_evaluation_runs",
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "reasoning_evaluation_runs",
        sa.Column("artifact_version", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "reasoning_evaluation_runs",
        sa.Column("artifact_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "reasoning_evaluation_runs",
        sa.Column("artifact_graph_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "reasoning_evaluation_runs",
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_reasoning_evaluation_runs_artifact_id"),
        "reasoning_evaluation_runs",
        ["artifact_id"],
        unique=False,
    )

    op.drop_index(
        op.f("ix_reasoning_compiled_artifacts_decision_tree_id"),
        table_name="reasoning_compiled_artifacts",
    )
    op.create_index(
        op.f("ix_reasoning_compiled_artifacts_decision_tree_id"),
        "reasoning_compiled_artifacts",
        ["decision_tree_id"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_reasoning_compiled_artifacts_id_tree",
        "reasoning_compiled_artifacts",
        ["id", "decision_tree_id"],
    )
    op.create_index(
        "uq_reasoning_compiled_artifacts_tree_version",
        "reasoning_compiled_artifacts",
        ["decision_tree_id", "artifact_version"],
        unique=True,
        postgresql_where=sa.text("artifact_version IS NOT NULL"),
        sqlite_where=sa.text("artifact_version IS NOT NULL"),
    )
    op.create_index(
        "uq_reasoning_compiled_artifacts_tree_orphan",
        "reasoning_compiled_artifacts",
        ["decision_tree_id"],
        unique=True,
        postgresql_where=sa.text("artifact_version IS NULL"),
        sqlite_where=sa.text("artifact_version IS NULL"),
    )

    bind = op.get_bind()
    _backfill_artifact_identity(bind)

    op.create_foreign_key(
        op.f("fk_decision_trees_current_artifact_id_reasoning_compiled_artifacts"),
        "decision_trees",
        "reasoning_compiled_artifacts",
        ["current_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_reasoning_evaluation_runs_artifact_id_reasoning_compiled_artifacts"),
        "reasoning_evaluation_runs",
        "reasoning_compiled_artifacts",
        ["artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        sa.text(
            """
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
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_reasoning_compiled_artifacts_immutable_payload
            BEFORE UPDATE ON reasoning_compiled_artifacts
            FOR EACH ROW
            EXECUTE FUNCTION reasoning_compiled_artifacts_immutable_payload();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION decision_trees_reject_incomplete_current_artifact()
            RETURNS trigger AS $$
            DECLARE
              art RECORD;
            BEGIN
              IF NEW.current_artifact_id IS NULL THEN
                RETURN NEW;
              END IF;
              SELECT decision_tree_id, artifact_version, artifact_hash, ir_hash
              INTO art
              FROM reasoning_compiled_artifacts
              WHERE id = NEW.current_artifact_id;
              IF NOT FOUND THEN
                RAISE EXCEPTION 'current_artifact_id references missing artifact';
              END IF;
              IF art.decision_tree_id IS DISTINCT FROM NEW.id THEN
                RAISE EXCEPTION 'current_artifact_id must reference same decision tree';
              END IF;
              IF art.artifact_version IS NULL OR art.artifact_hash IS NULL OR art.ir_hash IS NULL THEN
                RAISE EXCEPTION 'current_artifact_id points at incomplete artifact identity';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_decision_trees_reject_incomplete_current_artifact
            BEFORE INSERT OR UPDATE OF current_artifact_id ON decision_trees
            FOR EACH ROW
            EXECUTE FUNCTION decision_trees_reject_incomplete_current_artifact();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_decision_trees_reject_incomplete_current_artifact ON decision_trees"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS decision_trees_reject_incomplete_current_artifact()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_reasoning_compiled_artifacts_immutable_payload ON reasoning_compiled_artifacts"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reasoning_compiled_artifacts_immutable_payload()"))

    op.drop_constraint(
        op.f("fk_reasoning_evaluation_runs_artifact_id_reasoning_compiled_artifacts"),
        "reasoning_evaluation_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_decision_trees_current_artifact_id_reasoning_compiled_artifacts"),
        "decision_trees",
        type_="foreignkey",
    )

    op.drop_index("uq_reasoning_compiled_artifacts_tree_orphan", table_name="reasoning_compiled_artifacts")
    op.drop_index("uq_reasoning_compiled_artifacts_tree_version", table_name="reasoning_compiled_artifacts")
    op.drop_constraint("uq_reasoning_compiled_artifacts_id_tree", "reasoning_compiled_artifacts", type_="unique")

    op.drop_index(
        op.f("ix_reasoning_compiled_artifacts_decision_tree_id"),
        table_name="reasoning_compiled_artifacts",
    )
    op.create_index(
        op.f("ix_reasoning_compiled_artifacts_decision_tree_id"),
        "reasoning_compiled_artifacts",
        ["decision_tree_id"],
        unique=True,
    )

    op.drop_index(op.f("ix_reasoning_evaluation_runs_artifact_id"), table_name="reasoning_evaluation_runs")
    op.drop_column("reasoning_evaluation_runs", "compiled_at")
    op.drop_column("reasoning_evaluation_runs", "artifact_graph_hash")
    op.drop_column("reasoning_evaluation_runs", "artifact_hash")
    op.drop_column("reasoning_evaluation_runs", "artifact_version")
    op.drop_column("reasoning_evaluation_runs", "artifact_id")

    op.drop_index(op.f("ix_decision_trees_current_artifact_id"), table_name="decision_trees")
    op.drop_column("decision_trees", "current_artifact_id")

    op.drop_column("reasoning_compiled_artifacts", "artifact_version")
    op.drop_column("reasoning_compiled_artifacts", "artifact_hash")
    op.drop_column("reasoning_compiled_artifacts", "ir_hash")
