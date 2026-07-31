"""Append-only compiled artifact deploy and current-artifact loaders (D025)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.reasoning.artifact_identity import compute_identity_fields_from_stored_artifact
from smeme.reasoning.graph_hash import canonical_graph_hash


class PublishGraphChangedError(RuntimeError):
    """A saved graph changed while a Deploy candidate was being compiled."""


async def load_current_compiled_artifact(
    db: AsyncSession,
    decision_tree: DecisionTree,
) -> ReasoningCompiledArtifact | None:
    """Follow ``DecisionTree.current_artifact_id``; never pick newest-by-time."""
    pointer = decision_tree.current_artifact_id
    if pointer is None:
        return None
    result = await db.execute(
        select(ReasoningCompiledArtifact).where(
            ReasoningCompiledArtifact.id == pointer,
            ReasoningCompiledArtifact.decision_tree_id == decision_tree.id,
        )
    )
    return result.scalar_one_or_none()


async def load_current_compiled_artifacts_for_trees(
    db: AsyncSession,
    decision_trees: list[DecisionTree],
) -> dict[UUID, ReasoningCompiledArtifact]:
    if not decision_trees:
        return {}
    pointer_ids = [
        t.current_artifact_id for t in decision_trees if t.current_artifact_id is not None
    ]
    if not pointer_ids:
        return {}
    result = await db.execute(
        select(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.id.in_(pointer_ids))
    )
    by_id = {a.id: a for a in result.scalars().all()}
    out: dict[UUID, ReasoningCompiledArtifact] = {}
    for tree in decision_trees:
        if tree.current_artifact_id is None:
            continue
        art = by_id.get(tree.current_artifact_id)
        if art is not None and art.decision_tree_id == tree.id:
            out[tree.id] = art
    return out


async def persist_compiled_artifact_append_only(
    db: AsyncSession,
    *,
    decision_tree: DecisionTree,
    ir_json: dict[str, Any],
    graph_hash: str,
    ir_format_version: int,
    compiler_version: str,
    cevi_contract_json: dict[str, Any] | None,
    cevi_contract_hash: str | None,
    research_corpus_hash: str | None,
) -> ReasoningCompiledArtifact:
    """Insert a new immutable artifact or return the current row when identity matches."""
    locked = (
        await db.execute(
            select(DecisionTree)
            .where(DecisionTree.id == decision_tree.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one()
    if canonical_graph_hash(parse_graph_data(locked)) != graph_hash:
        raise PublishGraphChangedError(
            "The saved decision tree changed while Deploy was preparing. Retry Deploy."
        )

    candidate = ReasoningCompiledArtifact(
        decision_tree_id=locked.id,
        ir_json=ir_json,
        graph_hash=graph_hash,
        compiler_version=compiler_version,
        ir_format_version=ir_format_version,
        cevi_contract_json=cevi_contract_json,
        cevi_contract_hash=cevi_contract_hash,
        research_corpus_hash=research_corpus_hash,
    )
    ir_hash, artifact_hash = compute_identity_fields_from_stored_artifact(candidate)
    candidate.ir_hash = ir_hash
    candidate.artifact_hash = artifact_hash

    current = await load_current_compiled_artifact(db, locked)
    if current is not None and current.artifact_hash == artifact_hash:
        locked.reasoning_status = "compiled"
        db.add(locked)
        return current

    max_ver = await db.scalar(
        select(func.max(ReasoningCompiledArtifact.artifact_version)).where(
            ReasoningCompiledArtifact.decision_tree_id == locked.id
        )
    )
    next_version = int(max_ver or 0) + 1
    candidate.artifact_version = next_version

    db.add(candidate)
    await db.flush()

    locked.current_artifact_id = candidate.id
    locked.reasoning_status = "compiled"
    db.add(locked)
    decision_tree.current_artifact_id = candidate.id
    decision_tree.reasoning_status = "compiled"
    return candidate
