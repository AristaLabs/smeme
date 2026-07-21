"""Deterministic completeness and inspection helpers for ``PublishedEvidenceContractV1``.

Used for logging, tests, and manual review of publish-time CEVI output. Does **not** call the LLM or
mutate contracts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from smeme.reasoning.published_evidence_contract import (
    PublishedEvidenceContractKind,
    PublishedEvidenceContractV1,
)

# Stable machine-readable codes for logs and dashboards (do not rename casually).
REASON_KIND_IR_ONLY: Literal["kind_is_ir_only"] = "kind_is_ir_only"
REASON_KIND_CORPUS_PARTIAL: Literal["kind_declared_corpus_partial"] = "kind_declared_corpus_partial"
REASON_NO_BRIDGE_RULES: Literal["no_truth_facing_bridge_rules"] = "no_truth_facing_bridge_rules"
REASON_DECLARED_INDUCED_BUT_POLICY_UNMET: Literal["declared_corpus_induced_but_policy_unmet"] = (
    "declared_corpus_induced_but_policy_unmet"
)

CeviNotInducedReason = Literal[
    "kind_is_ir_only",
    "kind_declared_corpus_partial",
    "no_truth_facing_bridge_rules",
    "declared_corpus_induced_but_policy_unmet",
]


class CeviSliceCountsV1(BaseModel):
    """Non-secret structural counts for inspection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    atom_glosses: int = Field(ge=0)
    option_paraphrase_questions: int = Field(ge=0)
    bridge_rules: int = Field(ge=0)
    lexical_signatures: int = Field(ge=0)
    normalization_rules: int = Field(ge=0)
    ontology_snapshots: int = Field(ge=0)
    corpus_chunk_manifest_entries: int = Field(ge=0)
    contract_warnings: int = Field(ge=0)


class CeviContractDiagnosticsV1(BaseModel):
    """What is present, what is empty, and whether the contract meets the **corpus_induced** policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stored_kind: PublishedEvidenceContractKind
    slice_counts: CeviSliceCountsV1
    empty_slices: tuple[str, ...] = Field(
        description="Structural slice names that are empty (maps/lists with len 0).",
    )
    reasons_not_corpus_induced: tuple[CeviNotInducedReason, ...] = Field(
        description="Why ``meets_corpus_induced_policy`` is false; empty when policy is satisfied.",
    )
    meets_corpus_induced_policy: bool = Field(
        description=(
            "True when stored kind is ``corpus_induced`` and required slices satisfy "
            "the configured policy (see ``diagnose_published_evidence_contract``)."
        ),
    )
    diagnostic_notes: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Non-blocking hints (e.g. published warnings copied from the contract).",
    )


def _empty_slice_names(contract: PublishedEvidenceContractV1) -> tuple[str, ...]:
    names: list[str] = []
    if not contract.atom_glosses:
        names.append("atom_glosses")
    if not contract.option_paraphrases:
        names.append("option_paraphrases")
    if not contract.bridge_rules:
        names.append("bridge_rules")
    if not contract.lexical_signatures:
        names.append("lexical_signatures")
    if not contract.normalization_rules:
        names.append("normalization_rules")
    if not contract.ontology_snapshots:
        names.append("ontology_snapshots")
    if not contract.corpus_chunk_manifest:
        names.append("corpus_chunk_manifest")
    return tuple(names)


def _slice_counts(contract: PublishedEvidenceContractV1) -> CeviSliceCountsV1:
    return CeviSliceCountsV1(
        atom_glosses=len(contract.atom_glosses),
        option_paraphrase_questions=len(contract.option_paraphrases),
        bridge_rules=len(contract.bridge_rules),
        lexical_signatures=len(contract.lexical_signatures),
        normalization_rules=len(contract.normalization_rules),
        ontology_snapshots=len(contract.ontology_snapshots),
        corpus_chunk_manifest_entries=len(contract.corpus_chunk_manifest),
        contract_warnings=len(contract.warnings),
    )


def diagnose_published_evidence_contract(
    contract: PublishedEvidenceContractV1,
    *,
    corpus_induced_requires_bridge_rules: bool = True,
) -> CeviContractDiagnosticsV1:
    """Inspect a typed contract: counts, empty slices, and **corpus_induced** policy alignment.

    **Policy (v1):** ``corpus_induced`` is only considered fully satisfied when
    ``stored_kind`` is ``corpus_induced`` and, if ``corpus_induced_requires_bridge_rules`` is true,
    at least one bridge rule exists (truth-facing extractors per product/docs).

    When ``stored_kind`` is ``corpus_induced`` but policy checks fail, we emit
    ``declared_corpus_induced_but_policy_unmet`` plus ``no_truth_facing_bridge_rules`` when bridges
    are missing.
    """
    counts = _slice_counts(contract)
    empty = _empty_slice_names(contract)
    notes: list[str] = []
    if contract.warnings:
        notes.append("contract_has_warnings")

    bridges_ok = len(contract.bridge_rules) > 0
    meets = contract.kind == "corpus_induced" and (
        not corpus_induced_requires_bridge_rules or bridges_ok
    )

    reasons: list[CeviNotInducedReason] = []
    if not meets:
        if contract.kind == "ir_only":
            reasons.append(REASON_KIND_IR_ONLY)
        elif contract.kind == "corpus_partial":
            reasons.append(REASON_KIND_CORPUS_PARTIAL)
        elif contract.kind == "corpus_induced":
            if corpus_induced_requires_bridge_rules and not bridges_ok:
                reasons.append(REASON_NO_BRIDGE_RULES)
                reasons.append(REASON_DECLARED_INDUCED_BUT_POLICY_UNMET)

    return CeviContractDiagnosticsV1(
        stored_kind=contract.kind,
        slice_counts=counts,
        empty_slices=empty,
        reasons_not_corpus_induced=tuple(reasons),
        meets_corpus_induced_policy=meets,
        diagnostic_notes=tuple(notes),
    )


def diagnostics_log_payload(diag: CeviContractDiagnosticsV1) -> dict[str, object]:
    """Flatten diagnostics into JSON-log-friendly primitives (no sets)."""
    return {
        "stored_kind": diag.stored_kind,
        "meets_corpus_induced_policy": diag.meets_corpus_induced_policy,
        "slice_counts": diag.slice_counts.model_dump(mode="json"),
        "empty_slices": list(diag.empty_slices),
        "reasons_not_corpus_induced": list(diag.reasons_not_corpus_induced),
        "diagnostic_notes": list(diag.diagnostic_notes),
    }
