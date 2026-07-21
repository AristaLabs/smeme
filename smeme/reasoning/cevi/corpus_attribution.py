"""Deterministic **narrow** corpus_chunk attribution for CEVI (no LLM).

Why this module exists
----------------------
``ResearchCorpusSnapshot`` is chunked into a **manifest** with stable ``chunk_id`` values and UTF-8
byte ranges (:mod:`smeme.reasoning.cevi.corpus_chunks`). Rows in ``PublishedEvidenceContractV1`` may
cite those ids on:

- ``AtomGlossEntryV1.corpus_chunk_ids``
- ``LexicalSignatureV1.corpus_chunk_ids``

Earlier scaffolding cited **every** chunk on **every** gloss whenever any corpus was present. That
validated the manifest and hashing pipeline end-to-end, but it only proved **corpus availability**
for the artifact—not that any particular chunk bears on any particular atom.

This module narrows citations **deterministically**:

1. **IR option labels (radio)** — Each label is normalized (NFC, lowercased, whitespace
   collapsed). If that string appears as a **substring** of a chunk’s normalized text, the chunk is
   eligible. Short labels like ``"A"`` are included intentionally (authors rely on them); substring
   matching can occasionally collide with unrelated prose—acceptable noise until LLM refinement.

2. **Question stem tokens** — Word-like tokens (length ≥ ``MIN_TOKEN_CHARS``) from the authored
   question text are matched the same way (substring after normalization). Very short English words
   are filtered by ``MIN_TOKEN_CHARS`` to reduce accidental hits.

3. **Conclusion title / summary** — Normalized title and summary strings are matched when their
   normalized length is **≥ 2**; additionally, tokens from the combined title+summary are matched
   with the same ≥2 rule. Single-character titles are intentionally weak—prefer multi-word outcomes in
   authoring when corpus linkage matters.

4. **Ordering** — Eligible chunk ids are emitted in **manifest order** so JSON and hashes stay
   stable across runs.

5. **Miss handling** — Callers emit ``corpus_attribution_miss:{atom_id}`` when the manifest is
   non-empty but **no** chunk matched any needle. Gloss ``corpus_chunk_ids`` may legitimately stay
   ``()`` while the manifest remains populated (validator allows this): empty means “no grounded span,”
   not “no corpus.”

Chunk text extraction
---------------------
Manifest rows store **UTF-8 byte offsets** into the normalized snapshot string (the same bytes that
were digested into ``research_corpus_hash``). We never index a Python ``str`` with byte offsets; we
slice ``snapshot.text.encode("utf-8")``, then decode for matching.

Lexical phrases (deterministic retrieval hints)
-----------------------------------------------
``LexicalSignatureV1`` is **retrieval / indexing only**—never truth-bearing bridge logic (see
``evidence_contract.md``). Phrases built here are boring surface variants (labels, optional lowercase
copies, stem/title/summary snippets) so downstream LLM passes have structured hooks without minting
carriers beyond IR vocabulary.
"""

from __future__ import annotations

import re
import unicodedata

from smeme.reasoning.cevi.corpus_normalize import ResearchCorpusSnapshot
from smeme.reasoning.published_evidence_contract import (
    CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE,
    CorpusChunkManifestEntryV1,
)

# Tokens shorter than this are skipped when harvesting overlap terms from question/conclusion prose.
# Option labels bypass this gate (handled separately) so short codes like "No" still work.
MIN_TOKEN_CHARS: int = 2

_TOKEN_PATTERN = re.compile(r"[\w\-]+", re.UNICODE)


def normalize_for_match(text: str) -> str:
    """NFC + lowercase + collapsed whitespace—shared shape for substring checks."""
    t = unicodedata.normalize("NFC", text)
    t = " ".join(t.lower().split())
    return t.strip()


def chunk_utf8_text(snapshot: ResearchCorpusSnapshot, row: CorpusChunkManifestEntryV1) -> str:
    """Decode UTF-8 bytes ``[utf8_byte_start, utf8_byte_end)`` from the snapshot (not ``str`` slicing)."""
    raw = snapshot.text.encode("utf-8")
    chunk_bytes = raw[row.utf8_byte_start : row.utf8_byte_end]
    return chunk_bytes.decode("utf-8", errors="replace")


def _tokens_from_normalized(norm: str) -> list[str]:
    """Word-like tokens from already-normalized prose (lower/NFC)."""
    return [t for t in _TOKEN_PATTERN.findall(norm) if len(t) >= MIN_TOKEN_CHARS]


