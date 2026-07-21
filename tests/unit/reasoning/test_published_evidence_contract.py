"""PublishedEvidenceContract v1 + IR-only induction stub."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smeme.reasoning.cevi.atom_catalog import canonical_ir_atom_catalog
from smeme.reasoning.evidence_contract import hash_contract, sha256_hex
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.published_evidence_contract import (
    AtomGlossEntryV1,
    BridgeRuleBodyV1,
    CEVI_MAX_BRIDGE_RULES_TOTAL,
    CorpusChunkManifestEntryV1,
    DefaultsPolicyV1,
    OptionParaphraseSetV1,
    PublishedEvidenceContractV1,
    PublishedEvidenceProvenanceV1,
    cevi_fingerprint,
    contract_to_stored_json,
    induce_published_evidence_contract_ir_only,
    validated_contract_with_ir_json,
)


def test_induce_ir_only_minimal_v1_shape() -> None:
    c = induce_published_evidence_contract_ir_only(
        graph_hash="g" * 64,
        ir_format_version=3,
    )
    d = contract_to_stored_json(c)
    assert d["version"] == 1
    assert d["kind"] == "ir_only"
    assert d["atom_glosses"] == {}
    assert d["option_paraphrases"] == {}
    assert d["defaults"] == {"world_assumption": "closed_world"}
    assert d["confidence_policy"] == "default"
    assert d["warnings"] == []
    assert d["bridge_rules"] == {}
    assert d["lexical_signatures"] == {}
    assert d["normalization_rules"] == {}
    assert d["ontology_snapshots"] == []
    assert d["corpus_chunk_manifest"] == []
    assert d["provenance"]["research_corpus_hash"] is None
    assert d["provenance"]["graph_hash"] == "g" * 64
    assert d["provenance"]["ir_format_version"] == 3
    assert d["provenance"]["legal"] is False


def test_cevi_fingerprint_matches_hash_contract() -> None:
    c = induce_published_evidence_contract_ir_only(
        graph_hash="a" * 64,
        ir_format_version=1,
    )
    assert cevi_fingerprint(c) == hash_contract(contract_to_stored_json(c))


def test_model_roundtrip() -> None:
    c1 = induce_published_evidence_contract_ir_only(
        graph_hash="b" * 64,
        ir_format_version=2,
    )
    c2 = PublishedEvidenceContractV1.model_validate(contract_to_stored_json(c1))
    assert cevi_fingerprint(c1) == cevi_fingerprint(c2)


def _minimal_ir_json() -> dict:
    return {
        "format_version": IR_FORMAT_VERSION,
        "nodes": [
            {"id": "q1", "kind": "question", "question": {"qtype": "radio", "options": ["A"]}},
            {"id": "c1", "kind": "conclusion", "question": None},
        ],
        "edges": [{"source": "q1", "target": "c1", "guard_id": "g0"}],
        "guards": [{"id": "g0", "expr": "A"}],
    }


def test_manifest_rejects_unknown_gloss_chunk_id() -> None:
    gh, irv = "c" * 64, 2
    corpus_hex = "f" * 64
    chunk_bytes = b"x"
    manifest_id = f"cc1-{corpus_hex}-0000"
    with pytest.raises(ValidationError, match="unknown corpus_chunk_id"):
        PublishedEvidenceContractV1(
            kind="corpus_partial",
            corpus_chunk_manifest=(
                CorpusChunkManifestEntryV1(
                    chunk_id=manifest_id,
                    utf8_byte_start=0,
                    utf8_byte_end=len(chunk_bytes),
                    content_sha256_hex=sha256_hex(chunk_bytes),
                ),
            ),
            atom_glosses={
                "node:q1": AtomGlossEntryV1(
                    text="x",
                    corpus_chunk_ids=("bogus_chunk",),
                ),
            },
            provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
        )


def test_catalog_validation_passes_when_atoms_match_ir() -> None:
    ir = _minimal_ir_json()
    catalog = canonical_ir_atom_catalog(ir)
    gh, irv = "c" * 64, 2
    c = PublishedEvidenceContractV1(
        kind="corpus_partial",
        atom_glosses={
            "node:q1": AtomGlossEntryV1(text="Ask about eligibility."),
        },
        provenance=PublishedEvidenceProvenanceV1(
            graph_hash=gh,
            ir_format_version=irv,
        ),
    )
    d = contract_to_stored_json(c)
    r2 = validated_contract_with_ir_json(d, ir_json=ir)
    assert r2.atom_glosses["node:q1"].text == "Ask about eligibility."
    assert catalog == canonical_ir_atom_catalog(ir)


def test_catalog_validation_rejects_unknown_atom_gloss_key() -> None:
    ir = _minimal_ir_json()
    gh, irv = "c" * 64, 2
    c = PublishedEvidenceContractV1(
        kind="corpus_partial",
        atom_glosses={"node:nope": AtomGlossEntryV1(text="x")},
        provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
    )
    d = contract_to_stored_json(c)
    with pytest.raises(Exception, match="unknown IR atom"):
        validated_contract_with_ir_json(d, ir_json=ir)


def test_catalog_validation_bridge_targets() -> None:
    ir = _minimal_ir_json()
    gh, irv = "c" * 64, 2
    good = PublishedEvidenceContractV1(
        kind="corpus_partial",
        bridge_rules={
            "br1": BridgeRuleBodyV1(
                kind="regex_span",
                pattern=r"\byes\b",
                target_atoms=("node:c1",),
            ),
        },
        provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
    )
    validated_contract_with_ir_json(contract_to_stored_json(good), ir_json=ir)

    bad = PublishedEvidenceContractV1(
        kind="corpus_partial",
        bridge_rules={
            "br1": BridgeRuleBodyV1(
                kind="regex_span",
                pattern=r"x",
                target_atoms=("node:ghost",),
            ),
        },
        provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
    )
    with pytest.raises(Exception, match="unknown IR atom"):
        validated_contract_with_ir_json(contract_to_stored_json(bad), ir_json=ir)


def test_kind_corpus_induced_distinct_fingerprint() -> None:
    """``kind`` is part of canonical JSON — not inferred from empty hint maps."""
    gh, irv = "c" * 64, 2
    ir_only = induce_published_evidence_contract_ir_only(graph_hash=gh, ir_format_version=irv)
    corpus = PublishedEvidenceContractV1(
        kind="corpus_induced",
        provenance=PublishedEvidenceProvenanceV1(
            research_corpus_hash="d" * 64,
            graph_hash=gh,
            ir_format_version=irv,
            legal=False,
        ),
    )
    assert contract_to_stored_json(ir_only)["kind"] == "ir_only"
    assert contract_to_stored_json(corpus)["kind"] == "corpus_induced"
    assert cevi_fingerprint(ir_only) != cevi_fingerprint(corpus)


def test_defaults_policy_roundtrip_without_context() -> None:
    c = induce_published_evidence_contract_ir_only(graph_hash="e" * 64, ir_format_version=1)
    d = contract_to_stored_json(c)
    again = PublishedEvidenceContractV1.model_validate(d)
    assert isinstance(again.defaults, DefaultsPolicyV1)
    assert again.defaults.world_assumption == "closed_world"


def test_option_paraphrases_aligned_with_ir_options() -> None:
    ir = _minimal_ir_json()
    gh, irv = "c" * 64, 2
    c = PublishedEvidenceContractV1(
        kind="corpus_partial",
        option_paraphrases={
            "node:q1": OptionParaphraseSetV1(by_option={"A": ("alpha",)}),
        },
        provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
    )
    d = contract_to_stored_json(c)
    r2 = validated_contract_with_ir_json(d, ir_json=ir)
    assert r2.option_paraphrases["node:q1"].by_option["A"] == ("alpha",)


def test_option_paraphrases_unknown_option_label_rejected() -> None:
    ir = _minimal_ir_json()
    gh, irv = "c" * 64, 2
    c = PublishedEvidenceContractV1(
        kind="corpus_partial",
        option_paraphrases={
            "node:q1": OptionParaphraseSetV1(by_option={"not_an_option": ("x",)}),
        },
        provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
    )
    d = contract_to_stored_json(c)
    with pytest.raises(Exception, match="unknown option label"):
        validated_contract_with_ir_json(d, ir_json=ir)


def test_bridge_rules_aggregate_cap() -> None:
    gh, irv = "c" * 64, 2
    bridge_rules = {
        f"b{i}": BridgeRuleBodyV1(
            kind="regex_span",
            pattern="x",
            target_atoms=("node:q1",),
        )
        for i in range(CEVI_MAX_BRIDGE_RULES_TOTAL + 1)
    }
    with pytest.raises(ValidationError, match="bridge_rules exceeds cap"):
        PublishedEvidenceContractV1(
            kind="corpus_partial",
            bridge_rules=bridge_rules,
            provenance=PublishedEvidenceProvenanceV1(graph_hash=gh, ir_format_version=irv),
        )
