"""Shared access rules for MCP tool listing and evaluation (MCP transport).

``mcp_discoverable`` is an owner opt-in gate: both ``smeme_reasoning_list`` and
``smeme_reasoning_evaluate`` must enforce it so hidden UUIDs are not callable.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select

from smeme.core.models import DecisionTree, User


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


def serialize_decision_trees_for_assistant_list(
    user: User,
    rows: Sequence[DecisionTree],
) -> list[dict[str, Any]]:
    """Serialize ORM rows for ``smeme_reasoning_list`` (keeps query results distinct from payload)."""
    from smeme.billing.access_policy import (
        is_decision_tree_live,
        is_workflow_pick_required,
    )

    decision_trees: list[dict[str, Any]] = []
    for q in rows:
        entry: dict[str, Any] = {
            "id": str(q.id),
            "title": q.title,
            "is_public": q.is_public,
            "reasoning_status": q.reasoning_status,
            "intended_audience": q.intended_audience,
            "use_case": q.use_case,
        }
        if is_workflow_pick_required(user) or not is_decision_tree_live(user, q):
            entry["accessible"] = False
            entry["status"] = "account_downgrade_pending"
        decision_trees.append(entry)
    return decision_trees


def assistant_tools_discoverability_violation(
    decision_tree: DecisionTree,
) -> tuple[str, str] | None:
    """If *decision_tree* must not be used for MCP tool evaluation, return (code, message)."""
    if not decision_tree.mcp_discoverable:
        return (
            "not_discoverable",
            "This decision tree is hidden from MCP tools. "
            "In the SMEme web app, set the decision tree to **Listed** in the Listed column on your dashboard "
            "(/decision-trees/dashboard#mcp-listed), then try again.",
        )
    return None
