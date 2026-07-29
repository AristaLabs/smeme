"""Jinja context for creator docs (/docs/*)."""

from typing import Any

from starlette.requests import Request

from smeme.core.config import settings
from smeme.docs.constants import DOCS_VERSION


def docs_context_processor(request: Request) -> dict[str, Any]:
    """Inject docs version and absolute site base for canonical/OG URLs."""
    _ = request
    return {
        "docs_version": DOCS_VERSION,
        "site_base": settings.effective_base_url.rstrip("/"),
    }
