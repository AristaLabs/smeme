"""Deterministic ``corpus_partial`` contract slices from authored graph copy (no LLM).

What this layer does (and does not)
-----------------------------------
This is the **non-learned** induction path at publish time: it fills ``PublishedEvidenceContractV1``
with honest ``kind="corpus_partial"``—structured hints grounded in **graph copy + optional research
corpus**, without minting decision carriers beyond what IR already fixes.

It produces:

- **Atom glosses** — Question stem and conclusion title/summary rendered into short gloss strings.
- **Identity option paraphrases** — ``by_option[label] = (label,)`` so runtime work can trust IR labels
  until richer synonyms arrive from LLM passes.
- **Lexical signatures** — Cheap retrieval phrases (labels, lowercase duplicates where distinct,
  stems, conclusion snippets). These are **never** bridge rules; they exist so retrieval layers (and
  later LLM drafts) have stable hooks keyed by ``node:{id}``.
- **Corpus chunk citations** — When ``ResearchCorpusSnapshot`` yields a manifest, glosses and lexical
  rows cite **only chunks whose text overlaps** curated needles (:mod:`smeme.reasoning.cevi.corpus_attribution`).
  If nothing matches, ``corpus_chunk_ids`` stay empty and we emit ``corpus_attribution_miss:…`` warnings
  rather than pretending every chunk supports every atom.

Relationship to ``kind``
------------------------
We keep ``kind="corpus_partial"`` here: bridge rules are absent and diagnostics policy has not yet
declared a ``corpus_induced`` outcome. Upgrading ``kind`` belongs with truth-facing extractors +
product policy, not with this deterministic shim.

Warnings (machine-readable codes)
---------------------------------
- ``gloss_truncated:{atom_id}`` — Gloss exceeded ``CEVI_MAX_GLOSS_TEXT_LENGTH`` after NFC strip.
- ``corpus_attribution_miss:{atom_id}`` — Non-empty manifest but no chunk matched authored cues for
  that atom (see attribution module for matching rules).
"""

from __future__ import annotations

from smeme.qnr.models import DTGraph
from smeme.reasoning.cevi.corpus_attribution import (
    attributed_chunk_ids_conclusion,
    attributed_chunk_ids_question,
    lexical_phrases_for_conclusion,
    lexical_phrases_for_question,
    should_warn_attribution_miss_conclusion,
    should_warn_attribution_miss_question,
)
from smeme.reasoning.cevi.corpus_chunks import build_corpus_chunk_manifest
from smeme.reasoning.cevi.corpus_normalize import ResearchCorpusSnapshot
from smeme.reasoning.published_evidence_contract import (
    CEVI_MAX_GLOSS_TEXT_LENGTH,
    AtomGlossEntryV1,
    DefaultsPolicyV1,
    LexicalSignatureV1,
    OptionParaphraseSetV1,
    PublishedEvidenceContractV1,
    PublishedEvidenceProvenanceV1,
)


def _truncate_gloss(raw: str) -> tuple[str, bool]:
    """Trim gloss source text and record whether we cut to satisfy storage caps."""
    t = raw.strip()
    if not t:
        return "", False
    if len(t) <= CEVI_MAX_GLOSS_TEXT_LENGTH:
        return t, False
    return t[:CEVI_MAX_GLOSS_TEXT_LENGTH], True


def _conclusion_gloss_text(graph: DTGraph, node_id: str) -> str:
    """Compose the human-facing gloss string stored on ``node:{id}`` for conclusions."""
    node = graph.get_node(node_id)
    if node is None or not node.is_conclusion():
        return ""
    cd = node.conclusion_data
    if not cd:
        return ""
    title = (cd.title or "").strip()
    summary = (cd.summary or "").strip()
    if title and summary:
        return f"{title}. {summary}"
    return title or summary


