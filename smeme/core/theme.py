"""UI theme preference (light / dark / system) — cookie-backed."""

from __future__ import annotations

from typing import Any, Literal

from starlette.requests import Request

ThemePreference = Literal["light", "dark", "system"]

THEME_COOKIE = "smeme_theme"
THEME_COOKIE_MAX_AGE = 365 * 24 * 3600
_THEME_VALUES: frozenset[str] = frozenset({"light", "dark", "system"})
_DEFAULT_PREFERENCE: ThemePreference = "system"
_THEME_CYCLE: tuple[ThemePreference, ...] = ("light", "dark", "system")

# Dark-mode logo under ``smeme/static/``. Rollback: ``smeme_logo_v15_dark.svg``.
DARK_LOGO_FILENAME = "smeme_logo_v15_dark_twotone.svg"


def dark_logo_src() -> str:
    """Static URL for the active dark logo SVG."""
    return f"/static/{DARK_LOGO_FILENAME}"


def resolve_theme_preference(cookie_value: str | None) -> ThemePreference:
    """Parse persisted theme from cookie; invalid or missing → ``system``."""
    if not cookie_value:
        return _DEFAULT_PREFERENCE
    pref = cookie_value.strip().lower()
    if pref not in _THEME_VALUES:
        return _DEFAULT_PREFERENCE
    return pref  # type: ignore[return-value]


def next_theme_preference(current: ThemePreference) -> ThemePreference:
    """Cycle ``light`` → ``dark`` → ``system`` → ``light``."""
    try:
        idx = _THEME_CYCLE.index(current)
    except ValueError:
        idx = _THEME_CYCLE.index(_DEFAULT_PREFERENCE)
    return _THEME_CYCLE[(idx + 1) % len(_THEME_CYCLE)]


def system_prefers_dark_from_request(request: Request | None) -> bool | None:
    """Parse ``Sec-CH-Prefers-Color-Scheme`` when the client sends it."""
    if request is None:
        return None
    hint = request.headers.get("sec-ch-prefers-color-scheme", "").strip().lower()
    if hint == "dark":
        return True
    if hint == "light":
        return False
    return None


def is_dark_theme(
    preference: ThemePreference,
    *,
    system_prefers_dark: bool | None,
) -> bool:
    """Whether the effective theme is dark for SSR or tests."""
    if preference == "dark":
        return True
    if preference == "light":
        return False
    if system_prefers_dark is None:
        return False
    return system_prefers_dark


def theme_template_context(request: Request | None) -> dict[str, Any]:
    """Template vars for ``base.html`` SSR (``theme_preference``, ``theme_dark``)."""
    preference = resolve_theme_preference(
        request.cookies.get(THEME_COOKIE) if request is not None else None
    )
    system_dark = system_prefers_dark_from_request(request)
    return {
        "theme_preference": preference,
        "theme_dark": is_dark_theme(preference, system_prefers_dark=system_dark),
    }


def theme_context_processor(request: Request) -> dict[str, Any]:
    """Starlette ``Jinja2Templates`` context processor."""
    return theme_template_context(request)
