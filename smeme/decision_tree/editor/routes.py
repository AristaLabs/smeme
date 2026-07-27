"""DecisionTree Editor Routes - Write operations for graph editing."""

import copy
import html
import json
import logging
import re
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from smeme.auth.users import current_active_user
from smeme.core.callout_html import render_callout_html
from smeme.core.database import get_db
from smeme.core.models import (
    DecisionTree,
    DecisionTreeResearchCorpus,
    ReasoningCompiledArtifact,
    User,
)
from smeme.core.templates import templates  # Shared templates with custom filters
from smeme.decision_tree.editor import tools_panel as tools_panel_handlers
from smeme.decision_tree.editor.models import (
    CreateEdgeRequest,
    CreateNodeRequest,
    CreateNodeWiredRequest,
    DeleteEdgeRequest,
    DeleteNodeRequest,
    UpdateEdgeRequest,
    UpdateNodeRequest,
)
from smeme.decision_tree.editor.workflow import build_editor_workflow
from smeme.decision_tree.helpers.db_queries import (
    _get_root_decision_tree_id,
    get_decision_tree_by_id,
    get_decision_tree_research_corpus_row,
    parse_graph_data,
)
from smeme.decision_tree.helpers.validation import (
    bare_create_node_blocked_message,
    build_validation_issue_rows,
    format_validation_results,
    get_node_validation_status,
    validate_graph_for_editing,
)
from smeme.decision_tree.models import DTGraph
from smeme.decision_tree.viewer.layout import ordered_nodes_for_checklist
from smeme.decision_tree.viewer.workflow import build_viewer_workflow
from smeme.decision_tree.viewer.workflow_config import build_viewer_workflow_config
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state_for_decision_tree
from smeme.reasoning.cevi.contract_diagnostics import (
    diagnose_published_evidence_contract,
    diagnostics_log_payload,
)
from smeme.reasoning.cevi.corpus_normalize import (
    MAX_RESEARCH_CORPUS_BYTES,
    normalize_corpus_text,
    truncate_corpus_to_max_bytes,
)
from smeme.reasoning.cevi.induction import induce_published_evidence_contract_at_publish
from smeme.reasoning.ir.types import IR_FORMAT_VERSION
from smeme.reasoning.publish_readiness import PublishReadiness, assess_publish_readiness
from smeme.reasoning.published_evidence_contract import (
    cevi_fingerprint,
    contract_to_stored_json,
)
from smeme.reasoning.version import REASONING_COMPILER_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/decision-trees/editor", tags=["decision_tree_editor"])


# Build workflows once at module load
editor_workflow = build_editor_workflow()
viewer_workflow = build_viewer_workflow()


# =============================================================================
# Type Aliases for Dependency Injection
# =============================================================================

CurrentUser = Annotated[User, Depends(current_active_user)]
AsyncSessionDep = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# Helper Functions
# =============================================================================


def render_edit_blocked_error(decision_tree_id: UUID, error_detail: str) -> HTMLResponse:
    """
    Render user-friendly HTML error for blocked edit attempts.

    Used when enforce_versioning_for_public_edits() blocks an edit.
    Returns HTML that can be swapped into HTMX targets.
    """
    error_html = render_callout_html(
        title="Edit Blocked",
        body=(
            f'<p class="mb-3">{error_detail}</p>'
            f'<div class="flex gap-2">'
            f'<a href="/decision-trees/editor/{decision_tree_id}/create_version" '
            f'class="inline-flex items-center px-3 py-2 ui-action-primary text-sm font-medium rounded">'
            f"Create New Version</a></div>"
        ),
        type="error",
        variant="accent-left",
        extra_class="mb-4",
    )
    return HTMLResponse(content=error_html, status_code=403)


def _side_panel_validation_html(
    *,
    validation_data: dict,
    validation_issue_rows: list,
    decision_tree_id: UUID | str,
    node_validation_status: dict | None = None,
) -> str:
    """Sidebar validation block for full page and OOB swaps."""
    if not (
        validation_data.get("error_count", 0) > 0 or validation_data.get("warning_count", 0) > 0
    ):
        return ""
    panel = templates.env.get_template("decision_tree/_validation_panel.html").render(
        {
            "validation_data": validation_data,
            "validation_issue_rows": validation_issue_rows,
            "node_validation_status": node_validation_status or {},
            "decision_tree_id": str(decision_tree_id),
        }
    )
    return f'<div class="mb-6 border-b border-ui-line pb-6">{panel}</div>'


