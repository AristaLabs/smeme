"""Unit tests for editor view resolution."""

from smeme.decision_tree.viewer.editor_view import (
    resolve_editor_view,
    should_persist_editor_view,
)


def test_resolve_prefers_query_over_cookie() -> None:
    assert (
        resolve_editor_view(
            query_view="checklist",
            cookie_view="graph",
            allow_lexicon=False,
        )
        == "checklist"
    )


def test_resolve_falls_back_to_cookie() -> None:
    assert (
        resolve_editor_view(
            query_view=None,
            cookie_view="checklist",
            allow_lexicon=False,
        )
        == "checklist"
    )


def test_resolve_sidebar_width_clamps() -> None:
    from smeme.decision_tree.viewer.editor_view import resolve_editor_sidebar_width

    assert resolve_editor_sidebar_width(None) == 384
    assert resolve_editor_sidebar_width("500") == 500
    assert resolve_editor_sidebar_width("9999") == 800
    assert resolve_editor_sidebar_width("bad") == 384


def test_resolve_lexicon_requires_flag() -> None:
    assert (
        resolve_editor_view(
            query_view="lexicon",
            cookie_view=None,
            allow_lexicon=False,
        )
        == "graph"
    )
    assert (
        resolve_editor_view(
            query_view="lexicon",
            cookie_view=None,
            allow_lexicon=True,
        )
        == "lexicon"
    )


def test_resolve_tools_view() -> None:
    assert (
        resolve_editor_view(
            query_view="tools",
            cookie_view="graph",
            allow_lexicon=False,
        )
        == "tools"
    )


def test_resolve_tools_requires_owner() -> None:
    assert (
        resolve_editor_view(
            query_view="tools",
            cookie_view="tools",
            allow_lexicon=False,
            allow_tools=False,
        )
        == "graph"
    )
    assert (
        resolve_editor_view(
            query_view=None,
            cookie_view="tools",
            allow_lexicon=False,
            allow_tools=False,
        )
        == "graph"
    )


def test_should_persist_only_explicit_query() -> None:
    assert should_persist_editor_view("tools") is True
    assert should_persist_editor_view("checklist") is True
    assert should_persist_editor_view(None) is False
    assert should_persist_editor_view("nope") is False
