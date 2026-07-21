"""Phase B file ingestion limits.

Per docs/planning/qnr-generation-ux-refinement.md §4.5.
Enforce at validation and parse.
"""

import tempfile
from pathlib import Path

# Max file size per file (bytes)
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# Max total bytes per request (aggregate)
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB

# Max files per generation
MAX_FILES_PER_GENERATION = 10

# Max extracted text chars (across all sources; shared with pasted text per plan)
MAX_EXTRACTED_TEXT_CHARS = 100_000

# Allowed file extensions and MIME types
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}
ALLOWED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Dedicated temp dir for ephemeral uploads (per plan §4.2)
UPLOAD_TEMP_DIR = Path(tempfile.gettempdir()) / "smeme_uploads"
