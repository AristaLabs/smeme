"""DR-3: OAuth protected-resource metadata + MCP URL helpers."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from smeme.app_factory import create_core_app as create_app
from smeme.core.config import Settings
from smeme.core.config import settings as process_settings
from smeme.mcp.discovery_routes import (
    _authorization_server_metadata_payload,
    _protected_resource_payload,
)
from smeme.mcp.reasoning_fastmcp import StripLastEventIdMiddleware, reset_mcp_runtime_for_tests
from smeme.mcp.urls import (
    mcp_connect_template_context,
    mcp_connector_url,
    mcp_resource_url,
    oauth_protected_resource_metadata_path,
)

CLERK_ISSUER = "https://clerk.example.com"


def _minimal_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> Settings:
    """Settings without Clerk configured (P1-Embedded / no-Clerk fallback path).

    Clears all Clerk keys so ``clerk_oauth_issuer`` returns None and the fallback
    path is exercised regardless of what is set in the local .env file.
    """
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("CLERK_OAUTH_ISSUER", raising=False)
    update: dict[str, object] = {
        "base_url": "https://api.example.com",
        "mcp_http_path": "/api/v1/mcp",
        "clerk_oauth_issuer_override": None,
        # Clear Clerk keys so clerk_frontend_api_host (and thus clerk_oauth_issuer) returns None.
        "clerk_publishable_key": None,
        "clerk_secret_key": None,
        "clerk_sign_in_url": None,
    }
    update.update(kwargs)
    return process_settings.model_copy(update=update)


def _minimal_settings_with_clerk(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> Settings:
    """Settings with Clerk configured as OAuth AS (P1-Clerk path)."""
    update: dict[str, object] = {"clerk_oauth_issuer_override": CLERK_ISSUER}
    update.update(kwargs)
    return _minimal_settings(monkeypatch, **update)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def test_mcp_resource_url(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _minimal_settings(monkeypatch)
    assert mcp_resource_url(s) == "https://api.example.com/api/v1/mcp"


def test_mcp_connector_url_localhost_matches_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _minimal_settings(monkeypatch, base_url="http://localhost:8000")
    assert mcp_resource_url(s) == "http://localhost:8000/api/v1/mcp"
    assert mcp_connector_url(s) == "http://localhost:8000/api/v1/mcp"


def test_mcp_connector_url_deployed_host_matches_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _minimal_settings(monkeypatch, base_url="https://core.example.com")
    assert mcp_connector_url(s) == "https://core.example.com/api/v1/mcp"


def test_mcp_connect_context_uses_operator_static_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _minimal_settings(
        monkeypatch,
        mcp_allowed_oauth_client_ids=["operator-client-id", "secondary-client-id"],
    )
    context = mcp_connect_template_context(s)
    assert context["mcp_oauth_client_id"] == "operator-client-id"


def test_mcp_connect_context_omits_client_id_when_dcr_or_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _minimal_settings(monkeypatch, mcp_allowed_oauth_client_ids=[])
    context = mcp_connect_template_context(s)
    assert context["mcp_oauth_client_id"] == ""


def test_oauth_protected_resource_metadata_path(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _minimal_settings(monkeypatch, mcp_http_path="/api/v1/mcp")
    assert oauth_protected_resource_metadata_path(s) == "/.well-known/oauth-protected-resource/api/v1/mcp"


# ---------------------------------------------------------------------------
# RFC 9728 payload
# ---------------------------------------------------------------------------


def test_protected_resource_payload_uses_clerk_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Clerk is configured, authorization_servers[0] must point at Clerk, not SMEme."""
    s = _minimal_settings_with_clerk(monkeypatch)
    doc = _protected_resource_payload(s)
    assert doc["resource"] == "https://api.example.com/api/v1/mcp"
    # No trailing slash — AnyHttpUrl adds one; we strip it to avoid double-slash in client URLs.
    assert doc["authorization_servers"][0] == CLERK_ISSUER
    assert doc["scopes_supported"] == ["profile", "email", "offline_access"]


def test_protected_resource_payload_fallback_without_clerk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Clerk, authorization_servers[0] falls back to SMEme's own origin."""
    s = _minimal_settings(monkeypatch)
    doc = _protected_resource_payload(s)
    assert doc["resource"] == "https://api.example.com/api/v1/mcp"
    # No trailing slash.
    assert doc["authorization_servers"][0] == "https://api.example.com"


# ---------------------------------------------------------------------------
# RFC 8414 AS metadata payload (fallback / P1-Embedded only)
# ---------------------------------------------------------------------------


def test_authorization_server_metadata_fallback_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """_authorization_server_metadata_payload describes SMEme-hosted endpoints (fallback only)."""
    s = _minimal_settings(monkeypatch)
    doc = _authorization_server_metadata_payload(s)
    assert doc["issuer"] == "https://api.example.com"
    assert doc["authorization_endpoint"].endswith("/oauth/authorize")
    assert doc["token_endpoint"].endswith("/oauth/token")


