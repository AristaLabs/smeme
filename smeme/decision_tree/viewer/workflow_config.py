"""Shared RunnableConfig helpers for the DecisionTree viewer workflow."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.templates import templates as default_templates
from smeme.decision_tree.viewer.editor_view import (
    EDITOR_SIDEBAR_WIDTH_COOKIE,
    resolve_editor_sidebar_width,
    resolve_editor_view,
)


def build_viewer_workflow_config(
    db: AsyncSession,
    *,
    request: Request | None = None,
    templates=default_templates,
    full_page: bool = False,
    user: Any | None = None,
    editor_view: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build ``config[\"configurable\"]`` for ``viewer_workflow.ainvoke``."""
    allow_lexicon = False
    if editor_view is None:
        query_view = request.query_params.get("view") if request is not None else None
        cookie_view = request.cookies.get("smeme_editor_view") if request is not None else None
        editor_view = resolve_editor_view(
            query_view=query_view,
            cookie_view=cookie_view,
            allow_lexicon=allow_lexicon,
        )

    cfg: dict[str, Any] = {
        "db": db,
        "templates": templates,
        "editor_view": editor_view,
    }
    if request is not None:
        cfg["editor_sidebar_width"] = resolve_editor_sidebar_width(
            request.cookies.get(EDITOR_SIDEBAR_WIDTH_COOKIE)
        )
    if full_page:
        cfg["full_page"] = True
    if user is not None:
        cfg["user"] = user
    if request is not None:
        cfg["request"] = request
    cfg.update(extra)
    return {"configurable": cfg}
