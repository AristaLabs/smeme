"""CSP policy includes Clerk Turnstile when browser sync is enabled."""

from __future__ import annotations

from smeme.core.config import settings as process_settings
from smeme.core.middleware import _csp_policy_for_request


def test_csp_includes_turnstile_when_clerk_browser_sync(monkeypatch) -> None:
    monkeypatch.setattr(
        process_settings,
        "clerk_secret_key",
        "sk_test_x",
        raising=False,
    )
    monkeypatch.setattr(
        process_settings,
        "clerk_sign_in_url",
        "https://clerk.example.com/sign-in",
        raising=False,
    )
    monkeypatch.setattr(
        process_settings,
        "clerk_publishable_key",
        "pk_test_Y2xlcmsuZXhhbXBsZS5jb20k",
        raising=False,
    )
    policy = _csp_policy_for_request()
    assert "https://challenges.cloudflare.com" in policy
    assert "script-src" in policy
    assert "frame-src" in policy


def test_csp_includes_plausible_when_analytics_enabled(monkeypatch) -> None:
    monkeypatch.setattr(process_settings, "plausible_domain", "smeme.ai", raising=False)
    policy = _csp_policy_for_request()
    assert "https://plausible.io" in policy
    assert "script-src" in policy
    assert "connect-src" in policy


def test_csp_omits_plausible_when_analytics_disabled(monkeypatch) -> None:
    monkeypatch.setattr(process_settings, "plausible_domain", None, raising=False)
    monkeypatch.setattr(
        process_settings,
        "plausible_script_url",
        "https://plausible.io/js/script.js",
        raising=False,
    )
    policy = _csp_policy_for_request()
    assert "https://plausible.io" not in policy
