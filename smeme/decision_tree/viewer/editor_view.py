"""DecisionTree editor main-pane view (graph / checklist / lexicon / tools) — server-resolved."""

from __future__ import annotations

from typing import Literal

EditorView = Literal["graph", "checklist", "lexicon", "tools"]

EDITOR_VIEW_COOKIE = "smeme_editor_view"
EDITOR_SIDEBAR_WIDTH_COOKIE = "smeme_editor_sidebar_width"
_EDITOR_VIEWS: frozenset[str] = frozenset({"graph", "checklist", "lexicon", "tools"})
_SIDEBAR_MIN_WIDTH = 280
_SIDEBAR_MAX_WIDTH = 800
_SIDEBAR_DEFAULT_WIDTH = 384


def resolve_editor_sidebar_width(cookie_value: str | None) -> int:
    """Parse persisted sidebar width from cookie (px)."""
    if not cookie_value:
        return _SIDEBAR_DEFAULT_WIDTH
    try:
        width = int(cookie_value.strip())
    except ValueError:
        return _SIDEBAR_DEFAULT_WIDTH
    return max(_SIDEBAR_MIN_WIDTH, min(_SIDEBAR_MAX_WIDTH, width))


def resolve_editor_view(
    *,
    query_view: str | None,
    cookie_view: str | None,
    allow_lexicon: bool,
    allow_tools: bool = True,
    default: EditorView = "graph",
) -> EditorView:
    """Pick editor pane from ``?view=`` (tab click), else cookie, else default."""
    for candidate in (query_view, cookie_view):
        if not candidate:
            continue
        view = candidate.strip().lower()
        if view not in _EDITOR_VIEWS:
            continue
        if view == "lexicon" and not allow_lexicon:
            continue
        if view == "tools" and not allow_tools:
            continue
        return view  # type: ignore[return-value]
    return default


def should_persist_editor_view(query_view: str | None) -> bool:
    """True when the user explicitly chose a tab via ``?view=``."""
    if not query_view:
        return False
    return query_view.strip().lower() in _EDITOR_VIEWS
