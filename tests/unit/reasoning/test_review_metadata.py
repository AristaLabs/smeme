from __future__ import annotations

from datetime import date

from smeme.decision_tree.models import DTGraph, DTGraphMetadata
from smeme.reasoning.review_metadata import decision_tree_review_warnings


def test_review_warning_only_after_deadline() -> None:
    graph = DTGraph(
        metadata=DTGraphMetadata(
            title="Current rules",
            effective_date=date(2026, 1, 1),
            review_by=date(2026, 7, 1),
        )
    )
    assert decision_tree_review_warnings(graph, today=date(2026, 7, 1)) == []

    warnings = decision_tree_review_warnings(graph, today=date(2026, 7, 2))
    assert warnings == [
        {
            "code": "review_overdue",
            "message": (
                "This decision tree was due for review on 2026-07-01. "
                "Its rules may be stale; ask the owner to review and redeploy it."
            ),
            "review_by": "2026-07-01",
            "remedy": ("Review the source authorities, update the tree if needed, and redeploy."),
            "effective_date": "2026-01-01",
        }
    ]
