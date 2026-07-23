"""Editor Tools tab — strict publish readiness + MCP deployment layers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, ReasoningCompiledArtifact, User
from smeme.core.templates import templates
from smeme.decision_tree.helpers.db_queries import parse_graph_data
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state_for_decision_tree
from smeme.reasoning.cevi.mcp_deployment_layers import build_mcp_deployment_layer_lines
from smeme.reasoning.publish_readiness import PublishReadiness, assess_publish_readiness


async def _load_owned_decision_tree(
    db: AsyncSession, decision_tree_id: UUID, user: User
) -> DecisionTree:
    row = (
        await db.execute(select(DecisionTree).where(DecisionTree.id == decision_tree_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision tree not found")
    if row.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return row


async def _tools_panel_context(
    *,
    db: AsyncSession,
    decision_tree: DecisionTree,
    readiness: PublishReadiness | None = None,
) -> dict:
    graph = parse_graph_data(decision_tree)
    if readiness is None:
        readiness = await assess_publish_readiness(graph)
    artifact = (
        await db.execute(
            select(ReasoningCompiledArtifact).where(
                ReasoningCompiledArtifact.decision_tree_id == decision_tree.id
            )
        )
    ).scalar_one_or_none()
    mcp_lines = build_mcp_deployment_layer_lines(
        readiness=readiness,
        artifact=artifact,
    )
    tools_row_state = await reasoning_tools_row_state_for_decision_tree(db, decision_tree)
    is_read_only = bool(decision_tree.is_public or decision_tree.was_ever_public)
    return {
        "decision_tree_id": str(decision_tree.id),
        "readiness": readiness,
        "mcp_lines": mcp_lines,
        "tools_row_state": tools_row_state,
        "is_read_only": is_read_only,
        "reasoning_status": decision_tree.reasoning_status,
        "mcp_discoverable": bool(decision_tree.mcp_discoverable),
        "checked_at": datetime.now(UTC),
    }


async def serve_tools_panel(
    *,
    request: Request,
    decision_tree_id: UUID,
    user: User,
    db: AsyncSession,
) -> HTMLResponse:
    """Full Tools tab (lazy-loaded on ``?view=tools``). Runs strict checks on each load."""
    decision_tree = await _load_owned_decision_tree(db, decision_tree_id, user)
    ctx = await _tools_panel_context(db=db, decision_tree=decision_tree)
    ctx["request"] = request
    return templates.TemplateResponse("decision_tree/_editor_tools_panel.html", ctx)


async def serve_tools_checks(
    *,
    request: Request,
    decision_tree_id: UUID,
    user: User,
    db: AsyncSession,
) -> HTMLResponse:
    """HTMX fragment: re-run strict checks + OOB deploy row refresh."""
    decision_tree = await _load_owned_decision_tree(db, decision_tree_id, user)
    ctx = await _tools_panel_context(db=db, decision_tree=decision_tree)
    ctx["request"] = request
    return templates.TemplateResponse("decision_tree/_tools_checks_fragment.html", ctx)
