"""Parse / validate / create-draft / revise helpers for MCP authoring graph tools.

Accepts a raw ``DTGraph`` JSON object or a ``.smeme.json`` export envelope
(``smeme_export_version`` + ``decision_tree.graph``).

**Create is strict** (``validate_graph_for_agent_authoring`` must pass).
**Update is lenient** (schema-valid graphs persist even with draft errors —
same save posture as the web editor). Neither path Deploys or Lists.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.decision_tree.helpers.cache import invalidate_graph_cache
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.decision_tree.helpers.validation import (
    ValidationResult,
    validate_graph_for_agent_authoring,
)
from smeme.decision_tree.models import DTGraph
from smeme.mcp.tool_contract import tool_error_json
from smeme.reasoning.assistant_tools_row_status import (
    ToolsRowState,
    reasoning_tools_row_state,
)
from smeme.reasoning.graph_hash import canonical_graph_hash
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
    "draft_edit_blocked_reason",
    "draft_read_payload",
    "editor_url_for_decision_tree",
    "extract_graph_dict",
    "get_owner_draft",
    "parse_authoring_graph_json",
    "update_draft_from_graph",
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
            "draft_ready means agent-authoring-valid (safe to create_draft; update_draft "
            "may still persist intermediate graphs). Deploy still requires the SMEme "
            "editor Deploy flow."
            if result["is_valid"]
            else (
                "Fix errors, then call smeme_authoring_validate_graph again. "
                "create_draft requires draft_ready; update_draft may save intermediate "
                "graphs after an intentional incremental edit."
            )
        ),
    }


def draft_edit_blocked_reason(decision_tree: DecisionTree) -> str | None:
    """Return ``draft_not_editable`` tool-error JSON when the web editor would block writes.

    Mirrors ``enforce_versioning_for_public_edits`` (archived / public / was-ever-public).
    """
    if decision_tree.is_archived:
        return tool_error_json(
            "draft_not_editable",
            "This decision tree is archived and cannot be edited. Restore it in the "
            "SMEme dashboard first.",
        )
    if decision_tree.is_public or decision_tree.was_ever_public:
        reason = "public" if decision_tree.is_public else "previously public"
        return tool_error_json(
            "draft_not_editable",
            f"This decision tree is {reason} and cannot be edited directly. "
            "Create a new version in the SMEme editor to make changes.",
        )
    return None


def _resolve_title(
    graph: DTGraph,
    *,
    title_override: str | None,
    existing_title: str | None = None,
) -> str:
    """Resolve DecisionTree.title, or return tool-error JSON when missing."""
    title = (title_override or "").strip() or (graph.metadata.title if graph.metadata else "")
    title = title.strip()
    if not title and existing_title:
        title = existing_title.strip()
    if not title:
        return tool_error_json(
            "invalid_graph",
            "Decision tree title is required. Set metadata.title on the graph, or pass title.",
        )
    if len(title) > 200:
        title = title[:200]
    return title


def _is_tool_error_json(value: str) -> bool:
    from smeme.mcp.tool_contract import parse_tool_error_code

    return parse_tool_error_code(value) is not None


def _sync_metadata_title(graph: DTGraph, title: str) -> DTGraph:
    """Keep graph metadata.title aligned with the DecisionTree.title column."""
    meta = graph.metadata
    if meta is None:
        from smeme.decision_tree.models import DTGraphMetadata

        return graph.model_copy(update={"metadata": DTGraphMetadata(title=title)})
    if meta.title == title:
        return graph
    return graph.model_copy(update={"metadata": meta.model_copy(update={"title": title})})


async def _load_artifact(
    db: AsyncSession, decision_tree: DecisionTree
) -> ReasoningCompiledArtifact | None:
    from smeme.reasoning.artifact_deploy import load_current_compiled_artifact

    return await load_current_compiled_artifact(db, decision_tree)


def draft_read_payload(
    decision_tree: DecisionTree,
    graph: DTGraph,
    *,
    base_url: str,
    artifact: ReasoningCompiledArtifact | None,
    editable: bool,
) -> dict[str, Any]:
    """Success body for ``smeme_authoring_get_draft`` (no watermark)."""
    graph_hash = canonical_graph_hash(graph)
    validation = validate_graph_for_agent_authoring(graph)
    deployment_sync: ToolsRowState = reasoning_tools_row_state(decision_tree, artifact)
    deployed = decision_tree.reasoning_status == "compiled" and artifact is not None
    body = validation_payload(graph, validation)
    body.update(
        {
            "decision_tree_id": str(decision_tree.id),
            "title": decision_tree.title,
            "graph": graph.model_dump(mode="json"),
            "graph_hash": graph_hash,
            "updated_at": (
                decision_tree.updated_at.isoformat() if decision_tree.updated_at else None
            ),
            "editor_url": editor_url_for_decision_tree(decision_tree.id, base_url=base_url),
            "reasoning_status": decision_tree.reasoning_status,
            "deployed": deployed,
            "deployment_sync": deployment_sync,
            "mcp_discoverable": bool(decision_tree.mcp_discoverable),
            "is_archived": bool(decision_tree.is_archived),
            "editable": editable,
        }
    )
    return body


async def get_owner_draft(
    db: AsyncSession,
    *,
    user: User,
    decision_tree_id: UUID,
    base_url: str,
) -> dict[str, Any] | str:
    """Load an owner draft for MCP read; no Listed/artifact requirement."""
    from smeme.billing.access_policy import (
        is_decision_tree_live,
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
        mcp_workflow_dormant_response,
    )

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    result = await db.execute(select(DecisionTree).where(DecisionTree.id == decision_tree_id))
    decision_tree = result.scalar_one_or_none()
    if decision_tree is None or decision_tree.author_id != user.id:
        return tool_error_json(
            "not_found",
            "Decision tree not found, or you are not its owner. "
            "Pass a decision_tree_id from smeme_authoring_create_draft "
            "or the SMEme dashboard.",
        )
    if not is_decision_tree_live(user, decision_tree):
        return mcp_workflow_dormant_response()

    try:
        graph = parse_graph_data(decision_tree)
    except ValidationError:
        return tool_error_json(
            "invalid_graph",
            "Saved graph_data is corrupt and cannot be parsed. "
            "Open the SMEme editor to repair the decision tree.",
        )

    artifact = await _load_artifact(db, decision_tree)
    editable = draft_edit_blocked_reason(decision_tree) is None
    return draft_read_payload(
        decision_tree,
        graph,
        base_url=base_url,
        artifact=artifact,
        editable=editable,
    )


async def create_draft_from_graph(
    db: AsyncSession,
    *,
    user: User,
    graph: DTGraph,
    title_override: str | None = None,
) -> tuple[DecisionTree, ValidationResult, str] | str:
    """Insert a draft DecisionTree when agent-authoring-valid; enforce decision-tree quota.

    Returns ``(decision_tree, validation, graph_hash)`` or tool-error JSON.
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

    title = _resolve_title(graph, title_override=title_override)
    if _is_tool_error_json(title):
        return title
    graph = _sync_metadata_title(graph, title)
    graph_hash = canonical_graph_hash(graph)

    decision_tree = DecisionTree(
        title=title,
        author_id=user.id,
        graph_data=graph.model_dump(mode="json"),
    )
    db.add(decision_tree)
    await db.commit()
    await db.refresh(decision_tree)
    return decision_tree, result, graph_hash


