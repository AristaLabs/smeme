"""CSP policy: Clerk Turnstile inclusion, self-hosted script-src (M-04)."""

from __future__ import annotations

from pathlib import Path

from smeme.core.config import settings as process_settings
from smeme.core.middleware import _csp_policy_for_request

BASE_HTML = (
    Path(__file__).resolve().parents[2] / "smeme" / "templates" / "layouts" / "base.html"
).read_text()


def _script_src_directive(policy: str) -> str:
    for directive in policy.split("; "):
        if directive.startswith("script-src "):
            return directive
    msg = f"no script-src directive in policy: {policy!r}"
    raise AssertionError(msg)


def test_csp_script_src_has_no_unpkg_or_tailwind_cdn() -> None:
    policy = _csp_policy_for_request()
    assert "unpkg.com" not in policy
    assert "cdn.tailwindcss.com" not in policy


def test_csp_script_src_has_no_unsafe_inline() -> None:
    """HTMX is self-hosted and Core templates have zero executable inline
    <script> tags (see tests/unit/test_static_vendor_assets.py and
    test_base_html_has_no_unpkg below) — script-src no longer needs
    'unsafe-inline'."""
    script_src = _script_src_directive(_csp_policy_for_request())
    assert "'unsafe-inline'" not in script_src


def test_base_html_does_not_load_htmx_from_unpkg() -> None:
    assert "unpkg.com" not in BASE_HTML
    assert "cdn.tailwindcss.com" not in BASE_HTML
    assert "/static/js/vendor/htmx-2.0.4.min.js" in BASE_HTML
    assert "/static/js/vendor/htmx-ext-json-enc-2.0.1.js" in BASE_HTML


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
    monkeypatch.setattr(process_settings, "plausible_domain", "core.example.com", raising=False)
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
