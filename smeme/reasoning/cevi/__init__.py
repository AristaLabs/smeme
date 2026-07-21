"""CEVI publish-time helpers (corpus normalize, IR atom catalog, deterministic induction)."""

from smeme.reasoning.cevi.atom_catalog import IrAtomCatalogError, canonical_ir_atom_catalog
from smeme.reasoning.cevi.contract_diagnostics import (
    CeviContractDiagnosticsV1,
    CeviSliceCountsV1,
    diagnose_published_evidence_contract,
    diagnostics_log_payload,
)
from smeme.reasoning.cevi.corpus_chunks import (
    MAX_CORPUS_CHUNKS,
    all_manifest_chunk_ids,
    build_corpus_chunk_manifest,
)
from smeme.reasoning.cevi.corpus_normalize import (
    MAX_RESEARCH_CORPUS_BYTES,
    ResearchCorpusSnapshot,
    build_research_corpus_snapshot,
    normalize_corpus_text,
    normalized_corpus_sha256_or_none,
    truncate_corpus_to_max_bytes,
)
from smeme.reasoning.cevi.deterministic_induction import build_deterministic_corpus_partial_contract
from smeme.reasoning.cevi.generation_corpus import build_research_corpus_text_from_generation_state
from smeme.reasoning.cevi.induction import induce_published_evidence_contract_at_publish

__all__ = [
    "CeviContractDiagnosticsV1",
    "CeviSliceCountsV1",
    "IrAtomCatalogError",
    "MAX_CORPUS_CHUNKS",
    "MAX_RESEARCH_CORPUS_BYTES",
    "ResearchCorpusSnapshot",
    "all_manifest_chunk_ids",
    "build_deterministic_corpus_partial_contract",
    "build_corpus_chunk_manifest",
    "build_research_corpus_snapshot",
    "build_research_corpus_text_from_generation_state",
    "canonical_ir_atom_catalog",
    "diagnose_published_evidence_contract",
    "diagnostics_log_payload",
    "induce_published_evidence_contract_at_publish",
    "normalize_corpus_text",
    "normalized_corpus_sha256_or_none",
    "truncate_corpus_to_max_bytes",
]