def build_deterministic_corpus_partial_contract(
    *,
    graph: DTGraph,
    corpus_snapshot: ResearchCorpusSnapshot,
    graph_hash: str,
    ir_format_version: int,
    legal_at_publish: bool,
) -> PublishedEvidenceContractV1:
    """Emit the deterministic ``corpus_partial`` contract for one compile."""
    manifest = build_corpus_chunk_manifest(corpus_snapshot)
    manifest_nonempty = len(manifest) > 0
    research_corpus_hash = corpus_snapshot.sha256_hex

    atom_glosses: dict[str, AtomGlossEntryV1] = {}
    lexical_signatures: dict[str, LexicalSignatureV1] = {}
    option_paraphrases: dict[str, OptionParaphraseSetV1] = {}
    warnings: list[str] = []

    for nid in sorted(graph.node_ids):
        node = graph.get_node(nid)
        if node is None:
            continue
        atom_id = f"node:{nid}"

        if node.is_question():
            qd = node.question_data
            if not qd:
                continue

            opts_tuple = tuple(qd.options) if qd.options else ()
            stem = (qd.text or "").strip()

            chunk_ids_q = attributed_chunk_ids_question(
                corpus_snapshot,
                manifest,
                question_text=qd.text or "",
                option_labels=opts_tuple,
            )

            if stem:
                text, trunc = _truncate_gloss(stem)
                if text:
                    atom_glosses[atom_id] = AtomGlossEntryV1(
                        text=text,
                        corpus_chunk_ids=chunk_ids_q,
                    )
                    if trunc:
                        warnings.append(f"gloss_truncated:{atom_id}")

            phrases_q = lexical_phrases_for_question(opts_tuple, qd.text or "")
            if phrases_q:
                lexical_signatures[atom_id] = LexicalSignatureV1(
                    phrases=phrases_q,
                    corpus_chunk_ids=chunk_ids_q,
                )

            if opts_tuple:
                option_paraphrases[atom_id] = OptionParaphraseSetV1(
                    by_option={label: (label,) for label in opts_tuple},
                )

            if should_warn_attribution_miss_question(
                manifest_nonempty=manifest_nonempty,
                attributed=chunk_ids_q,
                question_text=qd.text or "",
                option_labels=opts_tuple,
            ):
                warnings.append(f"corpus_attribution_miss:{atom_id}")

        elif node.is_conclusion():
            cd = node.conclusion_data
            if not cd:
                continue

            raw_c = _conclusion_gloss_text(graph, nid)

            chunk_ids_c = attributed_chunk_ids_conclusion(
                corpus_snapshot,
                manifest,
                title=cd.title or "",
                summary=cd.summary or "",
            )

            if raw_c:
                text, trunc = _truncate_gloss(raw_c)
                if text:
                    atom_glosses[atom_id] = AtomGlossEntryV1(
                        text=text,
                        corpus_chunk_ids=chunk_ids_c,
                    )
                    if trunc:
                        warnings.append(f"gloss_truncated:{atom_id}")

            phrases_c = lexical_phrases_for_conclusion(cd.title or "", cd.summary or "")
            if phrases_c:
                lexical_signatures[atom_id] = LexicalSignatureV1(
                    phrases=phrases_c,
                    corpus_chunk_ids=chunk_ids_c,
                )

            if should_warn_attribution_miss_conclusion(
                manifest_nonempty=manifest_nonempty,
                attributed=chunk_ids_c,
                title=cd.title or "",
                summary=cd.summary or "",
            ):
                warnings.append(f"corpus_attribution_miss:{atom_id}")

    return PublishedEvidenceContractV1(
        kind="corpus_partial",
        atom_glosses=atom_glosses,
        option_paraphrases=option_paraphrases,
        lexical_signatures=lexical_signatures,
        defaults=DefaultsPolicyV1(),
        warnings=warnings,
        corpus_chunk_manifest=manifest,
        provenance=PublishedEvidenceProvenanceV1(
            research_corpus_hash=research_corpus_hash,
            graph_hash=graph_hash,
            ir_format_version=ir_format_version,
            legal=legal_at_publish,
        ),
    )
