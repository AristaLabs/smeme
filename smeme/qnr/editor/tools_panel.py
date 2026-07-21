"""Editor Tools tab — strict publish readiness + MCP deployment layers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import QNR, ReasoningCompiledArtifact, User
from smeme.core.templates import templates
from smeme.qnr.helpers.db_queries import parse_graph_data
from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state_for_qnr
from smeme.reasoning.cevi.mcp_deployment_layers import build_mcp_deployment_layer_lines
from smeme.reasoning.publish_readiness import PublishReadiness, assess_publish_readiness


async def _load_owned_qnr(db: AsyncSession, qnr_id: UUID, user: User) -> QNR:
    row = (await db.execute(select(QNR).where(QNR.id == qnr_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if row.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return row


async def _tools_panel_context(
    *,
    db: AsyncSession,
    qnr: QNR,
    readiness: PublishReadiness | None = None,
) -> dict:
    graph = parse_graph_data(qnr)
    if readiness is None:
        readiness = await assess_publish_readiness(graph)
    artifact = (
        await db.execute(
            select(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.qnr_id == qnr.id)
        )
    ).scalar_one_or_none()
    mcp_lines = build_mcp_deployment_layer_lines(
        readiness=readiness,
        artifact=artifact,
    )
    tools_row_state = await reasoning_tools_row_state_for_qnr(db, qnr)
    is_read_only = bool(qnr.is_public or qnr.was_ever_public)
    return {
        "qnr_id": str(qnr.id),
        "readiness": readiness,
        "mcp_lines": mcp_lines,
        "tools_row_state": tools_row_state,
        "is_read_only": is_read_only,
        "reasoning_status": qnr.reasoning_status,
        "mcp_discoverable": bool(qnr.mcp_discoverable),
        "checked_at": datetime.now(UTC),
    }


async def serve_tools_panel(
    *,
    request: Request,
    qnr_id: UUID,
    user: User,
    db: AsyncSession,
) -> HTMLResponse:
    """Full Tools tab (lazy-loaded on ``?view=tools``). Runs strict checks on each load."""
    qnr = await _load_owned_qnr(db, qnr_id, user)
    ctx = await _tools_panel_context(db=db, qnr=qnr)
    ctx["request"] = request
    return templates.TemplateResponse("qnr/_editor_tools_panel.html", ctx)


async def serve_tools_checks(
    *,
    request: Request,
    qnr_id: UUID,
    user: User,
    db: AsyncSession,
) -> HTMLResponse:
    """HTMX fragment: re-run strict checks + OOB deploy row refresh."""
    qnr = await _load_owned_qnr(db, qnr_id, user)
    ctx = await _tools_panel_context(db=db, qnr=qnr)
    ctx["request"] = request
    return templates.TemplateResponse("qnr/_tools_checks_fragment.html", ctx)
