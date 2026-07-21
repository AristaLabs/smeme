"""Jinja context for authenticated creator docs."""

from starlette.requests import Request

from smeme.docs.constants import DOCS_VERSION


def docs_context_processor(request: Request) -> dict[str, str]:
    """Inject docs version into every template (used in /docs/* partials)."""
    _ = request
    return {"docs_version": DOCS_VERSION}
