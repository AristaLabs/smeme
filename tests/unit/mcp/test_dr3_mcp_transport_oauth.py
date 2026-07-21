"""DR-3: Streamable HTTP MCP transport OAuth challenge (401 + WWW-Authenticate)."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.routes import build_resource_metadata_url
from pydantic import AnyHttpUrl

from smeme.core.middleware import McpTransportRateLimitMiddleware
from smeme.core.config import Settings
from smeme.core.config import settings as process_settings
from smeme.app_factory import create_core_app as create_app
from smeme.mcp.reasoning_fastmcp import reset_mcp_runtime_for_tests
from smeme.mcp.urls import mcp_resource_url, oauth_protected_resource_metadata_path

CLERK_ISSUER = "https://clerk.example.com"


def _minimal_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Settings:
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("CLERK_OAUTH_ISSUER", raising=False)
    update: dict[str, Any] = {
        "base_url": "https://api.example.com",
        "mcp_http_path": "/api/v1/mcp",
        "clerk_oauth_issuer_override": None,
        "clerk_publishable_key": None,
        "clerk_secret_key": None,
        "clerk_sign_in_url": None,
    }
    update.update(kwargs)
    return process_settings.model_copy(update=update)


def _minimal_settings_with_clerk(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Settings:
    update: dict[str, Any] = {"clerk_oauth_issuer_override": CLERK_ISSUER}
    update.update(kwargs)
    return _minimal_settings(monkeypatch, **update)


def _expected_resource_metadata_url_str(s: Settings) -> str:
    """Absolute RFC 9728 metadata URL (same as FastAPI discovery + SDK helper)."""
    base = s.effective_base_url.rstrip("/")
    return f"{base}{oauth_protected_resource_metadata_path(s)}"


def _parse_resource_metadata(www_authenticate: str) -> str | None:
    m = re.search(r'resource_metadata="([^"]+)"', www_authenticate)
    return m.group(1) if m else None


MCP_ACCEPT = "application/json, text/event-stream"


def _fake_bearer_with_sub(sub: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.mark.asyncio
async def test_mcp_unauthenticated_post_401_www_authenticate(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    expected_meta = _expected_resource_metadata_url_str(s)
    assert expected_meta == str(
        build_resource_metadata_url(AnyHttpUrl(mcp_resource_url(s)))
    )

    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post(
            "/api/v1/mcp/",
            json={"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
            headers={
                "Accept": MCP_ACCEPT,
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 401, r.text
    www = r.headers.get("www-authenticate", "")
    assert www, "WWW-Authenticate must be present for OAuth bootstrap"
    assert "Bearer" in www
    assert 'error="invalid_token"' in www or "invalid_token" in www
    meta = _parse_resource_metadata(www)
    assert meta == expected_meta
    err = r.json()
    assert err.get("error") == "invalid_token"


@pytest.mark.asyncio
async def test_mcp_invalid_bearer_post_401_same_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    expected_meta = _expected_resource_metadata_url_str(s)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post(
            "/api/v1/mcp/",
            json={"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
            headers={
                "Accept": MCP_ACCEPT,
                "Content-Type": "application/json",
                "Authorization": "Bearer not.a.valid.jwt.structure",
            },
        )
    assert r.status_code == 401
    meta = _parse_resource_metadata(r.headers.get("www-authenticate", ""))
    assert meta == expected_meta


@pytest.mark.asyncio
async def test_mcp_tools_call_without_bearer_not_200_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing Authorization must not yield HTTP 200 + in-band tool auth_error (regression)."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        r = await client.post(
            "/api/v1/mcp/",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "smeme_reasoning_list", "arguments": {}},
                "id": 2,
            },
            headers={
                "Accept": MCP_ACCEPT,
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 401
    assert "auth_error" not in r.text


def test_no_clerk_fastmcp_has_no_sdk_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Clerk, we do not enable AuthSettings (Streamable HTTP needs lifespan for real POSTs)."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings(monkeypatch, mcp_enabled=True)
    from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp

    fm = get_or_create_fastmcp(s)
    assert fm.settings.auth is None


@pytest.mark.skip(reason="D016 P3: enable when Clerk issues dtq:* and required_scopes is set on AuthSettings")
@pytest.mark.asyncio
async def test_mcp_insufficient_scope_403_placeholder() -> None:
    assert False


@pytest.mark.asyncio
async def test_mcp_unauthenticated_401_when_accept_includes_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test", follow_redirects=False) as client:
        r = await client.post(
            "/api/v1/mcp/",
            json={"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1},
            headers={
                "Accept": f"{MCP_ACCEPT}, text/html",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_mcp_transport_rate_limit_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(
        monkeypatch,
        mcp_enabled=True,
        mcp_transport_rate_limit_per_ip_per_minute=2,
        mcp_transport_rate_limit_per_sub_per_minute=10,
    )
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        headers = {"Accept": MCP_ACCEPT, "Content-Type": "application/json"}
        payload = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        r1 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
        r2 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
        r3 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 429
    assert r3.json().get("error") == "rate_limited"
    assert int(r3.headers.get("Retry-After", "0")) >= 1


@pytest.mark.asyncio
async def test_mcp_transport_rate_limit_per_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(
        monkeypatch,
        mcp_enabled=True,
        mcp_transport_rate_limit_per_ip_per_minute=100,
        mcp_transport_rate_limit_per_sub_per_minute=1,
    )
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    bearer = _fake_bearer_with_sub("user_test_123")
    verify_sub = AsyncMock(return_value="user_test_123")
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        headers = {
            "Accept": MCP_ACCEPT,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
        }
        payload = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        with patch.object(
            McpTransportRateLimitMiddleware,
            "_verified_subject_from_bearer",
            verify_sub,
        ):
            r1 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
            r2 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
    assert r1.status_code == 401
    assert r2.status_code == 429
    assert r2.json().get("error") == "rate_limited"
    assert int(r2.headers.get("Retry-After", "0")) >= 1
    assert verify_sub.await_count == 2


@pytest.mark.asyncio
async def test_mcp_transport_spoofed_sub_does_not_consume_sub_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unverified JWT ``sub`` must not apply the per-sub transport bucket."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(
        monkeypatch,
        mcp_enabled=True,
        mcp_transport_rate_limit_per_ip_per_minute=100,
        mcp_transport_rate_limit_per_sub_per_minute=1,
    )
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    bearer = _fake_bearer_with_sub("victim_user_id")
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        headers = {
            "Accept": MCP_ACCEPT,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
        }
        payload = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        r1 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
        r2 = await client.post("/api/v1/mcp/", json=payload, headers=headers)
    assert r1.status_code == 401
    assert r2.status_code == 401
