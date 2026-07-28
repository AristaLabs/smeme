"""Phase B file ingestion: validate, parse, merge into research corpus.

Per docs/planning/decision_tree-generation-ux-refinement.md §4.3, §4.7.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import secrets
import zipfile
from pathlib import Path
from typing import NamedTuple

from starlette.datastructures import UploadFile

from smeme.decision_tree.generation.agentic.file_limits import (
    ALLOWED_EXTENSIONS,
    MAX_DOCX_COMPRESSION_RATIO,
    MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES,
    MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_DOCX_ZIP_ENTRIES,
    MAX_EXTRACTED_TEXT_CHARS,
    MAX_FILE_SIZE_BYTES,
    UPLOAD_TEMP_DIR,
)

logger = logging.getLogger("smeme.decision_tree.generation.agentic.ingestion")

# Magic bytes for validation (per plan §4.2)
MAGIC_PDF = b"%PDF"
MAGIC_DOCX = b"PK"  # DOCX is zip
MAGIC_TXT = None  # No magic; validate by extension only

# Parse timeout (seconds) per plan §4.7
PARSE_TIMEOUT_SECONDS = 30

# Extensions that run in a killable child process
_ISOLATED_PARSE_EXTENSIONS = frozenset({".pdf", ".docx"})


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


def assert_docx_zip_bounds(path: Path) -> None:
    """Reject DOCX ZIP bombs before python-docx expands entries."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid DOCX (not a valid ZIP)") from exc

    if len(infos) > MAX_DOCX_ZIP_ENTRIES:
        msg = f"DOCX has too many entries (max {MAX_DOCX_ZIP_ENTRIES})"
        raise ValueError(msg)

    total_uncompressed = 0
    for info in infos:
        if info.file_size < 0 or info.compress_size < 0:
            raise ValueError("DOCX entry has invalid sizes")
        if info.file_size > MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES:
            raise ValueError("DOCX entry exceeds uncompressed size limit")
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_DOCX_COMPRESSION_RATIO:
                raise ValueError("DOCX compression ratio too high")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("DOCX total uncompressed size exceeds limit")


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
    """Parse DOCX to text via python-docx after ZIP bounds checks."""
    from docx import Document

    assert_docx_zip_bounds(path)
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


def _parse_file_process_entry(path_str: str, ext: str, conn) -> None:
    """Child-process entrypoint: parse and send (status, payload)."""
    try:
        text = parse_file(Path(path_str), ext)
        conn.send(("ok", text))
    except Exception as exc:  # noqa: BLE001 - isolate all parser failures
        conn.send(("err", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def _parse_file_in_process(path: Path, ext: str, timeout: float) -> str:
    """Parse PDF/DOCX in a killable child process with a hard timeout."""
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_parse_file_process_entry,
        args=(str(path), ext, child_conn),
        daemon=True,
    )
    proc.start()
    child_conn.close()
    status: str | None = None
    payload: str | None = None
    try:
        if parent_conn.poll(timeout):
            status, payload = parent_conn.recv()
        else:
            if proc.is_alive():
                proc.kill()
            msg = f"Parse timed out after {int(timeout)}s"
            raise TimeoutError(msg)
    finally:
        parent_conn.close()
        if proc.is_alive():
            proc.kill()
        proc.join(5)

    if status == "ok" and payload is not None:
        return payload
    raise RuntimeError(payload or "Parse failed in child process")


def _parse_file_sync(path: Path, ext: str) -> str:
    """Sync parse; used from asyncio.to_thread for timeout."""
    return parse_file(path, ext)


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


async def parse_uploaded_file(path: Path, original_filename: str) -> ParseResult:
    """
    Parse stored file to text.

    PDF/DOCX run in a killable child process so a stuck parser cannot pin a
    worker thread. Plain text stays in-process with an asyncio timeout.
    """
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ParseResult(original_filename, "", False, f"Unsupported: {ext}")

    try:
        if ext in _ISOLATED_PARSE_EXTENSIONS:
            text = await asyncio.to_thread(
                _parse_file_in_process,
                path,
                ext,
                float(PARSE_TIMEOUT_SECONDS),
            )
        else:
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
