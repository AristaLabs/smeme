"""Normalize SME research corpus text and compute artifact-grade SHA-256."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from smeme.reasoning.evidence_contract import sha256_hex

# Align with sprint sizing guidance (half MB UTF-8 budget).
MAX_RESEARCH_CORPUS_BYTES: int = 512 * 1024


@dataclass(frozen=True, slots=True)
class ResearchCorpusSnapshot:
    """Single publish-time binding: normalized+truncated UTF-8 text and its digest.

    Induction and provenance must use this object (or a copy of ``text``) so the hash always
    matches the bytes that were processed.

    **No corpus** (``body`` missing, or empty after normalize): ``text == ""``,
    ``sha256_hex is None``, ``utf8_byte_length == 0``, ``utf8_bytes == b""``.
    """

    text: str
    sha256_hex: str | None

    @property
    def utf8_bytes(self) -> bytes:
        return self.text.encode("utf-8")

    @property
    def utf8_byte_length(self) -> int:
        """Length of :attr:`utf8_bytes` (0 when there is no corpus content)."""
        return len(self.utf8_bytes)


def build_research_corpus_snapshot(body: str | None) -> ResearchCorpusSnapshot:
    """Build the canonical normalized snapshot (empty text and no hash when there is no content)."""
    if body is None:
        return ResearchCorpusSnapshot(text="", sha256_hex=None)
    norm = truncate_corpus_to_max_bytes(normalize_corpus_text(body))
    if not norm:
        return ResearchCorpusSnapshot(text="", sha256_hex=None)
    raw = norm.encode("utf-8")
    return ResearchCorpusSnapshot(text=norm, sha256_hex=sha256_hex(raw))


def normalize_corpus_text(raw: str) -> str:
    """NFC, unify newlines, trim ends (no semantic changes to intentional inner whitespace)."""
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    t = unicodedata.normalize("NFC", t)
    return t.strip()


def truncate_corpus_to_max_bytes(text: str, *, max_bytes: int = MAX_RESEARCH_CORPUS_BYTES) -> str:
    """Truncate by UTF-8 byte length so persisted blobs stay bounded."""
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    cut = data[:max_bytes]
    while cut and (cut[-1] & 0xC0) == 0x80:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="ignore")


def normalized_corpus_sha256_or_none(body: str | None) -> str | None:
    """SHA-256 hex of normalized+truncated corpus, or None when empty after normalize."""
    return build_research_corpus_snapshot(body).sha256_hex
