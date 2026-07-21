"""Phase B file ingestion: validate, parse, merge into research corpus.

Per docs/planning/qnr-generation-ux-refinement.md §4.3, §4.7.
"""

import asyncio
import logging
import secrets
from pathlib import Path
from typing import NamedTuple

from starlette.datastructures import UploadFile

from smeme.qnr.generation.agentic.file_limits import (
    ALLOWED_EXTENSIONS,
    MAX_EXTRACTED_TEXT_CHARS,
    MAX_FILE_SIZE_BYTES,
    UPLOAD_TEMP_DIR,
)

logger = logging.getLogger("smeme.qnr.generation.agentic.ingestion")

# Magic bytes for validation (per plan §4.2)
MAGIC_PDF = b"%PDF"
MAGIC_DOCX = b"PK"  # DOCX is zip
MAGIC_TXT = None  # No magic; validate by extension only

# Parse timeout (seconds) per plan §4.7
PARSE_TIMEOUT_SECONDS = 30


class ParseResult(NamedTuple):
    """Result of parsing a single file."""

    filename: str
    text: str
    success: bool
    error: str | None = None


class IngestionError(NamedTuple):
    """Parse failure for UX (per plan §4.9)."""

    filename: str
    reason: str


def _ensure_upload_dir() -> Path:
    """Ensure upload temp dir exists."""
    UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_TEMP_DIR


def _check_magic_bytes(content: bytes, ext: str) -> bool:
    """Validate magic bytes match extension."""
    if ext == ".txt":
        return True
    if ext == ".pdf" and content.startswith(MAGIC_PDF):
        return True
    return ext == ".docx" and content.startswith(MAGIC_DOCX)


def _parse_txt(content: bytes) -> str:
    """Parse plain text."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_pdf(path: Path) -> str:
    """Parse PDF to text via pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _parse_docx(path: Path) -> str:
    """Parse DOCX to text via python-docx."""
    from docx import Document

    doc = Document(str(path))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_file(path: Path, ext: str) -> str:
    """Parse file to text. Raises on failure."""
    if ext == ".txt":
        return _parse_txt(path.read_bytes())
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".docx":
        return _parse_docx(path)
    msg = f"Unsupported extension: {ext}"
    raise ValueError(msg)


async def validate_and_store_upload(
    upload: UploadFile,
    file_index: int,
) -> tuple[Path | None, str | None]:
    """
    Validate upload (size, type, magic bytes), store to temp, return path or error.

    Returns (path, None) on success, (None, error_message) on failure.
    """
    if not upload.filename:
        return None, "File has no filename"

    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, f"File type '{ext}' not allowed. Use .txt, .pdf, or .docx"

    # Stream with size limit
    content = bytearray()
    while chunk := await upload.read(64 * 1024):
        content.extend(chunk)
        if len(content) > MAX_FILE_SIZE_BYTES:
            return None, f"File exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit"

    if not content:
        return None, "File is empty"

    if not _check_magic_bytes(bytes(content), ext):
        return None, f"File content does not match extension {ext} (bad magic bytes)"

    # Write to temp with randomized name
    _ensure_upload_dir()
    safe_name = f"{secrets.token_hex(8)}_{file_index}{ext}"
    dest = UPLOAD_TEMP_DIR / safe_name
    dest.write_bytes(content)
    return dest, None


def _parse_file_sync(path: Path, ext: str) -> str:
    """Sync parse; used from asyncio.to_thread for timeout."""
    return parse_file(path, ext)


async def parse_uploaded_file(path: Path, original_filename: str) -> ParseResult:
    """
    Parse stored file to text. Runs in thread pool with timeout (per plan §4.7).

    Returns ParseResult with success=True and text, or success=False and error.
    """
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ParseResult(original_filename, "", False, f"Unsupported: {ext}")

    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_parse_file_sync, path, ext),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
        return ParseResult(original_filename, text[:MAX_EXTRACTED_TEXT_CHARS], True)
    except TimeoutError:
        return ParseResult(original_filename, "", False, "Parse timed out")
    except Exception as e:
        logger.exception("Parse failed for %s", original_filename)
        return ParseResult(original_filename, "", False, str(e))


def prepare_research_corpus(
    pasted_text: str,
    file_items: list[tuple[str, str]],
    max_chars: int = MAX_EXTRACTED_TEXT_CHARS,
) -> str:
    """
    Merge pasted text and extracted file text into single corpus.

    Per plan §4.3: prepare_research_corpus merges pasted + file text.
    File items are (filename, text) tuples so the LLM can cite uploaded docs.
    """
    parts = []
    total = 0
    if pasted_text and pasted_text.strip():
        chunk = pasted_text.strip()[:max_chars]
        parts.append("**Pasted text** (cite as 'Pasted text' when relevant)\n" + chunk)
        total += len(chunk)
    for filename, text in file_items:
        if not text or not text.strip():
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        chunk = text.strip()[:remaining]
        safe_name = filename or "uploaded file"
        parts.append(
            f"\n**Uploaded Document: {safe_name}** (cite as 'Uploaded document ({safe_name})' when relevant)\n{chunk}"
        )
        total += len(chunk)
    return "\n".join(parts) if parts else ""
