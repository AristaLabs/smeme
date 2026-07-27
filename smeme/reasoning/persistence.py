"""Persist reasoning evaluation outcomes for audit and analytics."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import ReasoningCompiledArtifact, ReasoningEvaluationRun
from smeme.reasoning.runtime.evaluate import BlobAuditRecord, EvaluationResult


def _explanation_payload(result: EvaluationResult) -> dict[str, Any]:
    out: dict[str, Any] = dict(result.explanation)
    if result.model_atoms is not None:
        out["model_atoms"] = result.model_atoms
    return out


async def persist_reasoning_evaluation_run(
    db: AsyncSession,
    *,
    decision_tree_id: UUID,
    result: EvaluationResult,
    audit: BlobAuditRecord,
    session_id: UUID | None = None,
    caller_user_id: UUID | None = None,
    ingest_warnings: list[Any] | None = None,
    report: dict[str, Any] | None = None,
    ingest_envelope: dict[str, Any] | None = None,
    artifact: ReasoningCompiledArtifact | None = None,
) -> ReasoningEvaluationRun:
    """Insert one evaluation run row and commit."""
    stamp: dict[str, Any] = {}
    if artifact is not None:
        stamp = {
            "artifact_id": artifact.id,
            "artifact_version": artifact.artifact_version,
            "artifact_hash": artifact.artifact_hash,
            "artifact_graph_hash": artifact.graph_hash,
            "compiled_at": artifact.compiled_at,
        }
    row = ReasoningEvaluationRun(
        decision_tree_id=decision_tree_id,
        session_id=session_id,
        caller_user_id=caller_user_id,
        outcome=result.status,
        evidence_items=audit.evidence_items
        or list((ingest_envelope or {}).get("evidence_items") or []),
        conflict_report=audit.conflict_report,
        user_resolutions=audit.user_resolutions,
        final_facts=audit.final_facts,
        permissive_mode=audit.permissive_mode,
        explanation=_explanation_payload(result),
        triggered_edges=result.triggered_edges,
        minimal_repairs=result.minimal_repairs,
        ingest_warnings=list(ingest_warnings or []),
        report=dict(report or {}),
        ingest_envelope=ingest_envelope,
        **stamp,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
