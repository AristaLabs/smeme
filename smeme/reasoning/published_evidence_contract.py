"""``PublishedEvidenceContract`` v1 — CEVI induction output (IR-only default; typed Phase B slices).

**Immutability (default):** A contract persisted on ``ReasoningCompiledArtifact`` is the artifact
for that compile. A **re-publish** replaces the row and hash.

**Catalog validation:** Call :func:`PublishedEvidenceContractV1.model_validate` with
``context={"atom_catalog": frozenset(...), "question_options": {...}}`` (from
:func:`smeme.reasoning.cevi.atom_catalog.canonical_ir_validation_context`) when you need to verify
keys, ``target_atoms``, and option paraphrases. Parsing JSON from storage **without** context skips
those checks (backwards compatible for read paths).
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from smeme.reasoning.cevi.atom_catalog import canonical_ir_validation_context
from smeme.reasoning.evidence_contract import hash_contract

__all__ = [
    "PUBLISHED_EVIDENCE_CONTRACT_VERSION",
    "CEVI_MAX_ATOM_GLOSSES_ENTRIES",
    "CEVI_MAX_BRIDGE_RULES_TOTAL",
    "CEVI_MAX_CORPUS_CHUNK_IDS_PER_ROW",
    "CEVI_MAX_CORPUS_MANIFEST_ENTRIES",
    "CEVI_MAX_LEXICAL_SIGNATURE_ENTRIES",
    "CEVI_MAX_NORMALIZATION_RULES",
    "CEVI_MAX_ONTOLOGY_SNAPSHOTS",
    "CEVI_MAX_OPTION_PARAPHRASE_QUESTIONS",
    "CEVI_MAX_PARAPHRASES_PER_OPTION",
    "CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE",
    "CEVI_MAX_REGEX_PATTERN_LENGTH",
    "CEVI_MAX_WARNINGS",
    "AtomGlossEntryV1",
    "BridgeRuleBodyV1",
    "BridgeRuleKind",
    "CorpusChunkManifestEntryV1",
    "DefaultsPolicyV1",
    "LexicalSignatureV1",
    "NormalizationRuleV1",
    "OptionParaphraseSetV1",
    "PublishedEvidenceContractKind",
    "PublishedEvidenceContractV1",
    "PublishedEvidenceProvenanceV1",
    "WorldAssumption",
    "cevi_fingerprint",
    "contract_to_stored_json",
    "induce_published_evidence_contract_ir_only",
    "validated_contract_with_ir_json",
]

PUBLISHED_EVIDENCE_CONTRACT_VERSION: Literal[1] = 1

# Structural caps (bounded induction + artifact safety)
CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE: int = 128
CEVI_MAX_BRIDGE_RULES_TOTAL: int = 256
CEVI_MAX_REGEX_PATTERN_LENGTH: int = 4096
CEVI_MAX_CORPUS_CHUNK_IDS_PER_ROW: int = 64
CEVI_MAX_ATOM_GLOSSES_ENTRIES: int = 512
CEVI_MAX_LEXICAL_SIGNATURE_ENTRIES: int = 512
CEVI_MAX_OPTION_PARAPHRASE_QUESTIONS: int = 128
CEVI_MAX_PARAPHRASES_PER_OPTION: int = 64
CEVI_MAX_NORMALIZATION_RULES: int = 128
CEVI_MAX_ONTOLOGY_SNAPSHOTS: int = 32
CEVI_MAX_WARNINGS: int = 128
CEVI_MAX_GLOSS_TEXT_LENGTH: int = 8000
CEVI_MAX_CONFIDENCE_POLICY_LENGTH: int = 256
CEVI_MAX_WARNING_LINE_LENGTH: int = 4000
CEVI_MAX_CORPUS_MANIFEST_ENTRIES: int = 512

PublishedEvidenceContractKind = Literal["ir_only", "corpus_partial", "corpus_induced"]

BridgeRuleKind = Literal["regex_span", "normalized_token_regex"]

WorldAssumption = Literal["closed_world", "permissive"]


class PublishedEvidenceProvenanceV1(BaseModel):
    """Provenance for v1 — corpus hash is digest of bytes fed to induction for this artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    research_corpus_hash: str | None = None
    graph_hash: str | None = Field(
        default=None,
        description="Authoritative graph hash at publish (same as artifact.graph_hash).",
    )
    ir_format_version: int | None = Field(
        default=None,
        description="IR format at publish (same as artifact.ir_format_version).",
    )
    legal: bool = Field(
        default=False,
        description="DecisionTree cevi_legal flag at publish (ontology validation intent when induction supports it).",
    )


