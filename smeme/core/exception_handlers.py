"""Global exception handlers for FastAPI application.

These handlers provide consistent error responses and detailed logging
across all routes and validation errors.
"""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from smeme.core.callout_html import render_callout_html
from smeme.core.templates import templates

logger = logging.getLogger(__name__)

# Paths that must always receive machine-readable (JSON) errors, never HTML pages.
_JSON_ONLY_PREFIXES = ("/api/", "/.well-known/", "/oauth")


def _wants_html_page(request: Request) -> bool:
    """True only for top-level browser navigations that should get a full HTML error page.

    Excludes API/MCP/OAuth paths (JSON contracts) and HTMX requests (expect fragments).
    """
    accept = request.headers.get("accept", "")
    if "text/html" not in accept:
        return False
    if request.headers.get("hx-request") == "true":
        return False
    return not request.url.path.startswith(_JSON_ONLY_PREFIXES)


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> HTMLResponse | JSONResponse:
    """
    Global handler for Pydantic validation errors.

    Catches validation errors from:
    - Form data (application/x-www-form-urlencoded)
    - JSON bodies (application/json)
    - Query parameters
    - Path parameters
    - Headers

    Provides:
    - Detailed error logging for debugging
    - User-friendly error responses
    - HTMX-aware responses (HTML fragments vs JSON)

    Args:
        request: The incoming request
        exc: The validation exception with error details

    Returns:
        HTMLResponse for HTMX requests, JSONResponse otherwise
    """
    # Extract validation errors without echoing rejected input values into logs/UI.
    try:
        errors = exc.errors(include_input=False, include_context=False)
    except TypeError:
        errors = [
            {k: v for k, v in err.items() if k not in {"input", "ctx"}} for err in exc.errors()
        ]

    # Log detailed error information
    logger.error(f"Validation error in request: {request.method} {request.url.path}")
    logger.error(f"Error count: {len(errors)}")
    logger.error(f"Validation errors: {errors}")

    # Try to log the actual request data for debugging
    try:
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")

            if (
                "application/x-www-form-urlencoded" in content_type
                or "multipart/form-data" in content_type
            ):
                # Form data
                form_data = await request.form()
                logger.error("Form fields received: %s", list(form_data.keys()))
            elif "application/json" in content_type:
                # JSON body
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        logger.error("JSON object keys received: %s", list(body.keys()))
                    elif isinstance(body, list):
                        logger.error("JSON array length received: %s", len(body))
                    else:
                        logger.error("JSON body type received: %s", type(body).__name__)
                except Exception:
                    # Body already consumed or invalid JSON
                    pass

    except Exception as e:
        logger.warning(f"Could not log request body: {e}")

    # Format error messages for user display
    error_messages = []
    for err in errors:
        # Extract field name (last element of loc tuple)
        field = err["loc"][-1] if err["loc"] else "unknown"
        msg = err["msg"]
        error_messages.append(f"{field}: {msg}")

    # Check if this is an HTMX request
    is_htmx = request.headers.get("hx-request") == "true"

    if is_htmx:
        # Return HTML fragment for HTMX swap
        errors_html = "".join(f'<div class="text-sm mb-1">• {msg}</div>' for msg in error_messages)

        html_response = render_callout_html(
            title="Validation Error",
            body=errors_html,
            type="error",
        )

        return HTMLResponse(content=html_response, status_code=422)

    # Return JSON for API requests
    return JSONResponse(
        status_code=422,
        content={
            "detail": errors,
            "error_summary": error_messages,
        },
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> Response:
    """Render a friendly HTML 404 for browser navigations; preserve JSON everywhere else.

    Faithfully reproduces Starlette's default JSON body/headers for all non-browser cases and
    all non-404 statuses, so API/MCP/OAuth contracts and the 401→login middleware are unaffected.
    """
    if exc.status_code == 404 and request.method == "GET" and _wants_html_page(request):
        return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def generic_error_handler(
    request: Request,
    exc: Exception,
) -> Response:
    """
    Catch-all handler for unexpected exceptions.

    Renders a branded 500 page for browser navigations and a generic JSON body for
    API/HTMX/MCP clients. Never exposes internal details.
    """
    logger.error(
        "Unexpected error in request",
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        },
        exc_info=True,
    )

    if _wants_html_page(request):
        return templates.TemplateResponse(request, "errors/500.html", {}, status_code=500)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Please try again or contact support.",
            "error_type": type(exc).__name__,
        },
    )
