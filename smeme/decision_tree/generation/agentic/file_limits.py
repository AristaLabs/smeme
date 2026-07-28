"""Phase B file ingestion limits.

Per docs/planning/decision_tree-generation-ux-refinement.md §4.5.
Enforce at validation and parse.
"""

import tempfile
from pathlib import Path

# Max file size per file (bytes)
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# Max total bytes per request (aggregate uploads)
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB

# Whole multipart body budget: uploads + form fields overhead
MAX_REQUEST_BODY_BYTES = MAX_TOTAL_BYTES + (2 * 1024 * 1024)  # 22 MB

# Max files per generation
MAX_FILES_PER_GENERATION = 10

# Multipart form parser caps (Starlette Request.form)
MAX_FORM_FILES = MAX_FILES_PER_GENERATION
MAX_FORM_FIELDS = 50
# Non-file parts only (Starlette); file parts rely on body + per-file limits.
MAX_FORM_PART_SIZE_BYTES = 1024 * 1024  # 1 MB

# Max extracted text chars (across all sources; shared with pasted text per plan)
MAX_EXTRACTED_TEXT_CHARS = 100_000

# Allowed file extensions and MIME types
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
ALLOWED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# DOCX is a ZIP — bound expansion before python-docx opens it
MAX_DOCX_ZIP_ENTRIES = 200
MAX_DOCX_ENTRY_UNCOMPRESSED_BYTES = 10 * 1024 * 1024  # 10 MB per entry
MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MB total
MAX_DOCX_COMPRESSION_RATIO = 100.0

# Dedicated temp dir for ephemeral uploads (per plan §4.2)
UPLOAD_TEMP_DIR = Path(tempfile.gettempdir()) / "smeme_uploads"
