"""Agent-facing advisories derived from decision-tree review metadata."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from smeme.decision_tree.models import DTGraph


def decision_tree_review_warnings(
    graph: DTGraph,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return stable warnings when the author's review deadline has passed."""
    review_by = graph.metadata.review_by
    current_date = today or datetime.now(UTC).date()
    if review_by is None or review_by >= current_date:
        return []

    warning: dict[str, Any] = {
        "code": "review_overdue",
        "message": (
            f"This decision tree was due for review on {review_by.isoformat()}. "
            "Its rules may be stale; ask the owner to review and redeploy it."
        ),
        "review_by": review_by.isoformat(),
        "remedy": "Review the source authorities, update the tree if needed, and redeploy.",
    }
    if graph.metadata.effective_date is not None:
        warning["effective_date"] = graph.metadata.effective_date.isoformat()
    return [warning]


__all__ = ["decision_tree_review_warnings"]
