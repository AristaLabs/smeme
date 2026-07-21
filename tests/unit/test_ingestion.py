"""Unit tests for Phase B file ingestion.

Per docs/planning/qnr-generation-ux-refinement.md §4.10.
Tests: magic bytes, size limits, prepare_research_corpus, parse (with temp files).
"""

import tempfile
from io import BytesIO
from pathlib import Path

import pytest

from smeme.qnr.generation.agentic import ingestion
from smeme.qnr.generation.agentic.file_limits import (
    MAX_EXTRACTED_TEXT_CHARS,
    MAX_FILE_SIZE_BYTES,
)
from smeme.qnr.generation.agentic.ingestion import (
    parse_file,
    parse_uploaded_file,
    prepare_research_corpus,
    validate_and_store_upload,
)


def _fake_upload(content: bytes, filename: str):
    """Create a Starlette-like upload with async read."""
    stream = BytesIO(content)

    class FakeUpload:
        def __init__(self):
            self.filename = filename

        async def read(self, size: int = -1) -> bytes:
            return stream.read(size) if size != -1 else stream.read()

    return FakeUpload()


# ---------------------------------------------------------------------------
# Magic bytes (security: bad magic rejected)
# ---------------------------------------------------------------------------


class TestCheckMagicBytes:
    """Security: reject wrong magic bytes per plan §4.2."""

    def test_pdf_valid_magic(self):
        assert ingestion._check_magic_bytes(b"%PDF-1.4\n", ".pdf") is True

    def test_pdf_bad_magic_rejected(self):
        # .pdf with non-PDF content
        assert ingestion._check_magic_bytes(b"not a pdf", ".pdf") is False
        assert ingestion._check_magic_bytes(b"PK\x03\x04", ".pdf") is False

    def test_docx_valid_magic(self):
        # DOCX is ZIP (starts with PK)
        assert ingestion._check_magic_bytes(b"PK\x03\x04", ".docx") is True

    def test_docx_bad_magic_rejected(self):
        assert ingestion._check_magic_bytes(b"%PDF", ".docx") is False
        assert ingestion._check_magic_bytes(b"plain text", ".docx") is False

    def test_txt_always_valid(self):
        # .txt has no magic check
        assert ingestion._check_magic_bytes(b"anything", ".txt") is True


# ---------------------------------------------------------------------------
# Size limits (security: oversized rejected)
# ---------------------------------------------------------------------------


class TestValidateAndStoreUpload:
    """validate_and_store_upload: size, type, magic."""

    @pytest.mark.asyncio
    async def test_oversized_file_rejected(self):
        # One byte over 5 MB
        big = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        upload = _fake_upload(big, "huge.txt")
        path, err = await validate_and_store_upload(upload, 0)
        assert path is None
        assert "5 MB" in (err or "")

    @pytest.mark.asyncio
    async def test_valid_txt_accepted(self):
        content = b"Hello world"
        upload = _fake_upload(content, "test.txt")
        path, err = await validate_and_store_upload(upload, 0)
        assert err is None
        assert path is not None
        assert path.exists()
        assert path.read_bytes() == content
        path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_valid_pdf_accepted(self):
        # Minimal PDF
        content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        upload = _fake_upload(content, "test.pdf")
        path, err = await validate_and_store_upload(upload, 0)
        assert err is None
        assert path is not None
        path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_bad_magic_rejected(self):
        content = b"not a pdf"
        upload = _fake_upload(content, "fake.pdf")
        path, err = await validate_and_store_upload(upload, 0)
        assert path is None
        assert "bad magic" in (err or "").lower()


# ---------------------------------------------------------------------------
# prepare_research_corpus
# ---------------------------------------------------------------------------


class TestPrepareResearchCorpus:
    """prepare_research_corpus merges pasted + file text."""

    def test_empty_returns_empty(self):
        assert prepare_research_corpus("", []) == ""

    def test_pasted_only(self):
        out = prepare_research_corpus("Hello pasted", [])
        assert "Pasted text" in out
        assert "Hello pasted" in out

    def test_files_only(self):
        out = prepare_research_corpus("", [("doc.pdf", "File content here")])
        assert "Uploaded Document: doc.pdf" in out
        assert "File content here" in out

    def test_merges_both(self):
        out = prepare_research_corpus("Pasted", [("a.pdf", "From file")])
        assert "Pasted text" in out
        assert "Pasted" in out
        assert "Uploaded Document: a.pdf" in out
        assert "From file" in out

    def test_respects_max_chars(self):
        long_text = "x" * (MAX_EXTRACTED_TEXT_CHARS + 1000)
        out = prepare_research_corpus(long_text, [])
        assert len(out) <= MAX_EXTRACTED_TEXT_CHARS + 100  # header overhead


# ---------------------------------------------------------------------------
# parse_file / parse_uploaded_file (happy path + timeout)
# ---------------------------------------------------------------------------


class TestParseUploadedFile:
    """Parse uploaded file to text."""

    def test_parse_txt(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Hello\nWorld")
            f.flush()
            path = Path(f.name)
        try:
            text = parse_file(path, ".txt")
            assert "Hello" in text
            assert "World" in text
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_parse_uploaded_txt_success(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test content")
            f.flush()
            path = Path(f.name)
        try:
            result = await parse_uploaded_file(path, "test.txt")
            assert result.success is True
            assert "Test content" in result.text
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_parse_uploaded_pdf_success(self):
        # Create a minimal valid PDF using pypdf (avoids "Stream has ended unexpectedly")
        from pypdf import PdfWriter

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            writer = PdfWriter()
            writer.add_blank_page(72, 72)
            writer.write(f)
            path = Path(f.name)
        try:
            result = await parse_uploaded_file(path, "minimal.pdf")
            assert result.success is True
        finally:
            path.unlink(missing_ok=True)
