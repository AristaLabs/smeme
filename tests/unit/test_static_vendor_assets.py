"""Self-hosted vendor JS assets exist and match their pinned checksums (M-04).

Core no longer loads HTMX from unpkg.com — see smeme/static/js/vendor/ and
smeme/templates/layouts/base.html. This test pins the exact bytes so a future
"just bump the version" edit cannot silently swap in unreviewed vendor code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parents[2] / "smeme" / "static" / "js" / "vendor"

EXPECTED_SHA256 = {
    "htmx-2.0.4.min.js": "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447",
    "htmx-ext-json-enc-2.0.1.js": "9899374573b1e3276618d4f46c5fff56b373b55f8bdde900f31ce3425dc478d3",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendor_files_exist():
    for filename in EXPECTED_SHA256:
        path = VENDOR_DIR / filename
        assert path.is_file(), f"missing self-hosted vendor asset: {path}"


def test_vendor_files_match_pinned_checksums():
    for filename, expected_digest in EXPECTED_SHA256.items():
        path = VENDOR_DIR / filename
        actual_digest = _sha256(path)
        assert actual_digest == expected_digest, (
            f"{filename} sha256 mismatch: expected {expected_digest}, got {actual_digest}. "
            "If this is an intentional version bump, update EXPECTED_SHA256 after reviewing "
            "the new vendor file."
        )
