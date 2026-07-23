"""Shared access rules for MCP tool listing and evaluation (MCP transport).

``mcp_discoverable`` is an owner opt-in gate: both ``smeme_reasoning_list`` and
``smeme_reasoning_evaluate`` must enforce it so hidden UUIDs are not callable.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select

from smeme.core.models import DecisionTree


def select_decision_trees_for_assistant_tools_list(author_id: UUID) -> Select:
    """SQLAlchemy select for DecisionTree rows exposed by ``smeme_reasoning_list``."""
    return (
        select(DecisionTree)
        .where(DecisionTree.author_id == author_id)
        .where(DecisionTree.reasoning_status == "compiled")
        .where(DecisionTree.is_current.is_(True))
        .where(DecisionTree.mcp_discoverable.is_(True))
        .order_by(DecisionTree.updated_at.desc())
    )


def assistant_tools_discoverability_violation(decision_tree: DecisionTree) -> tuple[str, str] | None:
    """If *decision_tree* must not be used for MCP tool evaluation, return (code, message)."""
    if not decision_tree.mcp_discoverable:
        return (
            "not_discoverable",
            "This workflow is hidden from MCP tools. "
            "In the SMEme web app, set the workflow to **Listed** in the Listed column on your dashboard "
            "(/decision-trees/dashboard#mcp-listed), then try again.",
        )
    return None