async def update_draft_from_graph(
    db: AsyncSession,
    *,
    user: User,
    decision_tree_id: UUID,
    graph: DTGraph,
    expected_graph_hash: str,
    title_override: str | None = None,
    base_url: str,
) -> dict[str, Any] | str:
    """Atomically replace an owner draft graph when ``expected_graph_hash`` matches.

    Acquires ``SELECT … FOR UPDATE`` on the DecisionTree row, compares the live
    canonical hash, and persists within the same transaction so two callers with
    the same expected hash cannot both commit.
    """
    from smeme.billing.access_policy import (
        is_decision_tree_live,
        is_workflow_pick_required,
        mcp_account_downgrade_pending_response,
        mcp_workflow_dormant_response,
    )

    expected = (expected_graph_hash or "").strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        return tool_error_json(
            "graph_conflict",
            "expected_graph_hash must be the 64-character hex digest from "
            "smeme_authoring_get_draft or smeme_authoring_create_draft.",
            expected_hash=expected_graph_hash,
        )

    if is_workflow_pick_required(user):
        return mcp_account_downgrade_pending_response(user=user)

    locked = await db.execute(
        select(DecisionTree).where(DecisionTree.id == decision_tree_id).with_for_update()
    )
    decision_tree = locked.scalar_one_or_none()
    if decision_tree is None or decision_tree.author_id != user.id:
        return tool_error_json(
            "not_found",
            "Decision tree not found, or you are not its owner. "
            "Pass a decision_tree_id from smeme_authoring_create_draft "
            "or the SMEme dashboard.",
        )
    if not is_decision_tree_live(user, decision_tree):
        return mcp_workflow_dormant_response()

    blocked = draft_edit_blocked_reason(decision_tree)
    if blocked is not None:
        return blocked

    try:
        current_graph = parse_graph_data(decision_tree)
    except ValidationError:
        return tool_error_json(
            "invalid_graph",
            "Saved graph_data is corrupt and cannot be hashed for concurrency. "
            "Open the SMEme editor to repair the decision tree.",
        )

    previous_hash = canonical_graph_hash(current_graph)
    if previous_hash != expected:
        return tool_error_json(
            "graph_conflict",
            "The decision tree changed since you last fetched it "
            "(web editor or another agent). Call smeme_authoring_get_draft, "
            "re-apply your edits, validate, and try update_draft again.",
            current_hash=previous_hash,
            expected_hash=expected,
        )

    title = _resolve_title(
        graph,
        title_override=title_override,
        existing_title=decision_tree.title,
    )
    if _is_tool_error_json(title):
        return title
    graph = _sync_metadata_title(graph, title)

    # Lenient: record agent-authoring validation but do not block the save.
    validation = validate_graph_for_agent_authoring(graph)
    new_hash = canonical_graph_hash(graph)

    decision_tree.title = title
    decision_tree.graph_data = graph.model_dump(mode="json")
    flag_modified(decision_tree, "graph_data")
    db.add(decision_tree)
    await db.commit()
    await db.refresh(decision_tree)
    await invalidate_graph_cache(decision_tree.id)

    artifact = await _load_artifact(db, decision_tree)
    deployment_sync = reasoning_tools_row_state(decision_tree, artifact)
    deployed = decision_tree.reasoning_status == "compiled" and artifact is not None
    body = validation_payload(graph, validation)
    body.update(
        {
            "decision_tree_id": str(decision_tree.id),
            "title": decision_tree.title,
            "graph_hash": new_hash,
            "previous_graph_hash": previous_hash,
            "editor_url": editor_url_for_decision_tree(decision_tree.id, base_url=base_url),
            "deployed": deployed,
            "deployment_sync": deployment_sync,
            "deployed_stale": deployment_sync == "stale",
            "mcp_discoverable": bool(decision_tree.mcp_discoverable),
            "next_step": (
                "Saved. If deployment_sync is stale, Redeploy from the SMEme editor "
                "before smeme_reasoning_evaluate will accept this graph. "
                "Use the returned graph_hash as expected_graph_hash for the next update."
                if deployed
                else (
                    "Saved draft. Polish in editor_url and Deploy + Listed when ready. "
                    "Use the returned graph_hash as expected_graph_hash for the next update."
                )
            ),
        }
    )
    return body


def editor_url_for_decision_tree(decision_tree_id: UUID, *, base_url: str) -> str:
    """Absolute editor URL for the draft."""
    return f"{base_url.rstrip('/')}/decision-trees/{decision_tree_id}/editor"
