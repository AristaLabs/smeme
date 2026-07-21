"""Safe, structured auth telemetry for MCP HTTP debugging (DR-3).

Logs booleans and lengths only — never token or API key values. Used to tell
client bugs (no ``Authorization`` on wire) from JWT/issuer/DB failures.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


def authorization_shape(*, authorization_value: str | None) -> dict[str, Any]:
    """Classify ``Authorization`` header without logging secrets."""
    raw = authorization_value if authorization_value is not None else ""
    ah = raw.strip()
    if not ah:
        return {
            "has_authorization_header": False,
            "authorization_scheme": "none",
            "bearer_token_length": 0,
        }
    low = ah.lower()
    if low.startswith("bearer "):
        token = ah[7:].strip()
        return {
            "has_authorization_header": True,
            "authorization_scheme": "bearer",
            "bearer_token_length": len(token),
        }
    return {
        "has_authorization_header": True,
        "authorization_scheme": "other",
        "bearer_token_length": 0,
    }


def api_key_shape(*, x_api_key_value: str | None) -> dict[str, Any]:
    """Whether ``X-Api-Key`` (or similar) is present; length only."""
    val = (x_api_key_value or "").strip()
    return {
        "has_api_key_header": bool(val),
        "api_key_header_length": len(val),
    }


def inbound_http_telemetry_dict(request: Request) -> dict[str, Any]:
    """Single JSON-serializable blob for middleware (inbound MCP HTTP)."""
    auth = request.headers.get("authorization")
    xak = request.headers.get("x-api-key")
    ua = (request.headers.get("user-agent") or "").strip()
    return {
        "stage": "inbound_http",
        "method": request.method,
        "path": request.url.path,
        **authorization_shape(authorization_value=auth),
        **api_key_shape(x_api_key_value=xak),
        "user_agent_length": len(ua),
    }


def tool_auth_context(request: Request) -> dict[str, Any]:
    """Shared header shape for tool-layer auth failures."""
    return {
        **authorization_shape(authorization_value=request.headers.get("authorization")),
        **api_key_shape(x_api_key_value=request.headers.get("x-api-key")),
    }
