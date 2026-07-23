"""Publish-time CEVI contract induction (deterministic corpus_partial + corpus digest)."""

from __future__ import annotations

from typing import Any

from smeme.decision_tree.models import DTGraph
from smeme.reasoning.cevi.atom_catalog import canonical_ir_atom_catalog
from smeme.reasoning.cevi.corpus_normalize import (
    ResearchCorpusSnapshot,
    build_research_corpus_snapshot,
)
from smeme.reasoning.cevi.deterministic_induction import (
    build_deterministic_corpus_partial_contract,
)
from smeme.reasoning.published_evidence_contract import PublishedEvidenceContractV1


def induce_published_evidence_contract_at_publish(
    *,
    ir_json: dict[str, Any],
    graph: DTGraph,
    graph_hash: str,
    ir_format_version: int,
    corpus_body: str | None,
    legal_at_publish: bool,
) -> tuple[PublishedEvidenceContractV1, ResearchCorpusSnapshot]:
    """Return ``(contract, corpus_snapshot)`` for this compile.

    Emits **deterministic** ``corpus_partial``: glosses from question/conclusion copy, identity
    option paraphrases, and (when corpus bytes exist) a chunk manifest + gloss chunk citations keyed
    by ``node:{id}``. Corpus bytes freeze into ``research_corpus_hash`` + provenance.
    ``legal_at_publish`` is recorded in provenance only.

    ``ir_json`` must match ``graph`` (same compile as publish readiness); atom-catalog validation
    ensures induction targets stay on the IR carrier set.
    """
    _ = canonical_ir_atom_catalog(ir_json)
    corpus_snapshot = build_research_corpus_snapshot(corpus_body)
    contract = build_deterministic_corpus_partial_contract(
        graph=graph,
        corpus_snapshot=corpus_snapshot,
        graph_hash=graph_hash,
        ir_format_version=ir_format_version,
        legal_at_publish=legal_at_publish,
    )
    return contract, corpus_snapshot