def render_editor_oob_swaps(
    viewer_result: dict,
    decision_tree_id: UUID,
    selected_node_id: str | None,
) -> str:
    """
    Render all OOB swaps for editor updates.

    This ensures validation badge, panel, graph views, and warning banner
    all update after any edit operation.
    """
    # Render graph pane content (SVG + legend or empty state)
    graph_view_html = templates.env.get_template("decision_tree/_graph_view_content.html").render(
        {
            "graph": viewer_result["graph"],
            "visualization": viewer_result.get("visualization"),
            "decision_tree_id": decision_tree_id,
            "selected_node_id": selected_node_id,
            "is_public": viewer_result.get("is_public", False),
            "is_read_only": viewer_result.get("is_public", False),
        }
    )

    # Render checklist
    checklist_ordered_nodes = ordered_nodes_for_checklist(viewer_result["graph"])
    graph_checklist_html = templates.env.get_template("decision_tree/_graph_checklist.html").render(
        {
            "graph": viewer_result["graph"],
            "decision_tree_id": decision_tree_id,
            "selected_node_id": selected_node_id,
            "node_validation_status": viewer_result.get("node_validation_status", {}),
            "checklist_ordered_nodes": checklist_ordered_nodes,
        }
    )

    # Render validation badge (compact header badge)
    validation_data = viewer_result.get("validation_data", {})
    is_public = viewer_result.get("is_public", False)
    validation_badge_html = templates.env.get_template(
        "decision_tree/_validation_badge.html"
    ).render(
        {
            "validation_data": validation_data,
            "is_public": is_public,
        }
    )

    tools_chip_html = templates.env.get_template("decision_tree/_editor_tools_chip.html").render(
        {"tools_row_state": viewer_result.get("tools_row_state", "not_built")}
    )

    editor_view = viewer_result.get("editor_view", "graph")
    status_bar_html = templates.env.get_template("decision_tree/_editor_status_bar.html").render(
        {
            "graph": viewer_result.get("graph"),
            "validation_data": validation_data,
            "is_public": is_public,
            "editor_view": editor_view,
        }
    )

    # Render validation panel (detailed side panel)
    validation_issue_rows = viewer_result.get("validation_issue_rows", [])
    validation_panel_html = _side_panel_validation_html(
        validation_data=validation_data,
        validation_issue_rows=validation_issue_rows,
        node_validation_status=viewer_result.get("node_validation_status", {}),
        decision_tree_id=decision_tree_id,
    )

    # Render warning banner
    warnings = viewer_result.get("warnings", [])
    warning_banner_html = ""
    if warnings:
        warning_banner_html = templates.env.get_template(
            "decision_tree/_warning_banner.html"
        ).render({"warnings": warnings})

    # Combine all OOB swaps
    return f"""
    <div id="view-graph" hx-swap-oob="innerHTML">
        {graph_view_html}
    </div>
    <div id="view-checklist" hx-swap-oob="innerHTML">
        {graph_checklist_html}
    </div>
    <div id="validation-badge" hx-swap-oob="innerHTML">
        {validation_badge_html}
    </div>
    <div id="editor-tools-chip" hx-swap-oob="innerHTML">
        {tools_chip_html}
    </div>
    <div id="editor-status-bar" hx-swap-oob="outerHTML">
        {status_bar_html}
    </div>
    <div id="side-panel-validation" hx-swap-oob="innerHTML">
        {validation_panel_html}
    </div>
    <div id="warning-banner" hx-swap-oob="innerHTML">
        {warning_banner_html}
    </div>
    """


def _allocate_question_node_id(graph: DTGraph, requested: str | None) -> str:
    """Pick a unique question node id from ``requested`` or autogenerate ``q_<hex>``."""
    existing = {n.id for n in graph.nodes}
    rid = (requested or "").strip()
    if rid:
        if rid in existing:
            msg = (
                f"A node with id '{rid}' already exists. "
                "Choose a different id or leave the Node ID field blank to autogenerate one."
            )
            raise ValueError(msg)
        return rid
    for _ in range(64):
        candidate = f"q_{secrets.token_hex(4)}"
        if candidate not in existing:
            return candidate
    msg = "Could not generate a unique node id; try again."
    raise ValueError(msg)


def _allocate_conclusion_node_id(graph: DTGraph, requested: str | None) -> str:
    """Pick a unique conclusion node id from ``requested`` or autogenerate ``c_<hex>``."""
    existing = {n.id for n in graph.nodes}
    rid = (requested or "").strip()
    if rid:
        if rid in existing:
            msg = (
                f"A node with id '{rid}' already exists. "
                "Choose a different id or leave the Node ID field blank to autogenerate one."
            )
            raise ValueError(msg)
        return rid
    for _ in range(64):
        candidate = f"c_{secrets.token_hex(4)}"
        if candidate not in existing:
            return candidate
    msg = "Could not generate a unique node id; try again."
    raise ValueError(msg)


def _build_create_node_wired_operation_data(
    req: CreateNodeWiredRequest, resolved_node_id: str
) -> dict[str, object]:
    if req.kind == "question":
        options_list = None
        if req.options and req.options.strip():
            options_list = [ln.strip() for ln in req.options.split("\n") if ln.strip()]
        preds = [p.strip() for p in req.predecessor_ids.split(",") if p.strip()]
        return {
            "kind": "question",
            "node_id": resolved_node_id,
            "question_text": req.text,
            "question_type": req.type,
            "options": options_list,
            "help_text": (req.help_text or "").strip() or None,
            "required": req.required.lower() in ("true", "1", "yes"),
            "question_wiring": req.question_wiring.strip() or None,
            "predecessor_ids": preds,
            "incoming_edge_condition": req.incoming_edge_condition,
        }

    conclusion_edges: list = []
    raw_js = (req.conclusion_edges_json or "").strip()
    if raw_js:
        try:
            parsed = json.loads(raw_js)
        except json.JSONDecodeError as e:
            msg = "conclusion_edges_json is not valid JSON"
            raise ValueError(msg) from e
        if not isinstance(parsed, list):
            raise ValueError("conclusion_edges_json must be a JSON array")
        conclusion_edges = parsed
    elif req.conclusion_source.strip():
        conclusion_edges = [
            {"source": req.conclusion_source.strip(), "condition": req.conclusion_condition}
        ]

    recs: list[str] = []
    if req.recommendations and req.recommendations.strip():
        recs = [ln.strip() for ln in req.recommendations.split("\n") if ln.strip()]

    return {
        "kind": "conclusion",
        "node_id": resolved_node_id,
        "title": req.title.strip(),
        "summary": req.summary.strip(),
        "recommendations": recs,
        "severity": req.severity,
        "conclusion_edges": conclusion_edges,
    }


async def _create_node_error_panel_html(
    *,
    db: AsyncSession,
    user_id: UUID,
    decision_tree_id: UUID,
    message: str,
    panel_context_node_id: str,
) -> str:
    """Re-render the side panel with an error banner (HTTP 200 for HTMX swap)."""
    decision_tree_fresh = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree_fresh:
        return render_callout_html(
            body=f"<p>{html.escape(message)}</p>", type="error", variant="compact"
        )

    graph = parse_graph_data(decision_tree_fresh)
    ctx = (panel_context_node_id or "").strip()
    selected: str | None = ctx if ctx and any(n.id == ctx for n in graph.nodes) else None

    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user_id,
            "selected_node_id": selected,
        },
        config=build_viewer_workflow_config(db),
    )

    banner = render_callout_html(
        body=f"<p>{html.escape(message)}</p>",
        type="error",
        variant="compact",
        extra_class="mb-3",
    )
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, selected)
    return f"{banner}{viewer_result['rendered_html']}{oob_swaps}"


