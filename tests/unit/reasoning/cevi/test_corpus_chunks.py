"""Stable corpus chunk ids + manifest entries."""

from __future__ import annotations

from smeme.reasoning.cevi.corpus_chunks import (
    MAX_CORPUS_CHUNKS,
    build_corpus_chunk_manifest,
)
from smeme.reasoning.cevi.corpus_normalize import ResearchCorpusSnapshot, build_research_corpus_snapshot
from smeme.reasoning.evidence_contract import sha256_hex


def test_empty_snapshot_yields_no_manifest() -> None:
    snap = build_research_corpus_snapshot(None)
    assert build_corpus_chunk_manifest(snap) == ()


def test_stable_chunk_ids_and_content_digests() -> None:
    body = "alpha\n\nbeta\n\ngamma"
    snap = build_research_corpus_snapshot(body)
    assert snap.sha256_hex is not None
    manifest = build_corpus_chunk_manifest(snap)
    assert len(manifest) == 3
    raw = snap.text.encode("utf-8")
    for i, row in enumerate(manifest):
        assert row.chunk_id == f"cc1-{snap.sha256_hex}-{i:04d}"
        seg = raw[row.utf8_byte_start : row.utf8_byte_end]
        assert row.content_sha256_hex == sha256_hex(seg)


def test_merge_keeps_at_most_max_chunks() -> None:
    parts = ["x"] * (MAX_CORPUS_CHUNKS + 8)
    body = "\n\n".join(parts)
    snap = build_research_corpus_snapshot(body)
    assert snap.sha256_hex is not None
    manifest = build_corpus_chunk_manifest(snap)
    assert len(manifest) <= MAX_CORPUS_CHUNKS


def test_manifest_stable_across_runs() -> None:
    snap1 = build_research_corpus_snapshot("same\n\ntext")
    snap2 = ResearchCorpusSnapshot(text=snap1.text, sha256_hex=snap1.sha256_hex)
    assert build_corpus_chunk_manifest(snap1) == build_corpus_chunk_manifest(snap2)
