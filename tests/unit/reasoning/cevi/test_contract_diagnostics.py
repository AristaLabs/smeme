"""CEVI contract completeness diagnostics (deterministic, no LLM)."""

from __future__ import annotations

from smeme.reasoning.cevi.contract_diagnostics import (
    REASON_DECLARED_INDUCED_BUT_POLICY_UNMET,
    REASON_KIND_CORPUS_PARTIAL,
    REASON_KIND_IR_ONLY,
    REASON_NO_BRIDGE_RULES,
    diagnose_published_evidence_contract,
    diagnostics_log_payload,
)
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.published_evidence_contract import (
    BridgeRuleBodyV1,
    PublishedEvidenceContractV1,
    PublishedEvidenceProvenanceV1,
    induce_published_evidence_contract_ir_only,
)


def test_ir_only_diagnostic_kind_and_empty_slices() -> None:
    c = induce_published_evidence_contract_ir_only(
        graph_hash="a" * 64,
        ir_format_version=IR_FORMAT_VERSION,
    )
    d = diagnose_published_evidence_contract(c)
    assert d.stored_kind == "ir_only"
    assert d.meets_corpus_induced_policy is False
    assert d.reasons_not_corpus_induced == (REASON_KIND_IR_ONLY,)
    assert "atom_glosses" in d.empty_slices
    assert "bridge_rules" in d.empty_slices
    assert "corpus_chunk_manifest" in d.empty_slices
    assert d.slice_counts.bridge_rules == 0
    payload = diagnostics_log_payload(d)
    assert payload["meets_corpus_induced_policy"] is False
    assert payload["reasons_not_corpus_induced"] == [REASON_KIND_IR_ONLY]


def test_corpus_partial_not_meets_induced_policy() -> None:
    c = PublishedEvidenceContractV1(
        kind="corpus_partial",
        provenance=PublishedEvidenceProvenanceV1(
            graph_hash="b" * 64,
            ir_format_version=IR_FORMAT_VERSION,
        ),
    )
    d = diagnose_published_evidence_contract(c)
    assert d.meets_corpus_induced_policy is False
    assert d.reasons_not_corpus_induced == (REASON_KIND_CORPUS_PARTIAL,)


def test_corpus_induced_without_bridges_fails_policy() -> None:
    c = PublishedEvidenceContractV1(
        kind="corpus_induced",
        provenance=PublishedEvidenceProvenanceV1(
            graph_hash="c" * 64,
            ir_format_version=IR_FORMAT_VERSION,
        ),
    )
    d = diagnose_published_evidence_contract(c)
    assert d.meets_corpus_induced_policy is False
    assert REASON_NO_BRIDGE_RULES in d.reasons_not_corpus_induced
    assert REASON_DECLARED_INDUCED_BUT_POLICY_UNMET in d.reasons_not_corpus_induced


def test_corpus_induced_with_bridge_meets_default_policy() -> None:
    c = PublishedEvidenceContractV1(
        kind="corpus_induced",
        bridge_rules={
            "r1": BridgeRuleBodyV1(
                kind="regex_span",
                pattern=r"\bx\b",
                target_atoms=("node:q1",),
            ),
        },
        provenance=PublishedEvidenceProvenanceV1(
            graph_hash="d" * 64,
            ir_format_version=IR_FORMAT_VERSION,
        ),
    )
    d = diagnose_published_evidence_contract(c)
    assert d.meets_corpus_induced_policy is True
    assert d.reasons_not_corpus_induced == ()
    assert "bridge_rules" not in d.empty_slices


def test_policy_bridge_optional_via_flag() -> None:
    c = PublishedEvidenceContractV1(
        kind="corpus_induced",
        provenance=PublishedEvidenceProvenanceV1(
            graph_hash="e" * 64,
            ir_format_version=IR_FORMAT_VERSION,
        ),
    )
    d = diagnose_published_evidence_contract(c, corpus_induced_requires_bridge_rules=False)
    assert d.meets_corpus_induced_policy is True
    assert d.reasons_not_corpus_induced == ()
