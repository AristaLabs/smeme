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
from smeme.decision_tree.helpers.validation import (
    ValidationResult,
    validate_graph_for_agent_authoring,
)
from smeme.decision_tree.models import DTGraph
from smeme.mcp.tool_contract import tool_error_json
from smeme.reasoning.runtime.input_validation import MAX_RADIO_OR_OPTION_STR_LEN

AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES = 512 * 1024

# Terse machine-readable wire contract advertised in ``smeme_reasoning_capabilities``
# (``authoring_graph.schema``). Keep aligned with ``QuestionData`` / ``ConclusionData`` /
# ``GraphEdge`` / ``DTGraphMetadata`` (extra=forbid).
# Nodes use a type-discriminated oneOf so clients can validate locally without
# round-tripping (question vs conclusion data shapes are not interchangeable).
_QUESTION_DATA_SCHEMA: dict[str, Any] = {
    "title": "QuestionData",
    "type": "object",
    "required": ["text", "type", "options", "required"],
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "type": {"const": "radio"},
        "options": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_RADIO_OR_OPTION_STR_LEN},
            "minItems": 1,
        },
        "required": {"type": "boolean"},
        "help_text": {"type": ["string", "null"]},
        "authorities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["citation"],
                "additionalProperties": False,
                "properties": {
                    "citation": {"type": "string", "minLength": 1},
                    "title": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                },
            },
        },
    },
}

_CONCLUSION_DATA_SCHEMA: dict[str, Any] = {
    "title": "ConclusionData",
    "type": "object",
    "required": ["title", "summary"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "severity": {
            "enum": ["info", "warning", "critical", None],
        },
    },
}

AUTHORING_GRAPH_WIRE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["nodes", "edges", "metadata"],
    "additionalProperties": False,
    "properties": {
        "nodes": {
            "type": "array",
            "items": {
                "oneOf": [
                    {
                        "title": "QuestionNode",
                        "type": "object",
                        "required": ["id", "type", "data"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"const": "question"},
                            "data": _QUESTION_DATA_SCHEMA,
                        },
                    },
                    {
                        "title": "ConclusionNode",
                        "type": "object",
                        "required": ["id", "type", "data"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"const": "conclusion"},
                            "data": _CONCLUSION_DATA_SCHEMA,
                        },
                    },
                ]
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target"],
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "condition": {"type": ["string", "null"]},
                },
            },
        },
        "metadata": {
            "type": "object",
            "required": ["title"],
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "category": {"type": ["string", "null"]},
                "estimated_time": {
                    "type": ["integer", "null"],
                    "description": "Estimated completion time in minutes.",
                },
                "effective_date": {
                    "type": ["string", "null"],
                    "format": "date",
                    "description": "ISO 8601 date when the encoded rules became effective.",
                },
                "review_by": {
                    "type": ["string", "null"],
                    "format": "date",
                    "description": "ISO 8601 date by which the decision tree must be reviewed.",
                },
                "version": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "regression_fixtures": {
                    "type": "array",
                    "description": "Expected outcomes re-run as a blocking Deploy gate.",
                    "items": {
                        "type": "object",
                        "required": ["name", "raw_answers", "expected_conclusion_id"],
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "raw_answers": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                                "minProperties": 1,
                            },
                            "expected_conclusion_id": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    },
}

__all__ = [
    "AUTHORING_GRAPH_JSON_MAX_UTF8_BYTES",
    "AUTHORING_GRAPH_WIRE_SCHEMA",
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
        export_version = payload.get("smeme_export_version")
        if export_version != "2":
            return tool_error_json(
                "invalid_graph",
                f"Unsupported smeme_export_version {export_version!r}. "
                "Only version '2' exports or a raw DTGraph are accepted.",
            )
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


def _format_schema_error_loc(loc: tuple[Any, ...]) -> str:
    """Dot-path for agents; drop pydantic union tags if any remain."""
    parts: list[str] = []
    for part in loc:
        if part in ("question", "conclusion") and parts and parts[-1] == "data":
            # Legacy discriminator tags — keep path as nodes.N.data.<field>
            continue
        parts.append(str(part))
    return ".".join(parts)


def _schema_errors_from_validation(exc: ValidationError) -> list[str]:
    """All pydantic issues as short ``path: message`` strings."""
    out: list[str] = []
    for err in exc.errors():
        loc = _format_schema_error_loc(tuple(err.get("loc", ())))
        detail = err.get("msg", "validation failed")
        out.append(f"{loc}: {detail}" if loc else str(detail))
    return out or ["Graph schema invalid."]


def parse_authoring_graph_json(dt_graph_json: str) -> DTGraph | str:
    """Parse agent JSON into ``DTGraph``, or return tool-error JSON."""
    graph_dict = extract_graph_dict(dt_graph_json)
    if isinstance(graph_dict, str):
        return graph_dict
    try:
        return DTGraph.model_validate(graph_dict)
    except ValidationError as exc:
        errors = _schema_errors_from_validation(exc)
        if len(errors) == 1:
            msg = f"Graph schema invalid: {errors[0]}"
        else:
            msg = f"Graph schema invalid ({len(errors)} issues). See errors."
        return tool_error_json("invalid_graph", msg, errors=errors)


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
    """Insert a draft DecisionTree when edit-valid; enforce active-decision-tree quota.

    Returns ``(decision_tree, validation)`` or tool-error JSON.
    """
    from smeme.billing.access_policy import (
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
    )
    from smeme.billing.quota import QuotaDimension, check_quota

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    result = validate_graph_for_agent_authoring(graph)
    if not result["is_valid"]:
        return tool_error_json(
            "invalid_graph",
            "Graph has blocking validation errors. Call smeme_authoring_validate_graph, "
            "fix the errors, then try create_draft again.",
            errors=list(result["errors"]),
            warnings=list(result["warnings"]),
            suggestions=result.get("suggestions") or {},
        )

    quota = await check_quota(db, user, QuotaDimension.DECISION_TREES, projected_add=1.0)
    if not quota.allowed:
        return tool_error_json(
            "quota_exceeded",
            quota.message,
            remaining=quota.remaining,
            limit=quota.limit,
            dimension="decision_trees",
            resets_at=quota.resets_at_iso,
        )

    title = (title_override or "").strip() or (graph.metadata.title if graph.metadata else "")
    title = title.strip()
    if not title:
        return tool_error_json(
            "invalid_graph",
            "Decision tree title is required. Set metadata.title on the graph, or pass title.",
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