async def enforce_versioning_for_public_edits(
    db: AsyncSession,
    decision_tree: DecisionTree,
    user_id: UUID,
) -> DecisionTree:
    """
    Enforce versioning for public DecisionTree edits.

    If the DecisionTree is currently public OR was ever public, BLOCKS editing entirely.
    Author must explicitly create a new version using the "Create New Version" button.

    If the DecisionTree is private and was never public, returns the original DecisionTree for direct editing.

    Args:
        db: Database session
        decision_tree: The DecisionTree being edited
        user_id: The user attempting to edit

    Returns:
        DecisionTree to edit (original if private and was never public)

    Raises:
        HTTPException: If DecisionTree is archived or public/was_ever_public (cannot edit directly)
    """
    # Block editing archived decision trees (must restore first)
    if decision_tree.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Cannot edit archived decision tree. Please restore it first.",
        )

    # If DecisionTree is currently public OR was ever public, BLOCK editing
    if decision_tree.is_public or decision_tree.was_ever_public:
        reason = "public" if decision_tree.is_public else "previously public"
        raise HTTPException(
            status_code=403,
            detail=f"This decision tree is {reason} and cannot be edited directly. Please create a new version to make changes, or publish this version as-is.",
        )

    # DecisionTree is private and was never public - allow direct editing
    return decision_tree


async def authorize_workflow_edit(
    db: AsyncSession,
    decision_tree: DecisionTree,
    user: User,
) -> DecisionTree:
    """Billing dormant/pick-required gate, then public-version edit rules."""
    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(user, decision_tree)
    return await enforce_versioning_for_public_edits(db, decision_tree, user.id)


# =============================================================================
# Node CRUD Routes
# =============================================================================


@router.post("/create_node", response_class=HTMLResponse)
async def create_node(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: CreateNodeRequest = Depends(),
) -> HTMLResponse:
    """
    Create a new question node (no edges in this request).

    Rejects adding a detached node when the graph is already non-empty, because
    that would violate the single-entry invariant until wiring is bundled here.
    """
    decision_tree_id = req.decision_tree_id

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    graph = parse_graph_data(decision_tree)
    blocked = bare_create_node_blocked_message(graph)
    if blocked:
        err_html = await _create_node_error_panel_html(
            db=db,
            user_id=user.id,
            decision_tree_id=decision_tree_id,
            message=blocked,
            panel_context_node_id=req.panel_context_node_id,
        )
        return HTMLResponse(content=err_html, status_code=200)

    try:
        resolved_node_id = _allocate_question_node_id(graph, req.node_id)
    except ValueError as e:
        err_html = await _create_node_error_panel_html(
            db=db,
            user_id=user.id,
            decision_tree_id=decision_tree_id,
            message=str(e),
            panel_context_node_id=req.panel_context_node_id,
        )
        return HTMLResponse(content=err_html, status_code=200)

    logger.info(
        f"Creating node: {resolved_node_id}",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    operation_data = req.model_dump(exclude={"decision_tree_id", "panel_context_node_id"})
    operation_data["node_id"] = resolved_node_id

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "create_node",
            "operation_data": operation_data,
            "selected_node_id": resolved_node_id,
        },
        config={"configurable": {"db": db}},
    )

    # Check for errors
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")
        err_html = await _create_node_error_panel_html(
            db=db,
            user_id=user.id,
            decision_tree_id=decision_tree_id,
            message=error_message,
            panel_context_node_id=req.panel_context_node_id,
        )
        return HTMLResponse(content=err_html, status_code=200)

    # Re-render viewer with new node selected
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": resolved_node_id,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, resolved_node_id)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.post("/create_node_wired", response_class=HTMLResponse)
async def create_node_wired_endpoint(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: CreateNodeWiredRequest = Depends(),
) -> HTMLResponse:
    """
    Create a question or conclusion node plus required edges in one save.

    Questions on a non-empty graph must use incoming wiring or new_start wiring.
    Conclusions require at least one conditional incoming edge from a question.
    """
    decision_tree_id = req.decision_tree_id

    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    graph = parse_graph_data(decision_tree)
    try:
        if req.kind == "question":
            resolved_node_id = _allocate_question_node_id(graph, req.node_id)
        else:
            resolved_node_id = _allocate_conclusion_node_id(graph, req.node_id)
        operation_data = _build_create_node_wired_operation_data(req, resolved_node_id)
    except ValueError as e:
        err_html = await _create_node_error_panel_html(
            db=db,
            user_id=user.id,
            decision_tree_id=decision_tree_id,
            message=str(e),
            panel_context_node_id=req.panel_context_node_id,
        )
        return HTMLResponse(content=err_html, status_code=200)

    logger.info(
        f"Creating wired node: {resolved_node_id} ({req.kind})",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "create_node_wired",
            "operation_data": operation_data,
            "selected_node_id": resolved_node_id,
        },
        config={"configurable": {"db": db}},
    )

    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")
        err_html = await _create_node_error_panel_html(
            db=db,
            user_id=user.id,
            decision_tree_id=decision_tree_id,
            message=error_message,
            panel_context_node_id=req.panel_context_node_id,
        )
        return HTMLResponse(content=err_html, status_code=200)

    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": resolved_node_id,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, resolved_node_id)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.post("/update_node", response_class=HTMLResponse)
