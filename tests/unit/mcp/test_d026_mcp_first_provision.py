"""D026 MCP-first provision: locked auth_reason codes, gates, rate limit, grandfather."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smeme.auth.clerk_auth import (
    ProvisionFailureReason,
    ProvisionResult,
    assert_provision_gates,
    normalize_clerk_profile,
    resolve_local_user_for_clerk,
)
from smeme.mcp.bearer_auth import (
    MCPAuthError,
    _FirstProvisionRateLimit,
    auth_error_tool_json,
    get_mcp_user,
    provision_gate_mcp_auth_error,
    unlinked_account_mcp_auth_error,
)


def _legal_settings(**overrides):
    base = dict(
        mcp_first_provisioning_enabled=True,
        legal_terms_url="https://www.smeme.ai/legal/terms",
        legal_privacy_url="https://www.smeme.ai/legal/privacy",
        legal_terms_version="2026-07-20",
        legal_privacy_version="2026-07-20",
        clerk_oauth_issuer="https://clerk.example.com",
        effective_base_url="https://www.smeme.ai",
        mcp_first_provision_rate_limit_per_ip_per_minute=10,
        mcp_first_provision_rate_limit_per_sub_per_minute=5,
        mcp_allowed_oauth_client_ids=[],
        mcp_oauth_access_token_audience=None,
        clerk_secret_key="sk_test",
    )
    base.update(overrides)

    def mcp_first_legal_config_complete():
        return bool(
            (base.get("legal_terms_url") or "").strip()
            and (base.get("legal_privacy_url") or "").strip()
            and (base.get("legal_terms_version") or "").strip()
            and (base.get("legal_privacy_version") or "").strip()
        )

    return MagicMock(mcp_first_legal_config_complete=mcp_first_legal_config_complete, **base)


def _clerk_user(*, verified: bool = True, legal_ts: int | None = 1_720_000_000, email="a@example.com"):
    verification = SimpleNamespace(status="verified" if verified else "unverified")
    ea = SimpleNamespace(
        id="idn_1",
        email_address=email,
        verification=verification,
    )
    return SimpleNamespace(
        primary_email_address_id="idn_1",
        email_addresses=[ea],
        legal_accepted_at=legal_ts,
    )


def test_normalize_clerk_profile_verified_and_legal():
    profile = normalize_clerk_profile("user_abc", _clerk_user())
    assert profile.email == "a@example.com"
    assert profile.email_verified is True
    assert profile.legal_accepted_at == datetime.fromtimestamp(1_720_000_000, tz=UTC)


def test_normalize_clerk_profile_legal_accepted_at_milliseconds():
    """Live Clerk Backend may return ms; seconds path must not 500."""
    profile = normalize_clerk_profile(
        "user_abc", _clerk_user(legal_ts=1_720_000_000_000)
    )
    assert profile.legal_accepted_at == datetime.fromtimestamp(1_720_000_000, tz=UTC)


def test_normalize_clerk_profile_legal_accepted_at_invalid_numeric_is_none():
    profile = normalize_clerk_profile("user_abc", _clerk_user(legal_ts=-1))
    assert profile.legal_accepted_at is None


def test_normalize_clerk_profile_unverified():
    profile = normalize_clerk_profile("user_abc", _clerk_user(verified=False))
    assert profile.email_verified is False


def test_normalize_clerk_profile_requires_clerk_primary_email():
    clerk_user = _clerk_user()
    clerk_user.primary_email_address_id = None

    profile = normalize_clerk_profile("user_abc", clerk_user)

    assert profile.email == ""
    assert profile.email_verified is False


def test_assert_gates_locked_reasons(monkeypatch):
    monkeypatch.setattr("smeme.auth.clerk_auth.settings", _legal_settings())
    no_primary = _clerk_user()
    no_primary.primary_email_address_id = None
    with pytest.raises(Exception) as excinfo:
        assert_provision_gates(normalize_clerk_profile("user_abc", no_primary))
    assert excinfo.value.reason == ProvisionFailureReason.PRIMARY_EMAIL_MISSING

    with pytest.raises(Exception) as excinfo:
        assert_provision_gates(
            normalize_clerk_profile("user_abc", _clerk_user(verified=False))
        )
    assert excinfo.value.reason == ProvisionFailureReason.EMAIL_NOT_VERIFIED

    with pytest.raises(Exception) as excinfo:
        assert_provision_gates(
            normalize_clerk_profile("user_abc", _clerk_user(legal_ts=None))
        )
    assert excinfo.value.reason == ProvisionFailureReason.LEGAL_CONSENT_REQUIRED

    monkeypatch.setattr(
        "smeme.auth.clerk_auth.settings",
        _legal_settings(legal_terms_url=""),
    )
    with pytest.raises(Exception) as excinfo:
        assert_provision_gates(normalize_clerk_profile("user_abc", _clerk_user()))
    assert excinfo.value.reason == ProvisionFailureReason.LEGAL_CONFIG_INCOMPLETE


@pytest.mark.parametrize(
    "reason",
    [
        "email_not_verified",
        "primary_email_missing",
        "legal_consent_required",
        "legal_config_incomplete",
        "clerk_lookup_failed",
        "provision_rate_limited",
    ],
)
def test_provision_gate_error_uses_locked_auth_reason(monkeypatch, reason):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", _legal_settings())
    payload = json.loads(auth_error_tool_json(provision_gate_mcp_auth_error(reason)))
    err = payload["error"]
    assert err["code"] == "auth_error"
    assert err["auth_reason"] == reason


def test_legal_config_error_does_not_suggest_web_signup(monkeypatch):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", _legal_settings())

    payload = json.loads(
        auth_error_tool_json(provision_gate_mcp_auth_error("legal_config_incomplete"))
    )

    assert "create an account on the web" not in payload["error"]["message"]
    assert all("web account" not in step for step in payload["error"]["next_steps"])


def test_flag_off_unlinked_error_retained(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        MagicMock(effective_base_url="https://core.example.com"),
    )
    payload = json.loads(auth_error_tool_json(unlinked_account_mcp_auth_error()))
    assert payload["error"]["auth_reason"] == "no_local_user_for_clerk_sub"


def _make_request(auth: str = "Bearer tok.en.here"):
    req = MagicMock()
    req.headers = {"authorization": auth}
    req.client = SimpleNamespace(host="127.0.0.1")
    return req


def _make_db(user=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_get_mcp_user_flag_off_unlinked(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _legal_settings(mcp_first_provisioning_enabled=False),
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
        with pytest.raises(MCPAuthError) as excinfo:
            await get_mcp_user(_make_request(), _make_db(user=None))
        assert excinfo.value.reason_code == "no_local_user_for_clerk_sub"


@pytest.mark.asyncio
async def test_get_mcp_user_provisions_when_gates_pass(monkeypatch):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", _legal_settings())
    _FirstProvisionRateLimit.reset_for_tests()
    user = MagicMock(is_active=True, id="u1")
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_xyz", "iat": 1, "exp": 9999999999},
        ),
        patch(
            "smeme.auth.clerk_auth.resolve_local_user_for_clerk",
            new=AsyncMock(
                return_value=ProvisionResult(user=user, telemetry_event="created")
            ),
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        got = await get_mcp_user(_make_request(), _make_db(user=None))
        assert got is user


@pytest.mark.asyncio
async def test_get_mcp_user_maps_gate_failure(monkeypatch):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", _legal_settings())
    _FirstProvisionRateLimit.reset_for_tests()
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_xyz", "iat": 1, "exp": 9999999999},
        ),
        patch(
            "smeme.auth.clerk_auth.resolve_local_user_for_clerk",
            new=AsyncMock(
                return_value=ProvisionResult(
                    failure_reason=ProvisionFailureReason.EMAIL_NOT_VERIFIED,
                    telemetry_event="blocked",
                )
            ),
        ),
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError) as excinfo:
            await get_mcp_user(_make_request(), _make_db(user=None))
        assert excinfo.value.reason_code == "email_not_verified"


def test_first_provision_rate_limit(monkeypatch):
    monkeypatch.setattr(
        "smeme.mcp.bearer_auth.settings",
        _legal_settings(
            mcp_first_provision_rate_limit_per_ip_per_minute=2,
            mcp_first_provision_rate_limit_per_sub_per_minute=0,
        ),
    )
    _FirstProvisionRateLimit.reset_for_tests()
    assert _FirstProvisionRateLimit.allow(ip="1.2.3.4", sub="user_a") is True
    assert _FirstProvisionRateLimit.allow(ip="1.2.3.4", sub="user_a") is True
    assert _FirstProvisionRateLimit.allow(ip="1.2.3.4", sub="user_a") is False


@pytest.mark.asyncio
async def test_rate_limited_provision_emits_provision_telemetry(monkeypatch):
    monkeypatch.setattr("smeme.mcp.bearer_auth.settings", _legal_settings())
    with (
        patch("smeme.mcp.bearer_auth.jwt.get_unverified_header", return_value={"kid": "k1"}),
        patch("smeme.mcp.bearer_auth._jwks_cache") as mock_cache,
        patch(
            "smeme.mcp.bearer_auth.jwt.decode",
            return_value={"sub": "user_clerk_limited", "iat": 1, "exp": 9999999999},
        ),
        patch("smeme.mcp.bearer_auth._first_provision_limiter.allow", return_value=False),
        patch("smeme.auth.clerk_auth.emit_provision_telemetry") as emit,
    ):
        mock_cache.get_public_key = AsyncMock(return_value=MagicMock())
        with pytest.raises(MCPAuthError) as excinfo:
            await get_mcp_user(_make_request(), _make_db(user=None))

    assert excinfo.value.reason_code == "provision_rate_limited"
    emit.assert_called_once_with(
        "rate_limited",
        clerk_user_id="user_clerk_limited",
        auth_reason="provision_rate_limited",
    )


@pytest.mark.asyncio
async def test_resolve_creates_user_with_audit(monkeypatch):
    monkeypatch.setattr("smeme.auth.clerk_auth.settings", _legal_settings())
    monkeypatch.setattr("smeme.auth.clerk_auth.settings.clerk_secret_key", "sk_test")

    class _FakeUsers:
        async def get_async(self, user_id: str):
            return _clerk_user()

    class _FakeClerk:
        def __init__(self, *args, **kwargs):
            self.users = _FakeUsers()

    db = AsyncMock()
    # first select by clerk_user_id → None; later username checks → None; email link → None
    none_result = MagicMock()
    none_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=none_result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    with patch("smeme.auth.clerk_auth.Clerk", side_effect=_FakeClerk):
        outcome = await resolve_local_user_for_clerk(
            db, "user_clerk_new", enforce_new_user_gates=True
        )
    assert outcome.user is not None
    assert outcome.telemetry_event == "created"
    assert outcome.user.email == "a@example.com"
    assert outcome.user.terms_version == "2026-07-20"
    assert outcome.user.privacy_version == "2026-07-20"
    assert outcome.user.legal_accepted_at is not None


@pytest.mark.asyncio
async def test_resolve_existing_user_no_clerk_fetch(monkeypatch):
    monkeypatch.setattr("smeme.auth.clerk_auth.settings", _legal_settings())
    existing = MagicMock(clerk_user_id="user_old", is_active=True)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    with patch("smeme.auth.clerk_auth.fetch_clerk_profile", new=AsyncMock()) as fetch:
        outcome = await resolve_local_user_for_clerk(
            db, "user_old", enforce_new_user_gates=True
        )
        fetch.assert_not_called()
    assert outcome.user is existing
    assert outcome.telemetry_event == "grandfathered"
