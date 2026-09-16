"""Shared Deploy path: validate, compile IR, persist D025 artifact.

Dashboard publish and ``ensure_sample_tree`` both call this so compile is not
reimplemented. Does not set Listed and does not commit.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact
from smeme.decision_tree.helpers.db_queries import (
    get_decision_tree_research_corpus_row,
    parse_graph_data,
)
from smeme.reasoning.artifact_deploy import persist_compiled_artifact_append_only
from smeme.reasoning.cevi.contract_diagnostics import (
    diagnose_published_evidence_contract,
    diagnostics_log_payload,
)
from smeme.reasoning.cevi.induction import induce_published_evidence_contract_at_publish
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.publish_readiness import PublishReadiness, assess_publish_readiness
from smeme.reasoning.published_evidence_contract import (
    cevi_fingerprint,
    contract_to_stored_json,
)
from smeme.reasoning.version import REASONING_COMPILER_VERSION

logger = logging.getLogger(__name__)


class DeployNotReadyError(RuntimeError):
    """Graph failed the same Deploy gate the dashboard uses."""

    def __init__(self, readiness: PublishReadiness) -> None:
        self.readiness = readiness
        super().__init__("Decision tree is not ready to Deploy")


async def compile_and_persist_current_graph(
    db: AsyncSession,
    decision_tree: DecisionTree,
) -> ReasoningCompiledArtifact:
    """Compile the saved graph and persist the current artifact (D025 stamps)."""
    graph = parse_graph_data(decision_tree)
    readiness = await assess_publish_readiness(graph)
    if not readiness.ready:
        raise DeployNotReadyError(readiness)

    ir_json = readiness.ir_json
    graph_hash = readiness.graph_hash
    assert ir_json is not None  # noqa: S101 — guarded by readiness.ready
    assert graph_hash is not None  # noqa: S101

    corp_row = await get_decision_tree_research_corpus_row(db, decision_tree.id)
    corpus_body = corp_row.body_text if corp_row else None

    cev_contract, corpus_snapshot = induce_published_evidence_contract_at_publish(
        ir_json=ir_json,
        graph=graph,
        graph_hash=graph_hash,
        ir_format_version=IR_FORMAT_VERSION,
        corpus_body=corpus_body,
    )
    cevi_diag = diagnose_published_evidence_contract(cev_contract)
    logger.info(
        "cevi_publish_contract",
        extra={
            "decision_tree_id": str(decision_tree.id),
            "cevi_contract_diagnostics": diagnostics_log_payload(cevi_diag),
        },
    )

    cevi_contract_json = contract_to_stored_json(cev_contract)
    cevi_contract_hash = cevi_fingerprint(cev_contract)
    research_corpus_hash = corpus_snapshot.sha256_hex

    artifact = await persist_compiled_artifact_append_only(
        db,
        decision_tree=decision_tree,
        ir_json=ir_json,
        graph_hash=graph_hash,
        ir_format_version=IR_FORMAT_VERSION,
        cevi_contract_json=cevi_contract_json,
        cevi_contract_hash=cevi_contract_hash,
        research_corpus_hash=research_corpus_hash,
        compiler_version=REASONING_COMPILER_VERSION,
    )
    await db.flush()
    logger.info(
        "Compiled reasoning artifact",
        extra={
            "decision_tree_id": str(decision_tree.id),
            "artifact_version": artifact.artifact_version,
            "artifact_hash": artifact.artifact_hash,
        },
    )
    return artifact
