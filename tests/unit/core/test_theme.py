"""Unit tests for theme preference resolution."""

from starlette.requests import Request

from smeme.core.theme import (
    DARK_LOGO_FILENAME,
    dark_logo_src,
    is_dark_theme,
    next_theme_preference,
    resolve_theme_preference,
    system_prefers_dark_from_request,
    theme_template_context,
)


def _request(*, cookie: str | None = None, color_hint: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if color_hint is not None:
        headers.append((b"sec-ch-prefers-color-scheme", color_hint.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
    }
    req = Request(scope)
    if cookie is not None:
        req._cookies = {"smeme_theme": cookie}  # noqa: SLF001
    return req


def test_resolve_defaults_to_system() -> None:
    assert resolve_theme_preference(None) == "system"
    assert resolve_theme_preference("") == "system"
    assert resolve_theme_preference("  ") == "system"


def test_resolve_accepts_valid_values() -> None:
    assert resolve_theme_preference("light") == "light"
    assert resolve_theme_preference("DARK") == "dark"
    assert resolve_theme_preference(" system ") == "system"


def test_resolve_rejects_invalid() -> None:
    assert resolve_theme_preference("nope") == "system"
    assert resolve_theme_preference("auto") == "system"


def test_next_theme_preference_cycles() -> None:
    assert next_theme_preference("light") == "dark"
    assert next_theme_preference("dark") == "system"
    assert next_theme_preference("system") == "light"


def test_is_dark_explicit_preferences() -> None:
    assert is_dark_theme("dark", system_prefers_dark=False) is True
    assert is_dark_theme("light", system_prefers_dark=True) is False


def test_is_dark_follows_system_when_system() -> None:
    assert is_dark_theme("system", system_prefers_dark=True) is True
    assert is_dark_theme("system", system_prefers_dark=False) is False
    assert is_dark_theme("system", system_prefers_dark=None) is False


def test_system_prefers_dark_from_client_hint() -> None:
    assert system_prefers_dark_from_request(_request(color_hint="dark")) is True
    assert system_prefers_dark_from_request(_request(color_hint="light")) is False
    assert system_prefers_dark_from_request(_request()) is None


def test_theme_template_context_from_cookie_and_hint() -> None:
    ctx = theme_template_context(_request(cookie="dark"))
    assert ctx == {"theme_preference": "dark", "theme_dark": True}

    ctx = theme_template_context(_request(cookie="system", color_hint="dark"))
    assert ctx == {"theme_preference": "system", "theme_dark": True}

    ctx = theme_template_context(_request(cookie="system"))
    assert ctx == {"theme_preference": "system", "theme_dark": False}


def test_dark_logo_src_uses_active_filename() -> None:
    assert dark_logo_src() == f"/static/{DARK_LOGO_FILENAME}"
    assert DARK_LOGO_FILENAME == "smeme_logo_v15_dark_twotone.svg"