class DefaultsPolicyV1(BaseModel):
    """Minimal frozen defaults / runtime interpretation intent (no open-ended knob bag)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_assumption: WorldAssumption = "closed_world"


class CorpusChunkManifestEntryV1(BaseModel):
    """One stable slice of normalized corpus UTF-8 bytes (audit without embedding full text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(..., min_length=1, max_length=220)
    utf8_byte_start: int = Field(
        ge=0, description="Inclusive byte offset into normalized corpus UTF-8."
    )
    utf8_byte_end: int = Field(
        ge=0, description="Exclusive byte offset into normalized corpus UTF-8."
    )
    content_sha256_hex: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hex of the UTF-8 bytes in [utf8_byte_start, utf8_byte_end).",
    )

    @model_validator(mode="after")
    def _byte_range_nonempty(self) -> Self:
        if self.utf8_byte_end <= self.utf8_byte_start:
            detail = "utf8_byte_end must be greater than utf8_byte_start"
            raise ValueError(detail)
        return self


class AtomGlossEntryV1(BaseModel):
    """Natural-language gloss keyed to one canonical IR atom id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(..., min_length=1, max_length=CEVI_MAX_GLOSS_TEXT_LENGTH)
    corpus_chunk_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=CEVI_MAX_CORPUS_CHUNK_IDS_PER_ROW,
    )


class LexicalSignatureV1(BaseModel):
    """Retrieval / indexing hints for one atom — never truth-bearing bridge assertions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phrases: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE,
    )
    corpus_chunk_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=CEVI_MAX_CORPUS_CHUNK_IDS_PER_ROW,
    )


class NormalizationRuleV1(BaseModel):
    """Auditable text normalization policy slice (optional regex pair + optional atom scope)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = ""
    pattern: str | None = Field(default=None, max_length=CEVI_MAX_REGEX_PATTERN_LENGTH)
    replacement: str | None = Field(default=None, max_length=CEVI_MAX_REGEX_PATTERN_LENGTH)
    applies_to_atoms: tuple[str, ...] | None = None


class BridgeRuleBodyV1(BaseModel):
    """Truth-facing bridge from structured surface pattern to existing catalog atoms."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: BridgeRuleKind
    pattern: str = Field(..., min_length=1, max_length=CEVI_MAX_REGEX_PATTERN_LENGTH)
    target_atoms: tuple[str, ...] = Field(
        ...,
        min_length=1,
        description="Must reference canonical IR atom ids when validated with atom_catalog context.",
    )


