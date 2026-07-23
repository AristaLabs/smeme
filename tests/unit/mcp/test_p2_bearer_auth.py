"""DR-3 P2: MCP Bearer JWT verification (smeme/mcp/bearer_auth.py)."""

from __future__ import annotations

import json
import time as time_module
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from smeme.mcp.bearer_auth import (
    MCPAuthError,
    _JwksCache,
    auth_error_tool_json,
    decode_clerk_oauth_access_token,
    get_mcp_user,
    oauth_client_id_from_clerk_access_payload,
    unlinked_account_mcp_auth_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(auth_header: str | None = None) -> MagicMock:
    """Build a mock Starlette Request with the given Authorization header value."""
    req = MagicMock()
    headers: dict[str, str] = {}
    if auth_header is not None:
        headers["authorization"] = auth_header
    req.headers = headers
    return req


def _make_db(user: MagicMock | None = None) -> AsyncMock:
    """Build a mock AsyncSession that returns ``user`` on execute().scalar_one_or_none()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Request / header guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_request_raises():
    with pytest.raises(MCPAuthError, match="No HTTP request"):
        await get_mcp_user(None, AsyncMock())


@pytest.mark.asyncio
async def test_missing_authorization_header_raises():
    with pytest.raises(MCPAuthError, match="Bearer"):
        await get_mcp_user(_make_request(), AsyncMock())


@pytest.mark.asyncio
async def test_non_bearer_scheme_raises():
    with pytest.raises(MCPAuthError, match="Bearer"):
        await get_mcp_user(_make_request("Basic dXNlcjpwYXNz"), AsyncMock())


@pytest.mark.asyncio
async def test_empty_bearer_token_raises():
    with pytest.raises(MCPAuthError, match="Empty Bearer"):
        await get_mcp_user(_make_request("Bearer   "), AsyncMock())


# ---------------------------------------------------------------------------
# Clerk configuration guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_when_clerk_not_configured(monkeypatch):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", MagicMock(clerk_oauth_issuer=None))
    with pytest.raises(MCPAuthError, match="not configured"):
        await get_mcp_user(_make_request("Bearer some.jwt.token"), AsyncMock())


# ---------------------------------------------------------------------------
# JWT parsing failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_jwt_header_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    with pytest.raises(MCPAuthError, match="Malformed JWT"):
        await get_mcp_user(_make_request("Bearer not.a.valid.jwt.here"), AsyncMock())


@pytest.mark.asyncio
async def test_expired_token_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    fake_key = MagicMock()
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            side_effect=jwt.ExpiredSignatureError("token expired"),
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=fake_key)
        with pytest.raises(MCPAuthError, match="expired"):
            await get_mcp_user(_make_request("Bearer tok.en.here"), AsyncMock())


@pytest.mark.asyncio
async def test_wrong_issuer_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    fake_key = MagicMock()
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            side_effect=jwt.InvalidIssuerError("bad issuer"),
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=fake_key)
        with pytest.raises(MCPAuthError, match="issuer"):
            await get_mcp_user(_make_request("Bearer tok.en.here"), AsyncMock())


# ---------------------------------------------------------------------------
# User-lookup failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_sub_claim_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch("smeme.mcp.bearer_auth.jwt.decode", return_value={"iat": 1, "exp": 9999999999}),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError, match="sub"):
            await get_mcp_user(_make_request("Bearer tok.en.here"), AsyncMock())


@pytest.mark.asyncio
async def test_user_not_in_db_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_abc", "iat": 1, "exp": 9999999999},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        db = _make_db(user=None)
        with pytest.raises(MCPAuthError, match="No SMEme account is linked"):
            await get_mcp_user(_make_request("Bearer tok.en.here"), db)


def test_unlinked_account_auth_error_includes_signup_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(effective_base_url="https://core.example.com"),
    )
    exc = unlinked_account_mcp_auth_error()
    payload = json.loads(auth_error_tool_json(exc))
    err = payload["error"]
    assert err["code"] == "auth_error"
    assert err["auth_reason"] == "no_local_user_for_clerk_sub"
    assert err["signup_url"] == "https://core.example.com/auth/register"
    assert err["sign_in_url"] == "https://core.example.com/auth/login"
    assert len(err["next_steps"]) == 4
    assert "core.example.com" in err["message"]
    assert "clerk" not in err["message"].lower()


@pytest.mark.asyncio
async def test_inactive_user_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    inactive_user = MagicMock(is_active=False)
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_abc", "iat": 1, "exp": 9999999999},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError, match="deactivated"):
            await get_mcp_user(_make_request("Bearer tok.en.here"), _make_db(inactive_user))


# ---------------------------------------------------------------------------
# OAuth client binding + audience (P3; empty allowlist = unchanged P2 behavior)
# ---------------------------------------------------------------------------


def test_oauth_client_id_prefers_client_id_over_azp():
    assert (
        oauth_client_id_from_clerk_access_payload(
            {"client_id": "first", "azp": "second"},
        )
        == "first"
    )


def test_oauth_client_id_falls_back_to_azp():
    assert oauth_client_id_from_clerk_access_payload({"azp": "only_azp"}) == "only_azp"


def _binding_settings_mock(**kwargs):
    m = MagicMock(
        clerk_oauth_issuer="https://clerk.example.com",
        mcp_allowed_oauth_client_ids=[],
        mcp_oauth_access_token_audience=None,
        debug=False,
    )
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


@pytest.mark.asyncio
async def test_allowlist_rejects_when_no_client_claim(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_allowed_oauth_client_ids=["trusted"]),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "u1", "iat": 1, "exp": 9999999999},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError, match="client_id or azp") as excinfo:
            await decode_clerk_oauth_access_token("tok.en.here")
    assert excinfo.value.reason_code == "unknown_oauth_client"


@pytest.mark.asyncio
async def test_allowlist_rejects_wrong_client(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_allowed_oauth_client_ids=["trusted"]),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={
                "sub": "u1",
                "iat": 1,
                "exp": 9999999999,
                "client_id": "rogue",
            },
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError, match="not allowlisted") as excinfo:
            await decode_clerk_oauth_access_token("tok.en.here")
    assert excinfo.value.reason_code == "unknown_oauth_client"


@pytest.mark.asyncio
async def test_allowlist_accepts_matching_client_id(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_allowed_oauth_client_ids=["trusted", "other"]),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={
                "sub": "u1",
                "iat": 1,
                "exp": 9999999999,
                "client_id": "trusted",
            },
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        payload = await decode_clerk_oauth_access_token("tok.en.here")
    assert payload["sub"] == "u1"


@pytest.mark.asyncio
async def test_allowlist_accepts_numeric_client_id(monkeypatch):
    """JWT may carry ``client_id`` as a JSON number; it must still match the allowlist string."""
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_allowed_oauth_client_ids=["7000123456789"]),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={
                "sub": "u1",
                "iat": 1,
                "exp": 9999999999,
                "client_id": 7000123456789,
            },
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        payload = await decode_clerk_oauth_access_token("tok.en.here")
    assert payload["client_id"] == 7000123456789


@pytest.mark.asyncio
async def test_allowlist_accepts_azp_only(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_allowed_oauth_client_ids=["from_azp"]),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={
                "sub": "u1",
                "iat": 1,
                "exp": 9999999999,
                "azp": "from_azp",
            },
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        payload = await decode_clerk_oauth_access_token("tok.en.here")
    assert payload["azp"] == "from_azp"


@pytest.mark.asyncio
async def test_audience_mismatch_raises(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(
            mcp_oauth_access_token_audience="https://api.example.com/api/v1/mcp",
        ),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={
                "sub": "u1",
                "iat": 1,
                "exp": 9999999999,
                "aud": "wrong",
            },
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError, match="audience") as excinfo:
            await decode_clerk_oauth_access_token("tok.en.here")
    assert excinfo.value.reason_code == "audience_mismatch"


@pytest.mark.asyncio
async def test_audience_accepts_matching_string_claim(monkeypatch):
    aud = "https://api.example.com/api/v1/mcp"
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_oauth_access_token_audience=aud),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "u1", "iat": 1, "exp": 9999999999, "aud": aud},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        payload = await decode_clerk_oauth_access_token("tok.en.here")
    assert payload["aud"] == aud


@pytest.mark.asyncio
async def test_audience_accepts_matching_value_in_aud_array(monkeypatch):
    aud = "https://api.example.com/api/v1/mcp"
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _binding_settings_mock(mcp_oauth_access_token_audience=aud),
    )
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "u1", "iat": 1, "exp": 9999999999, "aud": ["other", aud]},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        payload = await decode_clerk_oauth_access_token("tok.en.here")
    assert aud in payload["aud"]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_token_returns_user(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(clerk_oauth_issuer="https://clerk.example.com"),
    )
    active_user = MagicMock(is_active=True)
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_xyz", "iat": 1, "exp": 9999999999},
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        user = await get_mcp_user(_make_request("Bearer real.jwt.token"), _make_db(active_user))
    assert user is active_user


# ---------------------------------------------------------------------------
# JWKS cache unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwks_cache_refresh_on_stale():
    """Cache calls _refresh when TTL has expired."""
    cache = _JwksCache(ttl=0)  # TTL=0 means always stale

    rsa_key_mock = MagicMock()

    async def fake_refresh(url: str) -> None:
        cache._keys = {"kid1": rsa_key_mock}
        cache._fetched_at = 1e9  # set a non-zero value

    with patch.object(cache, "_refresh", side_effect=fake_refresh) as mock_refresh:
        key = await cache.get_public_key("https://clerk.example.com/.well-known/jwks.json", "kid1")

    assert key is rsa_key_mock
    mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_jwks_cache_kid_not_found_triggers_refresh():
    """Cache re-fetches if the requested kid is absent (key rotation scenario)."""
    cache = _JwksCache(ttl=3600)
    import time as _time

    cache._fetched_at = _time.monotonic()  # mark as fresh
    cache._keys = {"old_kid": MagicMock()}

    new_key = MagicMock()

    async def rotate_refresh(url: str) -> None:
        cache._keys = {"old_kid": MagicMock(), "new_kid": new_key}
        cache._fetched_at = _time.monotonic()

    with patch.object(cache, "_refresh", side_effect=rotate_refresh):
        key = await cache.get_public_key("https://clerk.example.com/.well-known/jwks.json", "new_kid")

    assert key is new_key


@pytest.mark.asyncio
async def test_jwks_cache_invalidate_forces_refresh():
    """invalidate() resets the cache so the next call always re-fetches."""
    cache = _JwksCache(ttl=3600)
    import time as _time

    cache._fetched_at = _time.monotonic()
    cache._keys = {"k": MagicMock()}

    cache.invalidate()
    assert cache._fetched_at == 0.0
    assert cache._keys == {}


@pytest.mark.asyncio
async def test_jwks_cache_fetch_failure_raises():
    """Network failure during JWKS fetch propagates as MCPAuthError when no keys cached."""
    cache = _JwksCache(ttl=0)

    async def fail_refresh(url: str) -> None:
        raise MCPAuthError("JWKS fetch failed (https://clerk.example.com/...): Connection refused")

    with patch.object(cache, "_refresh", side_effect=fail_refresh):
        with pytest.raises(MCPAuthError, match="JWKS fetch failed"):
            await cache.get_public_key("https://clerk.example.com/.well-known/jwks.json", None)


@pytest.mark.asyncio
async def test_jwks_cache_ttl_refresh_failure_uses_stale_keys():
    """When TTL refresh fails but in-memory keys exist, return cached key (no outage)."""
    jwks_url = "https://clerk.example.com/.well-known/jwks.json"
    cache = _JwksCache(ttl=300)
    stale_key = MagicMock(name="stale_rsa")
    cache._keys = {"k1": stale_key}
    cache._fetched_at = 1.0

    async def fail_refresh(url: str) -> None:
        raise MCPAuthError("JWKS fetch failed: simulated network error")

    with patch("smeme.mcp.bearer_auth.time.monotonic", return_value=100_000.0):
        with patch.object(cache, "_refresh", side_effect=fail_refresh) as mock_refresh:
            out = await cache.get_public_key(jwks_url, "k1")

    assert out is stale_key
    mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_jwks_cache_kid_rotation_refresh_failure_falls_back_to_cached_key():
    """If rotation re-fetch fails but cache is non-empty, use existing fallback key."""
    jwks_url = "https://clerk.example.com/.well-known/jwks.json"
    cache = _JwksCache(ttl=3600)
    old_key = MagicMock(name="old_rsa")
    cache._keys = {"old_kid": old_key}
    cache._fetched_at = time_module.monotonic()

    async def fail_refresh(url: str) -> None:
        raise MCPAuthError("JWKS fetch failed: rotation fetch down")

    with patch.object(cache, "_refresh", side_effect=fail_refresh) as mock_refresh:
        out = await cache.get_public_key(jwks_url, "unknown_new_kid")

    assert out is old_key
    mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_jwks_cache_rejects_kidless_jwt_when_multiple_keys_cached():
    cache = _JwksCache(ttl=3600)
    cache._keys = {"kid_a": MagicMock(), "kid_b": MagicMock()}
    cache._fetched_at = time_module.monotonic()

    with pytest.raises(MCPAuthError, match="missing kid"):
        await cache.get_public_key("https://clerk.example.com/.well-known/jwks.json", None)
