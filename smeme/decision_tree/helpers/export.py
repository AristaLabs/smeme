"""Workflow export helpers (Tier 1 per-workflow download)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smeme.core.models import DecisionTree
from smeme.decision_tree.helpers.db_queries import parse_graph_data

EXPORT_VERSION = "2"

__all__ = ["EXPORT_VERSION", "build_decision_tree_export", "export_download_filename"]


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_decision_tree_export(decision_tree: DecisionTree) -> dict[str, Any]:
    """Build the portable JSON envelope for a single workflow download."""
    graph = parse_graph_data(decision_tree)
    return {
        "smeme_export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "decision_tree": {
            "id": str(decision_tree.id),
            "title": decision_tree.title,
            "version_number": decision_tree.version_number,
            "created_at": _iso(decision_tree.created_at),
            "updated_at": _iso(decision_tree.updated_at),
            "graph": graph.model_dump(mode="json"),
        },
    }


def export_download_filename(decision_tree: DecisionTree) -> str:
    """Safe attachment filename from workflow title."""
    safe = "".join(c for c in decision_tree.title if c.isalnum() or c in (" ", "-", "_")).rstrip()
    safe = safe.replace(" ", "_") or "workflow"
    return f"{safe}.smeme.json"
