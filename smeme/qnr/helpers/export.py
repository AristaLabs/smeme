"""Workflow export helpers (Tier 1 per-workflow download)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smeme.core.models import QNR
from smeme.qnr.helpers.db_queries import parse_graph_data

EXPORT_VERSION = "1"

__all__ = ["EXPORT_VERSION", "build_workflow_export", "export_download_filename"]


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_workflow_export(qnr: QNR) -> dict[str, Any]:
    """Build the portable JSON envelope for a single workflow download."""
    graph = parse_graph_data(qnr)
    return {
        "smeme_export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "qnr": {
            "id": str(qnr.id),
            "title": qnr.title,
            "version_number": qnr.version_number,
            "created_at": _iso(qnr.created_at),
            "updated_at": _iso(qnr.updated_at),
            "graph": graph.model_dump(mode="json"),
        },
    }


def export_download_filename(qnr: QNR) -> str:
    """Safe attachment filename from workflow title."""
    safe = "".join(c for c in qnr.title if c.isalnum() or c in (" ", "-", "_")).rstrip()
    safe = safe.replace(" ", "_") or "workflow"
    return f"{safe}.smeme.json"
