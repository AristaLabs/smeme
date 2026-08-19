"""Canonical HTTP URLs for MCP resource + OAuth metadata (RFC 9728 / RFC 8414)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from smeme.core.config import Settings


def mcp_connector_url(settings: Settings) -> str:
    """URL users paste into remote MCP clients for this Core deployment."""
    return mcp_resource_url(settings)


def mcp_connect_template_context(settings: Settings) -> dict[str, Any]:
    """Jinja context for connector-first MCP setup (endpoint URL + static OAuth client id)."""
    deployment_url = mcp_resource_url(settings)
    connector_url = mcp_connector_url(settings)
    static_client_id = next(iter(settings.mcp_allowed_oauth_client_ids), "")
    return {
        "mcp_endpoint_url": deployment_url,
        "mcp_connector_url": connector_url,
        "mcp_connector_url_differs": connector_url != deployment_url,
        "mcp_oauth_client_id": static_client_id,
    }


def mcp_resource_url(settings: Settings) -> str:
    """Absolute URL of the Streamable HTTP MCP endpoint (OAuth ``resource``)."""
    base = settings.effective_base_url.rstrip("/")
    path = (
        settings.mcp_http_path
        if settings.mcp_http_path.startswith("/")
        else f"/{settings.mcp_http_path}"
    )
    return f"{base}{path}"


def mcp_orchestrator_http_path(settings: Settings) -> str:
    """Path of the Inquire orchestrator MCP mount (sibling under chat MCP path)."""
    base = (
        settings.mcp_http_path
        if settings.mcp_http_path.startswith("/")
        else f"/{settings.mcp_http_path}"
    ).rstrip("/")
    return f"{base}/orchestrator"


def mcp_orchestrator_resource_url(settings: Settings) -> str:
    """Absolute URL of the Inquire orchestrator MCP endpoint (OAuth ``resource``)."""
    return f"{settings.effective_base_url.rstrip('/')}{mcp_orchestrator_http_path(settings)}"


def oauth_protected_resource_metadata_path(settings: Settings) -> str:
    """Path only: ``/.well-known/oauth-protected-resource`` + resource path (RFC 9728 §3)."""
    path = (
        settings.mcp_http_path
        if settings.mcp_http_path.startswith("/")
        else f"/{settings.mcp_http_path}"
    )
    return f"/.well-known/oauth-protected-resource{path}"


def oauth_orchestrator_protected_resource_metadata_path(settings: Settings) -> str:
    """RFC 9728 well-known path for the orchestrator MCP resource."""
    return f"/.well-known/oauth-protected-resource{mcp_orchestrator_http_path(settings)}"


def transport_security_allowed_hosts(settings: Settings) -> tuple[list[str], list[str]]:
    """(allowed_hosts, allowed_origins) for MCP DNS rebinding protection when not in dev."""
    parsed = urlparse(settings.effective_base_url)
    netloc = parsed.netloc
    if not netloc:
        return ([], [])
    hostname = netloc.rsplit(":", 1)[0] if ":" in netloc else netloc
    hosts: list[str] = [netloc]
    if ":" in netloc:
        hosts.append(f"{hostname}:*")
    origins: list[str] = [f"{parsed.scheme}://{netloc}", f"{parsed.scheme}://{hostname}:*"]
    return hosts, origins