# ---------------------------------------------------------------------------
# HTTP integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_well_known_routes_clerk_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Clerk: RFC 9728 lists Clerk issuer (no trailing slash); AS metadata returns
    Clerk endpoints inline as JSON (200) to avoid CORS failures in browser-based clients."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        # RFC 9728 — resource metadata: authorization_servers must have no trailing slash.
        pr = await client.get("/.well-known/oauth-protected-resource/api/v1/mcp")
        assert pr.status_code == 200
        pr_doc = pr.json()
        assert pr_doc["resource"] == "https://api.example.com/api/v1/mcp"
        assert pr_doc["authorization_servers"][0] == CLERK_ISSUER  # no trailing slash

        # RFC 8414 — AS metadata: 200 JSON derived from Clerk issuer (not a redirect).
        as_meta = await client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        as_doc = as_meta.json()
        assert as_doc["issuer"] == CLERK_ISSUER
        assert as_doc["authorization_endpoint"] == f"{CLERK_ISSUER}/oauth/authorize"
        assert as_doc["token_endpoint"] == f"{CLERK_ISSUER}/oauth/token"
        assert as_doc["jwks_uri"] == f"{CLERK_ISSUER}/.well-known/jwks.json"
        # No registration_endpoint while Clerk DCR is off (avoid clients preferring DCR).
        assert "registration_endpoint" not in as_doc

        oidc = await client.get("/.well-known/openid-configuration")
        assert oidc.status_code == 200
        assert "registration_endpoint" not in oidc.json()


@pytest.mark.asyncio
async def test_well_known_routes_clerk_dcr_advertises_registration_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CLERK_OAUTH_DYNAMIC_REGISTRATION is on, mirror Clerk's register URL."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(
        monkeypatch,
        mcp_enabled=True,
        clerk_oauth_dynamic_registration=True,
    )
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    reg = f"{CLERK_ISSUER}/oauth/register"
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        as_meta = await client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        assert as_meta.json().get("registration_endpoint") == reg
        oidc = await client.get("/.well-known/openid-configuration")
        assert oidc.status_code == 200
        assert oidc.json().get("registration_endpoint") == reg


@pytest.mark.asyncio
async def test_well_known_routes_no_clerk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Clerk: RFC 9728 uses SMEme origin; AS metadata returns local stub."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings(monkeypatch, mcp_enabled=True)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        pr = await client.get("/.well-known/oauth-protected-resource/api/v1/mcp")
        assert pr.status_code == 200
        assert pr.json()["authorization_servers"][0].rstrip("/") == "https://api.example.com"

        as_meta = await client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        assert as_meta.json()["issuer"] == "https://api.example.com"


@pytest.mark.asyncio
async def test_mcp_mount_path_normalize_middleware_adds_slash() -> None:
    """Bare ``/api/v1/mcp`` is rewritten to ``/api/v1/mcp/`` before routing (no 307 + broken redirect)."""
    from smeme.mcp.reasoning_fastmcp import McpMountPathNormalizeMiddleware

    captured: list[str] = []

    async def inner(scope, receive, send):
        captured.append(scope["path"])
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_msg):
        pass

    await McpMountPathNormalizeMiddleware(inner, mcp_path="/api/v1/mcp")(
        {"type": "http", "path": "/api/v1/mcp", "headers": []},
        receive,
        send,
    )
    assert captured == ["/api/v1/mcp/"]


@pytest.mark.asyncio
async def test_oauth_stubs_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    """/oauth/authorize and /oauth/token are no longer registered — clients must use Clerk."""
    reset_mcp_runtime_for_tests()
    s = _minimal_settings_with_clerk(monkeypatch, mcp_enabled=True)
    app = create_app(_register_settings=s)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        assert (await client.get("/oauth/authorize")).status_code == 404
        assert (await client.post("/oauth/token")).status_code == 404


@pytest.mark.asyncio
async def test_mcp_asgi_strip_last_event_id_for_inspector_reconnect() -> None:
    """MCP Inspector sends Last-Event-ID on SSE reconnect; strip it so SDK does not 500."""
    captured: dict[str, object] = {}

    async def inner_app(scope, receive, send):
        captured["headers"] = list(scope.get("headers") or ())

    scope = {
        "type": "http",
        "headers": [
            (b"last-event-id", b"stale-id"),
            (b"host", b"test"),
        ],
        "asgi": {"version": "3.0"},
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        pass

    await StripLastEventIdMiddleware(inner_app)(scope, receive, send)
    hdrs = captured["headers"]
    assert isinstance(hdrs, list)
    assert not any(name.lower() == b"last-event-id" for name, _ in hdrs)
    assert any(name.lower() == b"host" for name, _ in hdrs)