async def update_node(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: UpdateNodeRequest = Depends(),
) -> HTMLResponse:
    """
    Update an existing node's properties.

    Returns updated editor view via HTMX swap.
    """
    decision_tree_id = req.decision_tree_id
    logger.info(f"Updating node: {req.node_id}", extra={"decision_tree_id": str(decision_tree_id)})

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Load graph to determine node type
    graph = parse_graph_data(decision_tree)
    node = next((n for n in graph.nodes if n.id == req.node_id), None)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Determine operation type based on node type
    if node.is_question():
        operation_type = "update_node"
    elif node.is_conclusion():
        operation_type = "update_conclusion_node"
    else:
        raise HTTPException(status_code=400, detail="Unknown node type")

    # Convert to dict (only include non-None values)
    # Exclude decision_tree_id as it's passed separately to the workflow
    operation_data = req.model_dump(exclude_none=True, exclude={"decision_tree_id"})

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": operation_type,
            "operation_data": operation_data,
            "selected_node_id": req.node_id,
        },
        config={"configurable": {"db": db}},
    )

    # Check for errors
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")
        return HTMLResponse(
            content=f"<div class='alert alert-error'>{error_message}</div>",
            status_code=400,
        )

    # Re-render viewer with updated node selected
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": req.node_id,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, req.node_id)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.post("/delete_node", response_class=HTMLResponse)
async def delete_node(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: DeleteNodeRequest = Depends(),
) -> HTMLResponse:
    """
    Delete a node and its connected edges.

    Returns updated editor view via HTMX swap.
    """
    decision_tree_id = req.decision_tree_id

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Convert to dict (Pydantic already validated the data)
    # Exclude decision_tree_id as it's passed separately to the workflow
    operation_data = req.model_dump(exclude={"decision_tree_id"})

    logger.info(
        f"Deleting node: {req.node_id}",
        extra={"decision_tree_id": str(decision_tree_id), "operation_data": operation_data},
    )

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "delete_node",
            "operation_data": operation_data,
            "selected_node_id": None,  # Deselect after deletion
        },
        config={"configurable": {"db": db}},
    )

    # Check for errors
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")
        return HTMLResponse(
            content=f"<div class='alert alert-error'>{error_message}</div>",
            status_code=400,
        )

    # Re-render viewer with no selection
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": None,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, None)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.get("/validate/{decision_tree_id}", response_class=HTMLResponse)
async def validate_realtime(
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Real-time validation endpoint - returns only the validation panel HTML.

    Used for instant feedback as users edit nodes/edges without full page reload.
    This is a lightweight endpoint that just validates the current graph state.
    """
    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this decision tree")

    # Parse and validate graph
    graph = parse_graph_data(decision_tree)
    validation_result = validate_graph_for_editing(graph)
    is_valid, errors, warnings = (
        validation_result["is_valid"],
        validation_result["errors"],
        validation_result["warnings"],
    )

    # Format validation results
    validation_data = format_validation_results(errors if not is_valid else [], warnings)
    validation_issue_rows = build_validation_issue_rows(
        list(errors) if not is_valid else [],
        list(warnings),
        graph=graph,
        suggestions=validation_result.get("suggestions"),
    )
    panel_html = _side_panel_validation_html(
        validation_data=validation_data,
        validation_issue_rows=validation_issue_rows,
        node_validation_status=get_node_validation_status(graph),
        decision_tree_id=decision_tree_id,
    )

    return HTMLResponse(content=panel_html)


# =============================================================================
# Edge CRUD Routes
# =============================================================================


@router.post("/create_edge", response_class=HTMLResponse)
async def create_edge(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: CreateEdgeRequest = Depends(),
) -> HTMLResponse:
    """
    Create a new edge in the DecisionTree graph.

    Returns updated editor view via HTMX swap.
    """
    decision_tree_id = req.decision_tree_id
    logger.info(
        f"Creating edge: {req.source} -> {req.target}",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Convert to dict (Pydantic already validated the data)
    # Exclude decision_tree_id as it's passed separately to the workflow
    operation_data = req.model_dump(exclude={"decision_tree_id"})

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "create_edge",
            "operation_data": operation_data,
            "selected_node_id": req.source,  # Keep source selected
        },
        config={"configurable": {"db": db}},
    )

    # Check for operation errors (not validation errors - those are allowed now)
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")

        # Log the error for debugging
        logger.error(
            f"Edge creation failed: {error_message}",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "source": req.source,
                "target": req.target,
            },
        )

        # Re-render the side panel with error message at the top
        viewer_result = await viewer_workflow.ainvoke(
            {
                "decision_tree_id": decision_tree_id,
                "user_id": user.id,
                "selected_node_id": req.source,
            },
            config=build_viewer_workflow_config(db, request=request),
        )

        # Prepend error message to the rendered HTML
        error_html = render_callout_html(
            title="Edge Creation Error",
            body=f'<p class="text-sm">{html.escape(error_message)}</p>',
            type="error",
            variant="compact",
            extra_class="mb-4",
        )

        # Inject error at the beginning of the side panel content
        side_panel_html = viewer_result["rendered_html"]
        # Insert error after the error display divs
        side_panel_html = side_panel_html.replace(
            '<div id="new-edge-error-display"></div>',
            f'<div id="new-edge-error-display"></div>\n{error_html}',
            1,
        )

        return HTMLResponse(content=side_panel_html, status_code=200)

    # Edge created and saved successfully (even if validation has errors/warnings)
    # Re-render viewer with source selected
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": req.source,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, req.source)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.post("/update_edge", response_class=HTMLResponse)
async def update_edge(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: UpdateEdgeRequest = Depends(),
) -> HTMLResponse:
    """
    Update an existing edge's target or condition.

    Returns updated editor view via HTMX swap.
    """
    decision_tree_id = req.decision_tree_id
    logger.info(
        f"Updating edge: {req.source} -> {req.old_target}",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Convert to dict (only include non-None values)
    # Exclude decision_tree_id as it's passed separately to the workflow
    operation_data = req.model_dump(exclude_none=True, exclude={"decision_tree_id"})

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "update_edge",
            "operation_data": operation_data,
            "selected_node_id": req.source,
        },
        config={"configurable": {"db": db}},
    )

    # Check for operation errors (not validation errors - those are allowed now)
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")

        # Log the error for debugging
        logger.error(
            f"Edge update failed: {error_message}",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "source": req.source,
                "old_target": req.old_target,
            },
        )

        # Re-render the side panel with error message at the top
        viewer_result = await viewer_workflow.ainvoke(
            {
                "decision_tree_id": decision_tree_id,
                "user_id": user.id,
                "selected_node_id": req.source,
            },
            config=build_viewer_workflow_config(db, request=request),
        )

        # Prepend error message to the rendered HTML
        error_html = render_callout_html(
            title="Edge Update Error",
            body=f'<p class="text-sm">{html.escape(error_message)}</p>',
            type="error",
            variant="compact",
            extra_class="mb-4",
        )

        # Inject error at the beginning of the side panel content
        side_panel_html = viewer_result["rendered_html"]
        # Insert error after the opening div tags
        side_panel_html = side_panel_html.replace(
            '<div id="new-edge-error-display"></div>',
            f'<div id="new-edge-error-display"></div>\n{error_html}',
            1,
        )

        return HTMLResponse(content=side_panel_html, status_code=200)

    # Edge updated and saved successfully (even if validation has errors/warnings)
    # Re-render viewer with source selected
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": req.source,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, req.source)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


@router.post("/delete_edge", response_class=HTMLResponse)
async def delete_edge(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    req: DeleteEdgeRequest = Depends(),
) -> HTMLResponse:
    """
    Delete an edge from the DecisionTree graph.

    Returns updated editor view via HTMX swap.
    """
    decision_tree_id = req.decision_tree_id
    logger.info(
        f"Deleting edge: {req.source} -> {req.target}",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Convert to dict (Pydantic already validated the data)
    # Exclude decision_tree_id as it's passed separately to the workflow
    operation_data = req.model_dump(exclude={"decision_tree_id"})

    # Run editor workflow
    result = await editor_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "operation": "delete_edge",
            "operation_data": operation_data,
            "selected_node_id": req.source,
        },
        config={"configurable": {"db": db}},
    )

    # Check for errors
    if not result.get("success", False):
        error_message = result.get("error_message", "Unknown error")
        return HTMLResponse(
            content=f"<div class='alert alert-error'>{error_message}</div>",
            status_code=400,
        )

    # Re-render viewer with source selected
    viewer_result = await viewer_workflow.ainvoke(
        {
            "decision_tree_id": decision_tree_id,
            "user_id": user.id,
            "selected_node_id": req.source,
        },
        config=build_viewer_workflow_config(db, request=request),
    )

    logger.info(f"Edge deleted successfully, returning side panel content for node {req.source}")

    # Combine side panel content + OOB swaps for all editor UI elements
    oob_swaps = render_editor_oob_swaps(viewer_result, decision_tree_id, req.source)
    combined_html = f"{viewer_result['rendered_html']}{oob_swaps}"

    return HTMLResponse(content=combined_html)


# =============================================================================
# DecisionTree Settings Routes
# =============================================================================


@router.post("/{decision_tree_id}/settings", response_class=HTMLResponse)
async def update_decision_tree_settings(
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    intended_audience: Annotated[str | None, Form()] = None,
    use_case: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """Update DecisionTree metadata settings (intended_audience, use_case)."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this decision tree")

    # Same edit-blocking as other editor routes
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Normalize empty strings to None
    decision_tree.intended_audience = (
        intended_audience.strip() if intended_audience and intended_audience.strip() else None
    )
    decision_tree.use_case = use_case.strip() if use_case and use_case.strip() else None

    db.add(decision_tree)
    await db.commit()

    logger.info(
        f"Updated DecisionTree settings: {decision_tree_id}",
        extra={
            "decision_tree_id": str(decision_tree_id),
            "intended_audience": decision_tree.intended_audience,
            "use_case": decision_tree.use_case,
        },
    )

    return HTMLResponse(
        content='<span class="text-green-600">Settings saved.</span>',
        status_code=200,
    )