def _chunk_matches_question_text(
    chunk_norm: str,
    *,
    question_text: str,
    option_labels: tuple[str, ...],
) -> bool:
    """Whether normalized chunk text matches any option label or sufficiently long question token."""
    if not chunk_norm:
        return False

    for lab in option_labels:
        nl = normalize_for_match(lab)
        if nl and nl in chunk_norm:
            return True

    qn = normalize_for_match(question_text)
    return any(tok in chunk_norm for tok in _tokens_from_normalized(qn))


def _chunk_matches_conclusion_text(
    chunk_norm: str,
    *,
    title: str,
    summary: str,
) -> bool:
    """Match conclusion blobs (≥2 chars normalized) or longer tokens from title+summary."""
    if not chunk_norm:
        return False

    for blob in (title, summary):
        nb = normalize_for_match(blob)
        if len(nb) >= 2 and nb in chunk_norm:
            return True

    combined = f"{title.strip()} {summary.strip()}".strip()
    cn = normalize_for_match(combined)
    return any(tok in chunk_norm for tok in _tokens_from_normalized(cn))


def attributed_chunk_ids_question(
    snapshot: ResearchCorpusSnapshot,
    manifest: tuple[CorpusChunkManifestEntryV1, ...],
    *,
    question_text: str,
    option_labels: tuple[str, ...],
) -> tuple[str, ...]:
    """Manifest-order chunk ids whose text overlaps authored question cues."""
    if not manifest:
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for row in manifest:
        chunk_norm = normalize_for_match(chunk_utf8_text(snapshot, row))
        if (
            _chunk_matches_question_text(
                chunk_norm,
                question_text=question_text,
                option_labels=option_labels,
            )
            and row.chunk_id not in seen
        ):
            seen.add(row.chunk_id)
            out.append(row.chunk_id)

    return tuple(out)


def attributed_chunk_ids_conclusion(
    snapshot: ResearchCorpusSnapshot,
    manifest: tuple[CorpusChunkManifestEntryV1, ...],
    *,
    title: str,
    summary: str,
) -> tuple[str, ...]:
    """Manifest-order chunk ids overlapping conclusion title/summary cues."""
    if not manifest:
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for row in manifest:
        chunk_norm = normalize_for_match(chunk_utf8_text(snapshot, row))
        if (
            _chunk_matches_conclusion_text(chunk_norm, title=title, summary=summary)
            and row.chunk_id not in seen
        ):
            seen.add(row.chunk_id)
            out.append(row.chunk_id)

    return tuple(out)


def lexical_phrases_for_question(
    option_labels: tuple[str, ...], question_text: str
) -> tuple[str, ...]:
    """Ordered surface phrases for ``LexicalSignatureV1`` on question atoms (retrieval hints only)."""
    phrases: list[str] = []
    seen: set[str] = set()

    def push(p: str) -> None:
        p = p.strip()
        if len(p) < 1 or p in seen:
            return
        seen.add(p)
        phrases.append(p)

    for lab in option_labels:
        push(lab)
        low = lab.strip().lower()
        if low and low != lab.strip():
            push(low)

    q = question_text.strip()
    if q:
        push(q)

    return tuple(phrases[:CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE])


def lexical_phrases_for_conclusion(title: str, summary: str) -> tuple[str, ...]:
    """Ordered surface phrases for conclusion atoms."""
    phrases: list[str] = []
    seen: set[str] = set()

    def push(p: str) -> None:
        p = p.strip()
        if len(p) < 1 or p in seen:
            return
        seen.add(p)
        phrases.append(p)

    push(title)
    push(summary)
    lt = title.strip().lower()
    ls = summary.strip().lower()
    if lt and lt != title.strip():
        push(lt)
    if ls and ls != summary.strip():
        push(ls)

    return tuple(phrases[:CEVI_MAX_PHRASES_PER_LEXICAL_SIGNATURE])


def should_warn_attribution_miss_question(
    *,
    manifest_nonempty: bool,
    attributed: tuple[str, ...],
    question_text: str,
    option_labels: tuple[str, ...],
) -> bool:
    """Return True when we had corpus chunks but could not attach any id to this question atom."""
    if not manifest_nonempty or attributed:
        return False
    # Nothing to hunt for—skip warning (e.g. blank stem and no options).
    return bool(option_labels or question_text.strip())


def should_warn_attribution_miss_conclusion(
    *,
    manifest_nonempty: bool,
    attributed: tuple[str, ...],
    title: str,
    summary: str,
) -> bool:
    """Return True when chunks exist but no conclusion cue matched any chunk."""
    if not manifest_nonempty or attributed:
        return False
    return bool(title.strip() or summary.strip())
