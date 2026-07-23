"""Parse / validate / create-draft helpers for MCP authoring graph tools.

Accepts a raw ``DTGraph`` JSON object or a ``.smeme.json`` export envelope
(``smeme_export_version`` + ``decision_tree.graph``). Draft accept uses
``validate_graph_for_editing`` — not publication / Deploy readiness.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, User
from smeme.mcp.tool_contract import tool_error_json
from smeme.decision_tree.helpers.validation import ValidationResult, validate_graph_for_editing
from smeme.decision_tree.models import DTGraph

AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES = 512 * 1024

__all__ = [
    "AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES",
    "create_draft_from_graph",
    "editor_url_for_decision_tree",
    "extract_graph_dict",
    "parse_authoring_graph_json",
    "validation_payload",
]


def extract_graph_dict(payload: Any) -> dict[str, Any] | str:
    """Normalize agent input to a graph dict, or return tool-error JSON."""
    if isinstance(payload, str):
        raw = payload.strip()
        if not raw:
            return tool_error_json(
                "invalid_graph",
                "dt_graph_json is empty. Pass a decision-tree graph object "
                "(nodes, edges, metadata) or a SMEme export envelope.",
            )
        if len(raw.encode("utf-8")) > AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES:
            return tool_error_json(
                "payload_too_large",
                f"dt_graph_json exceeds {AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES} bytes. "
                "Reduce the graph size and try again.",
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return tool_error_json(
                "invalid_graph",
                f"dt_graph_json is not valid JSON: {exc.msg}",
            )

    if not isinstance(payload, dict):
        return tool_error_json(
            "invalid_graph",
            "dt_graph_json must be a JSON object (graph or SMEme export envelope).",
        )

    if "nodes" in payload and "edges" in payload:
        return payload

    if "smeme_export_version" in payload:
        decision_tree = payload.get("decision_tree")
        if not isinstance(decision_tree, dict):
            return tool_error_json(
                "invalid_graph",
                "Export envelope is missing decision_tree. Pass a .smeme.json export or a raw graph.",
            )
        graph = decision_tree.get("graph")
        if not isinstance(graph, dict):
            return tool_error_json(
                "invalid_graph",
                "Export envelope is missing decision_tree.graph.",
            )
        return graph

    nested = payload.get("graph")
    if isinstance(nested, dict) and "nodes" in nested and "edges" in nested:
        return nested

    return tool_error_json(
        "invalid_graph",
        "Unrecognized graph shape. Expected {nodes, edges, metadata} "
        "or a SMEme export with decision_tree.graph.",
    )


def parse_authoring_graph_json(dt_graph_json: str) -> DTGraph | str:
    """Parse agent JSON into ``DTGraph``, or return tool-error JSON."""
    graph_dict = extract_graph_dict(dt_graph_json)
    if isinstance(graph_dict, str):
        return graph_dict
    try:
        return DTGraph.model_validate(graph_dict)
    except ValidationError as exc:
        # Keep message short — full Pydantic dump is noisy for agents.
        first = exc.errors()[0] if exc.errors() else None
        if first:
            loc = ".".join(str(p) for p in first.get("loc", ()))
            detail = first.get("msg", "validation failed")
            msg = (
                f"Graph schema invalid at {loc}: {detail}"
                if loc
                else f"Graph schema invalid: {detail}"
            )
        else:
            msg = "Graph schema invalid."
        return tool_error_json("invalid_graph", msg)


def validation_payload(graph: DTGraph, result: ValidationResult) -> dict[str, Any]:
    """Structured validate response body (no watermark — caller adds via ``_tool_json``)."""
    suggestions = result.get("suggestions") or {}
    return {
        "is_valid": result["is_valid"],
        "errors": list(result["errors"]),
        "warnings": list(result["warnings"]),
        "suggestions": suggestions,
        "title": graph.metadata.title if graph.metadata else None,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "question_count": sum(1 for n in graph.nodes if n.type == "question"),
        "conclusion_count": sum(1 for n in graph.nodes if n.type == "conclusion"),
        "draft_ready": result["is_valid"],
        "deploy_ready": False,
        "note": (
            "draft_ready means edit-valid (safe to create a dashboard draft). "
            "Deploy still requires the SMEme editor Deploy flow."
            if result["is_valid"]
            else "Fix errors, then call smeme_authoring_validate_graph again before create_draft."
        ),
    }


async def create_draft_from_graph(
    db: AsyncSession,
    *,
    user: User,
    graph: DTGraph,
    title_override: str | None = None,
) -> tuple[DecisionTree, ValidationResult] | str:
    """Insert a draft DecisionTree when edit-valid; enforce active-workflow quota.

    Returns ``(decision_tree, validation)`` or tool-error JSON.
    """
    from smeme.billing.access_policy import (
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
    )
    from smeme.billing.quota import QuotaDimension, check_quota

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    result = validate_graph_for_editing(graph)
    if not result["is_valid"]:
        return tool_error_json(
            "invalid_graph",
            "Graph has blocking validation errors. Call smeme_authoring_validate_graph, "
            "fix the errors, then try create_draft again.",
            errors=list(result["errors"]),
            warnings=list(result["warnings"]),
            suggestions=result.get("suggestions") or {},
        )

    quota = await check_quota(db, user, QuotaDimension.WORKFLOWS, projected_add=1.0)
    if not quota.allowed:
        return tool_error_json(
            "quota_exceeded",
            quota.message,
            remaining=quota.remaining,
            limit=quota.limit,
            dimension="workflows",
            resets_at=quota.resets_at_iso,
        )

    title = (title_override or "").strip() or (graph.metadata.title if graph.metadata else "")
    title = title.strip()
    if not title:
        return tool_error_json(
            "invalid_graph",
            "Workflow title is required. Set metadata.title on the graph, or pass title.",
        )
    if len(title) > 200:
        title = title[:200]

    decision_tree = DecisionTree(
        title=title,
        author_id=user.id,
        graph_data=graph.model_dump(mode="json"),
    )
    db.add(decision_tree)
    await db.commit()
    await db.refresh(decision_tree)
    return decision_tree, result


def editor_url_for_decision_tree(decision_tree_id: UUID, *, base_url: str) -> str:
    """Absolute editor URL for the new draft."""
    return f"{base_url.rstrip('/')}/decision-trees/{decision_tree_id}/editor"
