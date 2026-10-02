"""Import one v2 decision-tree export as a new Hidden draft.

This is a copy of the procedure. It does not Deploy, List, or carry the source
account's id, timestamps, sample identity, or compiled artifact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, User
from smeme.decision_tree.models import DTGraph, DTGraphMetadata

IMPORT_BODY_MAX_BYTES = 600 * 1024
IMPORT_GRAPH_MAX_UTF8_BYTES = 512 * 1024
IMPORT_MAX_NODES = 2_000
IMPORT_MAX_EDGES = 4_000
IMPORT_MAX_STRING_CHARS = 8_192
IMPORT_FILENAME_MAX_CHARS = 200
IMPORT_TITLE_MAX_CHARS = 200
IMPORT_EXPORT_VERSION = "2"

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


class ImportCopyError(Exception):
    """User-facing failure while copying an export into a new draft."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def import_banner_visible(*, imported_at: datetime | None, current_artifact_id: Any) -> bool:
    """Show the review banner until the imported draft is Deployed."""
    return imported_at is not None and current_artifact_id is None


def sanitize_import_filename(raw: str | None) -> str:
    """Keep a display basename. Drop directories and cap the length."""
    text = (raw or "").replace("\\", "/").replace("\x00", "").strip()
    name = PurePosixPath(text).name.strip() if text else ""
    if not name or name in {".", ".."}:
        name = "import.smeme.json"
    if len(name) > IMPORT_FILENAME_MAX_CHARS:
        name = name[:IMPORT_FILENAME_MAX_CHARS]
    return name


def _walk_strings(value: Any) -> list[str]:
    found: list[str] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            found.append(current)
        elif isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _authority_url_error(graph: dict[str, Any]) -> str | None:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        authorities = data.get("authorities")
        if not isinstance(authorities, list):
            continue
        for authority in authorities:
            if not isinstance(authority, dict) or "url" not in authority:
                continue
            url = authority.get("url")
            if url is None or url == "":
                continue
            if not isinstance(url, str):
                return "An authority link must be an http or https URL."
            parts = urlsplit(url.strip())
            if parts.scheme not in _ALLOWED_URL_SCHEMES or not parts.netloc:
                return "An authority link must be an http or https URL."
    return None


def _sync_title(graph: DTGraph, title: str) -> DTGraph:
    meta = graph.metadata
    if meta is None:
        return graph.model_copy(update={"metadata": DTGraphMetadata(title=title)})
    if meta.title == title:
        return graph
    return graph.model_copy(update={"metadata": meta.model_copy(update={"title": title})})


def parse_import_export(raw: bytes) -> tuple[DTGraph, str]:
    """Validate export bytes into a graph and title. Does not touch the database."""
    if len(raw) > IMPORT_BODY_MAX_BYTES:
        raise ImportCopyError("payload_too_large", "This file is larger than 600 KiB.")

    try:
        payload = json.loads(raw)
    except RecursionError as exc:
        raise ImportCopyError(
            "invalid_graph",
            "This file is nested too deeply to import.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise ImportCopyError("invalid_graph", "This file is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise ImportCopyError(
            "invalid_envelope",
            "This file is not a SMEme export. Download a decision tree as .smeme.json and import that file.",
        )

    if "smeme_export_version" not in payload:
        raise ImportCopyError(
            "invalid_envelope",
            "This file is not a SMEme export. Download a decision tree as .smeme.json and import that file.",
        )
    if payload.get("smeme_export_version") != IMPORT_EXPORT_VERSION:
        raise ImportCopyError(
            "unsupported_export_version",
            "This export version is not supported. Import accepts version 2.",
        )

    decision_tree = payload.get("decision_tree")
    if not isinstance(decision_tree, dict):
        raise ImportCopyError(
            "invalid_envelope",
            "This file is not a SMEme export. Download a decision tree as .smeme.json and import that file.",
        )
    graph = decision_tree.get("graph")
    if not isinstance(graph, dict):
        raise ImportCopyError(
            "invalid_envelope",
            "This file is not a SMEme export. Download a decision tree as .smeme.json and import that file.",
        )

    title = decision_tree.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ImportCopyError("invalid_graph", "Decision tree title is required.")
    title = title.strip()
    if len(title) > IMPORT_TITLE_MAX_CHARS:
        title = title[:IMPORT_TITLE_MAX_CHARS]

    encoded = json.dumps(graph, ensure_ascii=False).encode("utf-8")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    node_count = len(nodes) if isinstance(nodes, list) else 0
    edge_count = len(edges) if isinstance(edges, list) else 0
    too_big = (
        len(encoded) > IMPORT_GRAPH_MAX_UTF8_BYTES
        or node_count > IMPORT_MAX_NODES
        or edge_count > IMPORT_MAX_EDGES
        or any(len(item) > IMPORT_MAX_STRING_CHARS for item in _walk_strings(graph))
    )
    if too_big:
        raise ImportCopyError("graph_too_large", "This decision tree is too large to import.")

    url_error = _authority_url_error(graph)
    if url_error is not None:
        raise ImportCopyError("invalid_graph", url_error)

    try:
        parsed = DTGraph.model_validate(graph)
    except ValidationError as exc:
        detail = exc.errors()[0].get("msg", "invalid") if exc.errors() else "invalid"
        raise ImportCopyError(
            "invalid_graph",
            f"This decision tree does not match the export schema. {detail}",
        ) from exc

    return _sync_title(parsed, title), title


async def import_decision_tree_export(
    db: AsyncSession,
    user: User,
    raw_bytes: bytes,
    filename: str | None,
) -> DecisionTree:
    """Insert a Hidden draft copied from a v2 export. This function commits the new draft itself."""
    import asyncio

    from smeme.billing.access_policy import is_workflow_pick_required
    from smeme.billing.quota import reserve_decision_tree_slot
    from smeme.decision_tree.helpers.validation import validate_graph_for_editing

    graph, title = parse_import_export(raw_bytes)
    validation = await asyncio.to_thread(validate_graph_for_editing, graph)
    if not validation["is_valid"]:
        detail = (
            validation["errors"][0] if validation["errors"] else "The decision tree is not valid."
        )
        raise ImportCopyError("invalid_graph", str(detail))

    if is_workflow_pick_required(user):
        raise ImportCopyError(
            "account_downgrade_pending",
            "Your Pro subscription ended with multiple decision trees. "
            "Choose which decision tree to keep live before importing another.",
        )

    quota = await reserve_decision_tree_slot(db, user)
    if not quota.allowed:
        raise ImportCopyError("quota_exceeded", quota.message or "Decision-tree limit reached.")

    decision_tree = DecisionTree(
        title=title,
        author_id=user.id,
        graph_data=graph.model_dump(mode="json"),
        sample_key=None,
        mcp_discoverable=False,
        is_public=False,
        was_ever_public=False,
        version_number=1,
        import_filename=sanitize_import_filename(filename),
        import_export_version=IMPORT_EXPORT_VERSION,
        imported_at=datetime.now(UTC),
    )
    db.add(decision_tree)
    await db.commit()
    await db.refresh(decision_tree)
    return decision_tree
