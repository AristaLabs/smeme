"""Deterministic UTF-8 corpus chunking for stable ``corpus_chunk_id`` values.

Chunks are defined over the **normalized** snapshot bytes that feed ``research_corpus_hash``.
IDs embed that hash so artifacts remain self-describing at rest.
"""

from __future__ import annotations

from smeme.reasoning.cevi.corpus_normalize import ResearchCorpusSnapshot
from smeme.reasoning.evidence_contract import sha256_hex
from smeme.reasoning.published_evidence_contract import CorpusChunkManifestEntryV1

# Align with per-row ``corpus_chunk_ids`` caps in ``PublishedEvidenceContractV1``.
MAX_CORPUS_CHUNKS: int = 64

# Hard split when a segment cannot stay under this UTF-8 byte size before merging.
MAX_CHUNK_UTF8_BYTES: int = 64 * 1024


def _utf8_safe_cut(raw: bytes, start: int, end: int) -> tuple[int, int]:
    """Clamp ``[start, end)`` to valid UTF-8 boundaries within ``raw``."""
    if start < 0:
        start = 0
    if end > len(raw):
        end = len(raw)
    if start >= end:
        return start, start
    while start < end and (raw[start] & 0xC0) == 0x80:
        start += 1
    while end > start and (raw[end - 1] & 0xC0) == 0x80:
        end -= 1
    if start >= end:
        return start, start
    return start, end


def _segments_double_newline(raw: bytes) -> list[tuple[int, int]]:
    """Non-overlapping spans covering ``raw``, split on ``b'\\n\\n'`` (paragraph-ish)."""
    if not raw:
        return []
    sep = b"\n\n"
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        j = raw.find(sep, start)
        if j == -1:
            seg = _utf8_safe_cut(raw, start, len(raw))
            if seg[1] > seg[0]:
                spans.append(seg)
            break
        seg = _utf8_safe_cut(raw, start, j)
        if seg[1] > seg[0]:
            spans.append(seg)
        start = j + len(sep)
    if not spans:
        seg = _utf8_safe_cut(raw, 0, len(raw))
        if seg[1] > seg[0]:
            spans.append(seg)
    return spans


def _split_oversized(raw: bytes, intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Split intervals whose UTF-8 span exceeds :data:`MAX_CHUNK_UTF8_BYTES`."""
    out: list[tuple[int, int]] = []
    for s, e in intervals:
        if e - s <= MAX_CHUNK_UTF8_BYTES:
            out.append((s, e))
            continue
        cur = s
        while cur < e:
            hi = min(cur + MAX_CHUNK_UTF8_BYTES, e)
            seg = _utf8_safe_cut(raw, cur, hi)
            if seg[1] > seg[0]:
                out.append(seg)
                cur = seg[1]
            else:
                cur += 1
    return out


def _merge_smallest_adjacent(
    intervals: list[tuple[int, int]], max_chunks: int
) -> list[tuple[int, int]]:
    """Merge adjacent spans until ``len(intervals) <= max_chunks`` (deterministic tie-break)."""
    spans = list(intervals)
    while len(spans) > max_chunks:
        best_i = 0
        best_cost: int | None = None
        for i in range(len(spans) - 1):
            a0, a1 = spans[i]
            b0, b1 = spans[i + 1]
            cost = (a1 - a0) + (b1 - b0)
            if best_cost is None or cost < best_cost or (cost == best_cost and i < best_i):
                best_cost = cost
                best_i = i
        merged = (spans[best_i][0], spans[best_i + 1][1])
        spans = spans[:best_i] + [merged] + spans[best_i + 2 :]
    return spans


def build_corpus_chunk_manifest(
    snapshot: ResearchCorpusSnapshot,
) -> tuple[CorpusChunkManifestEntryV1, ...]:
    """Partition normalized corpus bytes into ≤ :data:`MAX_CORPUS_CHUNKS` chunks with stable ids.

    Returns an empty tuple when there is no hashed corpus (empty text or missing digest).
    """
    if not snapshot.text or snapshot.sha256_hex is None:
        return ()

    raw = snapshot.text.encode("utf-8")
    intervals = _segments_double_newline(raw)
    intervals = _split_oversized(raw, intervals)
    intervals = _merge_smallest_adjacent(intervals, MAX_CORPUS_CHUNKS)

    out: list[CorpusChunkManifestEntryV1] = []
    digest_hex = snapshot.sha256_hex
    for i, (s, e) in enumerate(intervals):
        chunk_b = raw[s:e]
        cid = f"cc1-{digest_hex}-{i:04d}"
        out.append(
            CorpusChunkManifestEntryV1(
                chunk_id=cid,
                utf8_byte_start=s,
                utf8_byte_end=e,
                content_sha256_hex=sha256_hex(chunk_b),
            )
        )
    return tuple(out)


def all_manifest_chunk_ids(manifest: tuple[CorpusChunkManifestEntryV1, ...]) -> tuple[str, ...]:
    """Ordered chunk ids suitable for ``AtomGlossEntryV1.corpus_chunk_ids`` (≤ ``MAX_CORPUS_CHUNKS``)."""
    return tuple(m.chunk_id for m in manifest)