class OptionParaphraseSetV1(BaseModel):
    """Per-question runtime hints: IR option label → synonymous surface phrases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    by_option: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("by_option", mode="after")
    @classmethod
    def _bounds(cls, v: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        for label, phrases in v.items():
            if not label:
                detail = "option paraphrase option label must be non-empty"
                raise ValueError(detail)
            if len(phrases) > CEVI_MAX_PARAPHRASES_PER_OPTION:
                detail = (
                    f"at most {CEVI_MAX_PARAPHRASES_PER_OPTION} paraphrases per option "
                    f"(got {len(phrases)} for option {label!r})"
                )
                raise ValueError(detail)
            for p in phrases:
                if not p or not p.strip():
                    detail = f"empty paraphrase string under option {label!r}"
                    raise ValueError(detail)
        return v


class PublishedEvidenceContractV1(BaseModel):
    """v1 contract: IR-only default; optional corpus-backed slices use honest ``kind``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    kind: PublishedEvidenceContractKind = "ir_only"
    atom_glosses: dict[str, AtomGlossEntryV1] = Field(default_factory=dict)
    option_paraphrases: dict[str, OptionParaphraseSetV1] = Field(default_factory=dict)
    defaults: DefaultsPolicyV1 = Field(default_factory=DefaultsPolicyV1)
    confidence_policy: str = Field(default="default", max_length=CEVI_MAX_CONFIDENCE_POLICY_LENGTH)
    warnings: list[str] = Field(default_factory=list, max_length=CEVI_MAX_WARNINGS)
    bridge_rules: dict[str, BridgeRuleBodyV1] = Field(default_factory=dict)
    lexical_signatures: dict[str, LexicalSignatureV1] = Field(default_factory=dict)
    normalization_rules: dict[str, NormalizationRuleV1] = Field(default_factory=dict)
    ontology_snapshots: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=CEVI_MAX_ONTOLOGY_SNAPSHOTS,
    )
    corpus_chunk_manifest: tuple[CorpusChunkManifestEntryV1, ...] = Field(default_factory=tuple)
    provenance: PublishedEvidenceProvenanceV1

    @staticmethod
    def _catalog(info: ValidationInfo) -> frozenset[str] | None:
        ctx = info.context
        if ctx is None:
            return None
        cat = ctx.get("atom_catalog")
        if cat is None:
            return None
        return frozenset(cat)

    @staticmethod
    def _question_options(info: ValidationInfo) -> dict[str, frozenset[str]] | None:
        ctx = info.context
        if ctx is None:
            return None
        qo = ctx.get("question_options")
        if qo is None:
            return None
        return qo

    @field_validator("warnings", mode="after")
    @classmethod
    def _warning_line_length(cls, v: list[str]) -> list[str]:
        for i, line in enumerate(v):
            if len(line) > CEVI_MAX_WARNING_LINE_LENGTH:
                detail = f"warnings[{i}] exceeds max length {CEVI_MAX_WARNING_LINE_LENGTH}"
                raise ValueError(detail)
        return v

    @field_validator("atom_glosses", mode="after")
    @classmethod
    def _atom_gloss_catalog_keys(
        cls, v: dict[str, AtomGlossEntryV1], info: ValidationInfo
    ) -> dict[str, AtomGlossEntryV1]:
        catalog = PublishedEvidenceContractV1._catalog(info)
        if catalog is None:
            return v
        for k in v:
            if k not in catalog:
                detail = f"atom_glosses references unknown IR atom id: {k!r}"
                raise ValueError(detail)
        return v

    @field_validator("lexical_signatures", mode="after")
    @classmethod
    def _lexical_catalog_keys(
        cls, v: dict[str, LexicalSignatureV1], info: ValidationInfo
    ) -> dict[str, LexicalSignatureV1]:
        catalog = PublishedEvidenceContractV1._catalog(info)
        if catalog is None:
            return v
        for k in v:
            if k not in catalog:
                detail = f"lexical_signatures references unknown IR atom id: {k!r}"
                raise ValueError(detail)
        return v

    @field_validator("bridge_rules", mode="after")
    @classmethod
    def _bridge_target_atoms(
        cls, v: dict[str, BridgeRuleBodyV1], info: ValidationInfo
    ) -> dict[str, BridgeRuleBodyV1]:
        catalog = PublishedEvidenceContractV1._catalog(info)
        if catalog is None:
            return v
        for rid, body in v.items():
            for atom in body.target_atoms:
                if atom not in catalog:
                    detail = f"bridge_rules[{rid!r}] targets unknown IR atom id: {atom!r}"
                    raise ValueError(detail)
        return v

    @field_validator("normalization_rules", mode="after")
    @classmethod
    def _norm_applies_to_atoms(
        cls, v: dict[str, NormalizationRuleV1], info: ValidationInfo
    ) -> dict[str, NormalizationRuleV1]:
        catalog = PublishedEvidenceContractV1._catalog(info)
        if catalog is None:
            return v
        for rid, rule in v.items():
            if rule.applies_to_atoms is None:
                continue
            for atom in rule.applies_to_atoms:
                if atom not in catalog:
                    detail = f"normalization_rules[{rid!r}] applies_to_atoms unknown IR atom id: {atom!r}"
                    raise ValueError(detail)
        return v

    @field_validator("option_paraphrases", mode="after")
    @classmethod
    def _option_paraphrases_vs_ir(
        cls, v: dict[str, OptionParaphraseSetV1], info: ValidationInfo
    ) -> dict[str, OptionParaphraseSetV1]:
        catalog = PublishedEvidenceContractV1._catalog(info)
        if catalog is not None:
            for k in v:
                if k not in catalog:
                    detail = f"option_paraphrases references unknown IR atom id: {k!r}"
                    raise ValueError(detail)
        qmap = PublishedEvidenceContractV1._question_options(info)
        if qmap is None:
            return v
        for node_key, oset in v.items():
            allowed = qmap.get(node_key)
            if allowed is None:
                detail = (
                    f"option_paraphrases key {node_key!r} is not a question node "
                    "with option metadata in IR"
                )
                raise ValueError(detail)
            for opt_label in oset.by_option:
                if opt_label not in allowed:
                    detail = (
                        f"option_paraphrases[{node_key!r}] unknown option label "
                        f"{opt_label!r} for this question"
                    )
                    raise ValueError(detail)
        return v

    @model_validator(mode="after")
    def _aggregate_caps(self) -> PublishedEvidenceContractV1:
        if len(self.atom_glosses) > CEVI_MAX_ATOM_GLOSSES_ENTRIES:
            msg = f"atom_glosses exceeds cap {CEVI_MAX_ATOM_GLOSSES_ENTRIES}"
            raise ValueError(msg)
        if len(self.lexical_signatures) > CEVI_MAX_LEXICAL_SIGNATURE_ENTRIES:
            msg = f"lexical_signatures exceeds cap {CEVI_MAX_LEXICAL_SIGNATURE_ENTRIES}"
            raise ValueError(msg)
        if len(self.bridge_rules) > CEVI_MAX_BRIDGE_RULES_TOTAL:
            msg = f"bridge_rules exceeds cap {CEVI_MAX_BRIDGE_RULES_TOTAL}"
            raise ValueError(msg)
        if len(self.normalization_rules) > CEVI_MAX_NORMALIZATION_RULES:
            msg = f"normalization_rules exceeds cap {CEVI_MAX_NORMALIZATION_RULES}"
            raise ValueError(msg)
        if len(self.option_paraphrases) > CEVI_MAX_OPTION_PARAPHRASE_QUESTIONS:
            msg = f"option_paraphrases exceeds cap {CEVI_MAX_OPTION_PARAPHRASE_QUESTIONS}"
            raise ValueError(msg)
        if len(self.corpus_chunk_manifest) > CEVI_MAX_CORPUS_MANIFEST_ENTRIES:
            msg = f"corpus_chunk_manifest exceeds cap {CEVI_MAX_CORPUS_MANIFEST_ENTRIES}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _corpus_chunk_manifest_vs_refs(self) -> PublishedEvidenceContractV1:
        mids = [m.chunk_id for m in self.corpus_chunk_manifest]
        if len(mids) != len(set(mids)):
            detail = "duplicate chunk_id in corpus_chunk_manifest"
            raise ValueError(detail)
        allowed = frozenset(mids)
        if not allowed:
            for aid, gloss in self.atom_glosses.items():
                if gloss.corpus_chunk_ids:
                    detail = f"atom_glosses[{aid!r}] sets corpus_chunk_ids but corpus_chunk_manifest is empty"
                    raise ValueError(detail)
            for lid, lex in self.lexical_signatures.items():
                if lex.corpus_chunk_ids:
                    detail = f"lexical_signatures[{lid!r}] sets corpus_chunk_ids but corpus_chunk_manifest is empty"
                    raise ValueError(detail)
            return self
        for aid, gloss in self.atom_glosses.items():
            for cid in gloss.corpus_chunk_ids:
                if cid not in allowed:
                    detail = f"atom_glosses[{aid!r}] unknown corpus_chunk_id: {cid!r}"
                    raise ValueError(detail)
        for lid, lex in self.lexical_signatures.items():
            for cid in lex.corpus_chunk_ids:
                if cid not in allowed:
                    detail = f"lexical_signatures[{lid!r}] unknown corpus_chunk_id: {cid!r}"
                    raise ValueError(detail)
        return self