# =============================================================================
# Research corpus (CEVI publish-time input)
# =============================================================================


def _research_corpus_save_htmx_html(*, message: str, byte_count: int) -> str:
    """HTMX: status line + OOB swap for the static “Status: N bytes” paragraph above the form."""
    if byte_count > 0:
        summary = f'<span class="text-green-700 font-medium">{byte_count} bytes saved</span>'
    else:
        summary = '<span class="text-gray-700">empty</span>'
    return (
        f"{message}"
        f'<p id="research-corpus-byte-summary" class="text-xs text-gray-500" '
        f'hx-swap-oob="true">Status: {summary}</p>'
    )


@router.post("/{decision_tree_id}/research-corpus", response_class=HTMLResponse)
async def save_research_corpus(
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    body_text: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Persist normalized research corpus for CEVI (owner-only)."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    normalized = truncate_corpus_to_max_bytes(normalize_corpus_text(body_text))
    row = await db.get(DecisionTreeResearchCorpus, decision_tree_id)
    if row:
        row.body_text = normalized
    else:
        db.add(DecisionTreeResearchCorpus(decision_tree_id=decision_tree.id, body_text=normalized))
    db.add(decision_tree)
    await db.commit()

    n_bytes = len(normalized.encode("utf-8"))
    msg = (
        f'<span class="text-green-600">Research corpus saved '
        f"({n_bytes} bytes, max {MAX_RESEARCH_CORPUS_BYTES}).</span>"
    )
    return HTMLResponse(
        content=_research_corpus_save_htmx_html(message=msg, byte_count=n_bytes),
        status_code=200,
    )


@router.delete("/{decision_tree_id}/research-corpus", response_class=HTMLResponse)
async def delete_research_corpus(
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Remove persisted research corpus (owner-only)."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    await db.execute(
        delete(DecisionTreeResearchCorpus).where(
            DecisionTreeResearchCorpus.decision_tree_id == decision_tree_id
        )
    )
    await db.commit()
    return HTMLResponse(
        content=_research_corpus_save_htmx_html(
            message='<span class="text-gray-600">Research corpus cleared.</span>',
            byte_count=0,
        ),
        status_code=200,
    )


# =============================================================================
# Title Editing Routes
# =============================================================================


@router.post("/edit_title_form", response_class=HTMLResponse)
async def edit_title_form(
    decision_tree_id: Annotated[UUID, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Return inline edit form for DecisionTree title.
    """
    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        return HTMLResponse(
            content='<div class="text-red-600">Decision tree not found</div>', status_code=404
        )

    if decision_tree.author_id != user.id:
        return HTMLResponse(
            content='<div class="text-red-600">Not authorized</div>', status_code=403
        )

    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    try:
        raise_if_workflow_edit_denied(user, decision_tree)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Return edit form HTML
    form_html = f"""
    <div class="flex items-center gap-2">
      <form hx-post="/decision-trees/editor/update_title"
            hx-target="#title-container"
            hx-swap="innerHTML">
        <input type="hidden" name="decision_tree_id" value="{decision_tree_id}">
        <input type="text"
               name="title"
               value="{decision_tree.title}"
               class="text-2xl font-bold border-2 border-blue-500 rounded px-2 py-1 bg-white min-w-64"
               required
               hx-trigger="keydown[key=='Enter'] from:closest input, focusout from:closest input delay:100ms"
               autofocus>
      </form>
    </div>
    """.strip()

    return HTMLResponse(content=form_html)


@router.post("/update_title", response_class=HTMLResponse)
async def update_title(
    decision_tree_id: Annotated[UUID, Form()],
    title: Annotated[str, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Update DecisionTree title and return updated title display.
    """
    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        return HTMLResponse(
            content='<div class="text-red-600">Decision tree not found</div>', status_code=404
        )

    if decision_tree.author_id != user.id:
        return HTMLResponse(
            content='<div class="text-red-600">Not authorized</div>', status_code=403
        )

    # Enforce versioning for public decision trees (blocks edits for public/was_ever_public decision trees)
    try:
        decision_tree = await authorize_workflow_edit(db, decision_tree, user)
    except HTTPException as e:
        if e.status_code == 403:
            return render_edit_blocked_error(decision_tree_id, e.detail)
        raise

    # Validate title
    title = title.strip()
    if not title:
        return HTMLResponse(
            content='<div class="text-red-600">Title cannot be empty</div>', status_code=400
        )

    # Update title
    decision_tree.title = title
    await db.commit()

    logger.info(
        f"Updated DecisionTree title: {decision_tree_id} -> '{title}'",
        extra={"decision_tree_id": str(decision_tree_id), "user_id": str(user.id)},
    )

    # Return updated title display
    display_html = f"""
    <div class="flex items-center gap-2">
      <h2 class="text-2xl font-bold">{title}</h2>

      <button class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
              hx-post="/decision-trees/editor/edit_title_form"
              hx-vals='{{"decision_tree_id": "{decision_tree_id}"}}'
              hx-target="#title-container"
              hx-swap="innerHTML"
              title="Edit title">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
        </svg>
        Edit
      </button>
    </div>
    """.strip()

    return HTMLResponse(content=display_html)


# =============================================================================
# Publish Routes
# =============================================================================


@router.get("/{decision_tree_id}/publish-modal", response_class=HTMLResponse)
async def publish_confirm_modal(
    request: Request,
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """Serve the publish confirmation modal (replaces browser confirm)."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree or decision_tree.author_id != user.id:
        return HTMLResponse(content="", status_code=404)

    return templates.TemplateResponse(
        "decision_tree/_publish_confirm_modal.html",
        {
            "request": request,
            "decision_tree_id": str(decision_tree_id),
            "return_next": request.query_params.get("return_next") or None,
        },
    )


def _publish_gate_failed_response(
    request: Request, readiness: PublishReadiness, decision_tree_id: UUID
) -> HTMLResponse:
    """HTMX: swap modal + OOB editor banner; non-HTMX: full page with back link."""
    is_htmx = (request.headers.get("HX-Request") or "").lower() == "true"
    ctx = {"request": request, "readiness": readiness, "decision_tree_id": str(decision_tree_id)}
    if is_htmx:
        return templates.TemplateResponse(
            "decision_tree/_publish_blocked_modal.html",
            ctx,
            status_code=200,
        )
    return templates.TemplateResponse(
        "decision_tree/_publish_blocked_standalone.html",
        ctx,
        status_code=400,
    )


@router.get("/{decision_tree_id}/publish-preflight", response_class=HTMLResponse)
async def publish_preflight_panel(
    request: Request,
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """HTMX fragment: publication + IR + reasoning preflight (loads inside publish modal)."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree or decision_tree.author_id != user.id:
        return HTMLResponse(content="", status_code=404)
    graph = parse_graph_data(decision_tree)
    readiness = await assess_publish_readiness(graph)
    tools_row_state = await reasoning_tools_row_state_for_decision_tree(db, decision_tree)
    return templates.TemplateResponse(
        "decision_tree/_publish_preflight_panel.html",
        {
            "request": request,
            "readiness": readiness,
            "decision_tree_id": str(decision_tree_id),
            "return_next": request.query_params.get("return_next") or None,
            "tools_row_state": tools_row_state,
        },
    )


def _publish_success_redirect_url(decision_tree_id: UUID, return_next: str | None) -> str:
    """Redirect after successful deploy; honors dashboard / tools tab return_next."""
    if return_next == "dashboard":
        return "/decision-trees/dashboard?deployed=1"
    if return_next in ("tools", "editor"):
        return f"/decision-trees/{decision_tree_id}/editor?view=tools&reasoning_compiled=1"
    return f"/decision-trees/{decision_tree_id}/editor?reasoning_compiled=1"


@router.post("/{decision_tree_id}/publish", response_class=HTMLResponse, response_model=None)
async def publish_decision_tree(
    request: Request,
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> RedirectResponse | Response | HTMLResponse:
    """
    Compile this DecisionTree to a persisted IR artifact (sets reasoning_status = "compiled").

    Does NOT change gallery visibility. MCP deploy is available on all tiers.
    """
    logger.info(
        f"Publishing reasoning artifact for Decision tree: {decision_tree_id}",
        extra={"decision_tree_id": str(decision_tree_id)},
    )

    form = await request.form()
    return_next_raw = form.get("return_next")
    return_next = str(return_next_raw).strip() if return_next_raw else None
    if return_next == "":
        return_next = None

    result = await db.execute(
        select(DecisionTree)
        .options(selectinload(DecisionTree.parent), selectinload(DecisionTree.children))
        .where(DecisionTree.id == decision_tree_id)
    )
    decision_tree = result.scalar_one_or_none()

    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to publish this decision tree")

    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(user, decision_tree)

    graph = parse_graph_data(decision_tree)

    readiness = await assess_publish_readiness(graph)
    if not readiness.ready:
        return _publish_gate_failed_response(request, readiness, decision_tree_id)

    ir_json = readiness.ir_json
    graph_hash = readiness.graph_hash
    assert ir_json is not None  # noqa: S101 — guarded by readiness.ready
    assert graph_hash is not None  # noqa: S101

    corp_row = await get_decision_tree_research_corpus_row(db, decision_tree.id)
    corpus_body = corp_row.body_text if corp_row else None

    cev_contract, corpus_snapshot = induce_published_evidence_contract_at_publish(
        ir_json=ir_json,
        graph=graph,
        graph_hash=graph_hash,
        ir_format_version=IR_FORMAT_VERSION,
        corpus_body=corpus_body,
        legal_at_publish=bool(decision_tree.cevi_legal),
    )

    cevi_diag = diagnose_published_evidence_contract(cev_contract)
    logger.info(
        "cevi_publish_contract",
        extra={
            "decision_tree_id": str(decision_tree.id),
            "cevi_contract_diagnostics": diagnostics_log_payload(cevi_diag),
        },
    )

    cevi_contract_json = contract_to_stored_json(cev_contract)
    cevi_contract_hash = cevi_fingerprint(cev_contract)
    research_corpus_hash = corpus_snapshot.sha256_hex

    from smeme.reasoning.artifact_deploy import persist_compiled_artifact_append_only

    artifact = await persist_compiled_artifact_append_only(
        db,
        decision_tree=decision_tree,
        ir_json=ir_json,
        graph_hash=graph_hash,
        ir_format_version=IR_FORMAT_VERSION,
        cevi_contract_json=cevi_contract_json,
        cevi_contract_hash=cevi_contract_hash,
        research_corpus_hash=research_corpus_hash,
        compiler_version=REASONING_COMPILER_VERSION,
        cevi_legal_validation_status="not_required",
    )
    await db.flush()

    await db.commit()
    await db.refresh(decision_tree)

    logger.info(
        f"Reasoning artifact compiled for Decision tree: {decision_tree.title}",
        extra={
            "decision_tree_id": str(decision_tree.id),
            "version_number": decision_tree.version_number,
            "artifact_version": artifact.artifact_version,
            "artifact_hash": artifact.artifact_hash,
            "user_id": str(user.id),
        },
    )

    redirect_url = _publish_success_redirect_url(decision_tree_id, return_next)
    if (request.headers.get("HX-Request") or "").lower() == "true":
        return Response(status_code=200, headers={"HX-Redirect": redirect_url})
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/{decision_tree_id}/tools", response_class=HTMLResponse, response_model=None)
async def editor_tools_panel(
    request: Request,
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    return await tools_panel_handlers.serve_tools_panel(
        request=request, decision_tree_id=decision_tree_id, user=user, db=db
    )


@router.get("/{decision_tree_id}/tools-checks", response_class=HTMLResponse, response_model=None)
async def editor_tools_checks(
    request: Request,
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    return await tools_panel_handlers.serve_tools_checks(
        request=request, decision_tree_id=decision_tree_id, user=user, db=db
    )


# =============================================================================
# Helper Routes for Dynamic UI
# =============================================================================


@router.post("/create_edge_form", response_class=HTMLResponse)
async def create_edge_form(
    decision_tree_id: Annotated[UUID, Form()],
    source_node_id: Annotated[str, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Render inline form for creating a new edge from the selected node.

    Used by HTMX when clicking "Add Edge" button in side panel.
    """
    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(user, decision_tree)

    # Load graph to get available target nodes
    from smeme.decision_tree.helpers.db_queries import parse_graph_data

    graph = parse_graph_data(decision_tree)

    # Validate source node exists and is a question (conclusions cannot have outgoing edges)
    source_node = next((n for n in graph.nodes if n.id == source_node_id), None)
    if not source_node:
        return HTMLResponse(
            content='<div class="text-red-600 dark:text-red-400 text-sm">Source node not found</div>',
            status_code=400,
        )

    if source_node.is_conclusion():
        return HTMLResponse(
            content='<div class="text-red-600 dark:text-red-400 text-sm">Cannot add edges from conclusion nodes</div>',
            status_code=400,
        )

    # Build form HTML
    # Generate options for target nodes (all nodes except source)
    node_options = "".join(
        [
            f'<option value="{n.id}">'
            f"{n.id} - {n.data.text if getattr(n, 'data', None) and getattr(n.data, 'text', None) else '(no text)'}"
            f"</option>"
            for n in graph.nodes
            if n.id != source_node_id
        ]
    )

    form_html = f"""
    <form hx-post="/decision-trees/editor/create_edge"
          hx-target="#side-panel-content"
          hx-swap="innerHTML"
          hx-ext="response-targets"
          class="p-3 bg-ui-surface-muted rounded border border-ui-line">
        <input type="hidden" name="decision_tree_id" value="{decision_tree_id}">
        <input type="hidden" name="source" value="{source_node_id}">

        <!-- Error display area -->
        <div id="new-edge-error-display"></div>

        <div class="mb-3">
            <label class="block text-sm font-medium text-ui-ink-secondary mb-1">
                Target Node:
            </label>
            <select name="target"
                    class="w-full px-3 py-2 border border-ui-line-strong rounded-md bg-ui-surface-muted text-ui-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-500"
                    required>
                <option value="">-- Select target node --</option>
                {node_options}
            </select>
        </div>

        <div class="mb-3">
            <label class="block text-sm font-medium text-ui-ink-secondary mb-1">
                Condition (optional):
            </label>
            <input type="text" name="condition"
                   class="w-full px-3 py-2 border border-ui-line-strong rounded-md bg-ui-surface-muted text-ui-ink
                          focus:outline-none focus:ring-2 focus:ring-brand-500"
                   placeholder="e.g., 'Grassland'">
            <p class="mt-1 text-xs text-ui-ink-muted">
                💡 For radio, use a single option label exactly as shown on the question (e.g. &quot;Grassland&quot;).<br>
                📌 Option labels can contain commas (e.g., &quot;Student on F, J, M or Q visas&quot;)
            </p>
        </div>

        <div class="flex gap-2">
            <button type="submit"
                    class="px-3 py-2 text-sm font-medium ui-action-primary rounded-md">
                Create Edge
            </button>
            <button type="button"
                    class="px-3 py-2 text-sm font-medium text-ui-ink-secondary bg-ui-surface
                           border border-ui-line-strong rounded-md hover:bg-ui-surface-muted"
                    onclick="location.reload()">
                Cancel
            </button>
        </div>
    </form>
    """

    return HTMLResponse(content=form_html)


@router.post("/update_edge_form", response_class=HTMLResponse)
async def update_edge_form(
    decision_tree_id: Annotated[UUID, Form()],
    source: Annotated[str, Form()],
    target: Annotated[str, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
    condition: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """
    Render inline form for editing an edge.

    Used by HTMX to swap edge display with editable form.
    """
    # Authorization check
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if decision_tree.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(user, decision_tree)

    # Load graph to get available target nodes
    from smeme.decision_tree.helpers.db_queries import parse_graph_data

    graph = parse_graph_data(decision_tree)

    # Build form HTML
    # Generate options for target nodes
    node_options = "".join(
        [
            f'<option value="{n.id}">'
            f"{n.id} - {n.data.text if getattr(n, 'data', None) and getattr(n.data, 'text', None) else '(no text)'}"
            f"</option>"
            for n in graph.nodes
            if n.id not in (source, target)
        ]
    )

    # Get current target node display text
    target_node = next((n for n in graph.nodes if n.id == target), None)
    target_display = (
        f"{target} - {target_node.data.text}"
        if target_node
        and getattr(target_node, "data", None)
        and getattr(target_node.data, "text", None)
        else f"{target} - (no text)"
    )

    form_html = f"""
    <form hx-post="/decision-trees/editor/update_edge"
          hx-target="#side-panel-content"
          hx-swap="innerHTML"
          hx-ext="response-targets"
          class="mt-2 p-3 bg-ui-surface-muted rounded border border-ui-line">
        <input type="hidden" name="decision_tree_id" value="{decision_tree_id}">
        <input type="hidden" name="source" value="{source}">
        <input type="hidden" name="old_target" value="{target}">
        <input type="hidden" name="old_condition" value="{condition or ""}">

        <!-- Error display area -->
        <div id="edge-error-display"></div>

        <div class="mb-3">
            <label class="block text-sm font-medium text-ui-ink-secondary mb-1">
                Target Node:
            </label>
            <select name="new_target"
                    class="w-full px-3 py-2 border border-ui-line-strong rounded-md bg-ui-surface-muted text-ui-ink
                           focus:outline-none focus:ring-2 focus:ring-brand-500">
                <option value="{target}" selected>{target_display}</option>
                {node_options}
            </select>
        </div>

        <div class="mb-3">
            <label class="block text-sm font-medium text-ui-ink-secondary mb-1">
                Condition:
            </label>
            <input type="text" name="new_condition" value="{condition or ""}"
                   placeholder="Leave empty for default edge"
                   class="w-full px-3 py-2 border border-ui-line-strong rounded-md bg-ui-surface-muted text-ui-ink
                          focus:outline-none focus:ring-2 focus:ring-brand-500">
            <p class="mt-1 text-xs text-ui-ink-muted">
                💡 For radio, use a single option label exactly as shown on the question (e.g. &quot;Grassland&quot;).<br>
                📌 Option labels can contain commas (e.g., &quot;Student on F, J, M or Q visas&quot;)
            </p>
        </div>

        <div class="flex gap-2">
            <button type="submit"
                    class="px-3 py-2 text-sm font-medium ui-action-primary rounded-md">
                Save
            </button>
            <button type="button"
                    class="px-3 py-2 text-sm font-medium text-ui-ink-secondary bg-ui-surface
                           border border-ui-line-strong rounded-md hover:bg-ui-surface-muted"
                    onclick="location.reload()">
                Cancel
            </button>
        </div>
    </form>
    """

    return HTMLResponse(content=form_html)


# =============================================================================
# Version Management
# =============================================================================


@router.post("/{decision_tree_id}/create_version")
async def create_new_version(
    decision_tree_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
) -> RedirectResponse:
    """
    Create a new version of an existing DecisionTree.

    Used when DecisionTree is public or was ever public and cannot be edited directly.
    Author must explicitly click "Create New Version" button.

    - Copies structure from original
    - Marks original as not current
    - Creates new draft version with incremented version number
    - Redirects to editor for the new version
    """
    # Load original with full structure and relationships
    result = await db.execute(
        select(DecisionTree)
        .options(
            selectinload(DecisionTree.parent),
            selectinload(DecisionTree.children),
        )
        .where(DecisionTree.id == decision_tree_id, DecisionTree.author_id == user.id)
    )
    original = result.scalar_one_or_none()

    if not original:
        raise HTTPException(status_code=404, detail="Decision tree not found")

    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(user, original)

    # Can't version archived decision trees
    if original.is_archived:
        raise HTTPException(
            status_code=400,
            detail="Cannot create version from archived decision tree. Restore it first.",
        )

    logger.info(
        f"Creating new version of Decision tree: {original.title}",
        extra={
            "original_decision_tree_id": str(original.id),
            "current_version": original.version_number,
        },
    )

    # Get base title from root version (v1) to avoid "Title v2 v3" problem
    # Use database query to avoid MissingGreenlet error
    root_decision_tree_id = await _get_root_decision_tree_id(db, original)
    root_decision_tree = await get_decision_tree_by_id(db, root_decision_tree_id)
    if not root_decision_tree:
        raise HTTPException(status_code=404, detail="Root decision tree not found")
    # Strip any existing version suffix (e.g., "My DecisionTree v1" → "My decision tree")
    base_title = re.sub(r"\s+v\d+$", "", root_decision_tree.title)
    new_version_number = original.version_number + 1

    # Create new version
    new_version = DecisionTree(
        title=f"{base_title} v{new_version_number}",
        author_id=user.id,
        version_number=new_version_number,
        parent_decision_tree_id=original.id,
        is_current=True,
        is_public=False,  # Always start as private (not visible to public)
        was_ever_public=False,  # New version, no public history
        # Deep copy structure (graph_data with nodes, edges, metadata)
        graph_data=copy.deepcopy(original.graph_data) if original.graph_data else {},
    )

    # Mark original as not current
    original.is_current = False

    db.add(new_version)
    db.add(original)
    await db.commit()
    await db.refresh(new_version)

    logger.info(
        "Created new version successfully",
        extra={
            "original_decision_tree_id": str(original.id),
            "new_decision_tree_id": str(new_version.id),
            "new_version_number": new_version.version_number,
        },
    )

    # Redirect to dashboard where new draft version will be visible
    # Regular form POST (not HTMX), so standard redirect works
    return RedirectResponse(url="/decision-trees/dashboard", status_code=303)
