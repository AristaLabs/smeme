"""Canonical HTTP URLs for MCP resource + OAuth metadata (RFC 9728 / RFC 8414)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from smeme.core.config import Settings

# Public PKCE client id for SMEme's first-party Clerk OAuth app (connector setup).
MCP_SAAS_OAUTH_CLIENT_ID = "NRdsdBvrio0DW9yo"
# Canonical remote MCP URL for SaaS prod.
MCP_SAAS_PUBLIC_MCP_URL = "https://www.smeme.ai/api/v1/mcp"


def _is_local_dev_host(hostname: str | None) -> bool:
    if not hostname:
        return True
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    return hostname.endswith(".local")


def mcp_connector_url(settings: Settings) -> str:
    """URL end users paste into remote MCP clients (Claude, ChatGPT, etc.).

    On localhost dev, docs/dashboard show SaaS prod — not ``effective_base_url``.
    On deployed hosts (prod, staging, self-hosted), use this deployment's resource URL.
    """
    deployment = mcp_resource_url(settings)
    parsed = urlparse(settings.effective_base_url)
    if _is_local_dev_host(parsed.hostname):
        return MCP_SAAS_PUBLIC_MCP_URL
    return deployment


def mcp_connect_template_context(settings: Settings) -> dict[str, Any]:
    """Jinja context for connector-first MCP setup (endpoint URL + static OAuth client id)."""
    deployment_url = mcp_resource_url(settings)
    connector_url = mcp_connector_url(settings)
    return {
        "mcp_endpoint_url": deployment_url,
        "mcp_connector_url": connector_url,
        "mcp_connector_url_differs": connector_url != deployment_url,
        "mcp_oauth_client_id": MCP_SAAS_OAUTH_CLIENT_ID,
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


def oauth_protected_resource_metadata_path(settings: Settings) -> str:
    """Path only: ``/.well-known/oauth-protected-resource`` + resource path (RFC 9728 §3)."""
    path = (
        settings.mcp_http_path
        if settings.mcp_http_path.startswith("/")
        else f"/{settings.mcp_http_path}"
    )
    return f"/.well-known/oauth-protected-resource{path}"


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