def induce_published_evidence_contract_ir_only(
    *,
    graph_hash: str,
    ir_format_version: int,
    research_corpus_hash: str | None = None,
    legal_at_publish: bool = False,
) -> PublishedEvidenceContractV1:
    """CEVI induction default: ``kind=ir_only`` until corpus-backed enrichment is implemented."""
    return PublishedEvidenceContractV1(
        kind="ir_only",
        defaults=DefaultsPolicyV1(),
        provenance=PublishedEvidenceProvenanceV1(
            research_corpus_hash=research_corpus_hash,
            graph_hash=graph_hash,
            ir_format_version=ir_format_version,
            legal=legal_at_publish,
        ),
    )


def contract_to_stored_json(contract: PublishedEvidenceContractV1) -> dict[str, Any]:
    """JSONB-safe dict (stable ``None`` / numbers) for ``ReasoningCompiledArtifact.cevi_contract_json``."""
    return contract.model_dump(mode="json")


def cevi_fingerprint(contract: PublishedEvidenceContractV1) -> str:
    """``cevi_contract_hash`` value for this contract (see ``evidence_contract.md`` §4)."""
    return hash_contract(contract_to_stored_json(contract))


def validated_contract_with_ir_json(
    data: dict[str, Any],
    *,
    ir_json: dict[str, Any],
) -> PublishedEvidenceContractV1:
    """Parse stored JSON and enforce atom ids + option labels against ``ir_json``.

    Raises :exc:`smeme.reasoning.cevi.atom_catalog.IrAtomCatalogError` when ``ir_json`` is invalid.
    """
    catalog, question_options = canonical_ir_validation_context(ir_json)
    return PublishedEvidenceContractV1.model_validate(
        data,
        context={"atom_catalog": catalog, "question_options": question_options},
    )
