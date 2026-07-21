"""Corpus normalization + digest."""

from smeme.reasoning.cevi.corpus_normalize import (
    build_research_corpus_snapshot,
    normalize_corpus_text,
    normalized_corpus_sha256_or_none,
)
from smeme.reasoning.evidence_contract import sha256_hex


def test_normalize_unifies_newlines() -> None:
    assert normalize_corpus_text("a\r\nb\rc") == "a\nb\nc"


def test_normalized_corpus_sha256_or_none_empty() -> None:
    assert normalized_corpus_sha256_or_none("") is None
    assert normalized_corpus_sha256_or_none("  \n  ") is None


def test_normalized_corpus_sha256_stable() -> None:
    h = normalized_corpus_sha256_or_none(" SME notes \n")
    assert h == sha256_hex(b"SME notes")


def test_build_research_corpus_snapshot_matches_hash_helper() -> None:
    raw = "  hello \n"
    snap = build_research_corpus_snapshot(raw)
    assert snap.text == "hello"
    assert snap.sha256_hex == normalized_corpus_sha256_or_none(raw)
    assert snap.utf8_bytes == b"hello"
    assert snap.utf8_byte_length == 5


def test_build_research_corpus_snapshot_no_corpus_empty_equivalence() -> None:
    """No durable corpus: explicit empty snapshot; hash omitted for provenance."""
    for body in (None, "", "  \n\t  "):
        snap = build_research_corpus_snapshot(body)
        assert snap.text == ""
        assert snap.sha256_hex is None
        assert snap.utf8_bytes == b""
        assert snap.utf8_byte_length == 0
