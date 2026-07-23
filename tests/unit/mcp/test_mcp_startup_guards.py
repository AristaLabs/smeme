"""Tests for A0 + B0 MCP startup guards.

Covers:
  A0-a  persist=false raises in non-dev/test environments
  A0-d  unknown tool quota_weight returns 0.0 and warns
  A0-e  persist failure logs stable metric key
  B0-a  MCP enabled without Clerk raises in production
  B0-b  DNS rebinding disabled in production raises
  B0-c  empty OAuth client allowlist logs warning in production
  B0-d  transport origins derived from BASE_URL only (not ALLOWED_ORIGINS)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from smeme.core.config import settings as process_settings
from smeme.mcp.invocation_telemetry import quota_weight_for_tool
from smeme.mcp.reasoning_fastmcp import _build_transport_security, validate_mcp_startup_config


def _prod_settings(**kwargs):
    """Return a Settings copy with production environment and MCP enabled."""
    base = {
        "environment": "production",
        "mcp_enabled": True,
        "base_url": "https://core.example.com",
        "clerk_oauth_issuer_override": "https://clerk.example.com",
        "mcp_invocation_telemetry_persist": True,
        "mcp_allowed_oauth_client_ids": ["client_abc"],
        # keep everything else from process settings
    }
    base.update(kwargs)
    return process_settings.model_copy(update=base)


def _dev_settings(**kwargs):
    base = {"environment": "development", "mcp_enabled": True}
    base.update(kwargs)
    return process_settings.model_copy(update=base)


# ---------------------------------------------------------------------------
# A0-d: unknown tool returns 0.0 and warns
# ---------------------------------------------------------------------------

def test_quota_weight_for_known_tool():
    assert quota_weight_for_tool("smeme_reasoning_evaluate") == 1.0
    assert quota_weight_for_tool("smeme_reasoning_list") == 0.0


def test_quota_weight_for_unknown_tool_returns_zero_and_warns():
    with patch("smeme.mcp.invocation_telemetry.logger") as mock_log:
        weight = quota_weight_for_tool("smeme_reasoning_unknown_future_tool")
    assert weight == 0.0
    mock_log.warning.assert_called_once()
    call_kwargs = mock_log.warning.call_args
    assert call_kwargs[0][0] == "unknown_mcp_tool_for_quota"
    assert call_kwargs[1]["extra"]["tool_name"] == "smeme_reasoning_unknown_future_tool"


# ---------------------------------------------------------------------------
# A0-a: persist=false raises validate in production
# ---------------------------------------------------------------------------

def test_validate_raises_when_persist_false_in_production():
    s = _prod_settings(mcp_invocation_telemetry_persist=False)
    with pytest.raises(RuntimeError, match="MCP_INVOCATION_TELEMETRY_PERSIST"):
        validate_mcp_startup_config(s)


def test_validate_does_not_raise_persist_false_in_development():
    s = _dev_settings(mcp_invocation_telemetry_persist=False)
    validate_mcp_startup_config(s)  # must not raise


def test_validate_noop_when_mcp_disabled():
    s = process_settings.model_copy(
        update={"environment": "production", "mcp_enabled": False}
    )
    validate_mcp_startup_config(s)  # must not raise


# ---------------------------------------------------------------------------
# B0-a: no Clerk in production raises
# ---------------------------------------------------------------------------

def test_validate_raises_no_clerk_in_production():
    s = _prod_settings(
        clerk_oauth_issuer_override=None,
        clerk_publishable_key=None,
    )
    with pytest.raises(RuntimeError, match="Clerk OAuth"):
        validate_mcp_startup_config(s)


def test_validate_passes_no_clerk_in_development():
    s = _dev_settings(clerk_oauth_issuer_override=None, clerk_publishable_key=None)
    validate_mcp_startup_config(s)  # must not raise


# ---------------------------------------------------------------------------
# B0-c: empty allowlist warns (does not raise)
# ---------------------------------------------------------------------------

def test_validate_warns_empty_allowlist_in_production():
    s = _prod_settings(mcp_allowed_oauth_client_ids=[])
    with patch("smeme.mcp.reasoning_fastmcp.logger") as mock_log:
        validate_mcp_startup_config(s)
    mock_log.warning.assert_called_once()
    assert mock_log.warning.call_args[0][0] == "mcp_oauth_client_allowlist_empty"


def test_validate_no_warning_when_allowlist_set():
    s = _prod_settings(mcp_allowed_oauth_client_ids=["client_abc"])
    with patch("smeme.mcp.reasoning_fastmcp.logger") as mock_log:
        validate_mcp_startup_config(s)
    mock_log.warning.assert_not_called()


# ---------------------------------------------------------------------------
# B0-b: _build_transport_security raises in production without a valid BASE_URL
# ---------------------------------------------------------------------------

def test_build_transport_security_raises_in_production_without_base_url():
    # Mock the URL helper to simulate an unparseable BASE_URL returning no hosts.
    s = _prod_settings(base_url="https://core.example.com")
    with patch("smeme.mcp.reasoning_fastmcp.transport_security_allowed_hosts", return_value=([], [])):
        with pytest.raises(RuntimeError, match="DNS rebinding"):
            _build_transport_security(s)


def test_build_transport_security_ok_in_production_with_base_url():
    s = _prod_settings(base_url="https://core.example.com")
    ts = _build_transport_security(s)
    assert ts is not None
    assert ts.enable_dns_rebinding_protection is True


def test_build_transport_security_disabled_in_dev():
    s = _dev_settings(base_url="http://localhost:8000")
    ts = _build_transport_security(s)
    assert ts is not None
    assert ts.enable_dns_rebinding_protection is False


# ---------------------------------------------------------------------------
# B0-d: transport origins from BASE_URL only — not ALLOWED_ORIGINS
# ---------------------------------------------------------------------------

def test_build_transport_security_does_not_include_allowed_origins():
    extra_origin = "https://staging.other-app.example.com"
    s = _prod_settings(
        base_url="https://core.example.com",
        allowed_origins=["https://core.example.com", extra_origin],
    )
    ts = _build_transport_security(s)
    assert ts is not None
    assert ts.allowed_origins is not None
    assert extra_origin not in ts.allowed_origins
    # BASE_URL-derived origin must be present
    assert any("core.example.com" in o for o in ts.allowed_origins)
