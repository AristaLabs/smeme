"""QNR Viewer Routes - Read-only graph visualization endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.users import current_active_user
from smeme.core.database import get_db
from smeme.core.models import User
from smeme.core.templates import templates  # Shared templates with custom filters
from smeme.qnr.helpers.db_queries import get_qnr_by_id
from smeme.qnr.viewer.editor_view import (
    EDITOR_VIEW_COOKIE,
    resolve_editor_view,
    should_persist_editor_view,
)
from smeme.qnr.viewer.layout import ordered_nodes_for_checklist
from smeme.qnr.viewer.workflow import build_viewer_workflow
from smeme.qnr.viewer.workflow_config import build_viewer_workflow_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qnr", tags=["qnr_viewer"])


# Build workflow once at module load
viewer_workflow = build_viewer_workflow()


# =============================================================================
# Type Aliases for Dependency Injection
# =============================================================================

CurrentUser = Annotated[User, Depends(current_active_user)]
AsyncSessionDep = Annotated[AsyncSession, Depends(get_db)]


# =============================================================================
# Viewer Routes
# =============================================================================


@router.get("/{qnr_id}/editor", response_class=HTMLResponse)
async def view_editor_page(
    request: Request,
    qnr_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    view: str | None = None,
) -> HTMLResponse:
    """
    Render DTGraph editor page (read-only visualization).

    This is the main entry point for the editor interface.
    Runs the Viewer Workflow to generate the visualization.
    """
    logger.info("Editor page requested", extra={"qnr_id": str(qnr_id), "user_id": str(user.id)})

    # Load QNR for authorization check
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Authorization: Check archived status
    if qnr.is_archived and qnr.author_id != user.id:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found",  # Don't reveal archived status to non-authors
        )

    # Authorization: Only author can view private QNRs
    if not qnr.is_public and qnr.author_id != user.id:
        raise HTTPException(
            status_code=403, detail="Private workflows can only be accessed by their author"
        )

    if qnr.author_id == user.id:
        from smeme.billing.access_policy import raise_if_workflow_edit_denied

        raise_if_workflow_edit_denied(user, qnr)

    is_owner = qnr.author_id == user.id
    editor_view = resolve_editor_view(
        query_view=view,
        cookie_view=request.cookies.get(EDITOR_VIEW_COOKIE),
        allow_lexicon=False,
        allow_tools=is_owner,
    )
    show_deploy_success = request.query_params.get("reasoning_compiled") == "1"

    from smeme.core.config import settings
    from smeme.mcp.urls import mcp_connect_template_context

    mcp_connect_ctx = {
        "mcp_enabled": settings.mcp_enabled,
        **mcp_connect_template_context(settings),
    }

    # Run Viewer Workflow
    try:
        result = await viewer_workflow.ainvoke(
            {
                "qnr_id": qnr_id,
                "user_id": user.id,
                "selected_node_id": None,
            },
            config=build_viewer_workflow_config(
                db,
                request=request,
                full_page=True,
                user=user,
                editor_view=editor_view,
                show_deploy_success=show_deploy_success,
                **mcp_connect_ctx,
            ),
        )

        rendered_html = result.get("rendered_html", "<p>Error rendering editor</p>")

        logger.info("Editor page rendered", extra={"qnr_id": str(qnr_id), "user_id": str(user.id)})

        response = HTMLResponse(content=rendered_html)
        if should_persist_editor_view(view):
            response.set_cookie(
                EDITOR_VIEW_COOKIE,
                editor_view,
                max_age=365 * 24 * 3600,
                samesite="lax",
                path="/",
            )
        return response

    except Exception as e:
        logger.error(
            f"Error rendering editor page: {e}",
            extra={"qnr_id": str(qnr_id), "user_id": str(user.id)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Error rendering editor page") from e


@router.post("/editor/select_node_with_qnr", response_class=HTMLResponse)
async def select_node_with_qnr(
    request: Request,
    node_id: Annotated[str, Form()],
    qnr_id: Annotated[UUID, Form()],
    user: CurrentUser,
    db: AsyncSessionDep,
) -> HTMLResponse:
    """
    Select a node in the editor with explicit qnr_id.

    This is the working version that includes qnr_id in the form data.
    """
    logger.info(
        "Node selected in editor",
        extra={"qnr_id": str(qnr_id), "node_id": node_id, "user_id": str(user.id)},
    )

    # Authorization check
    qnr = await get_qnr_by_id(db, qnr_id)
    if not qnr:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check archived status
    if qnr.is_archived and qnr.author_id != user.id:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found",  # Don't reveal archived status to non-authors
        )

    if not qnr.is_public and qnr.author_id != user.id:
        raise HTTPException(
            status_code=403, detail="Private workflows can only be accessed by their author"
        )

    # Run Viewer Workflow with selection
    try:
        result = await viewer_workflow.ainvoke(
            {
                "qnr_id": qnr_id,
                "user_id": user.id,
                "selected_node_id": node_id,
            },
            config=build_viewer_workflow_config(db, request=request),
        )

        rendered_html = result.get("rendered_html", "<p>Error rendering editor</p>")

        # Also render graph view pane for OOB swap to keep empty/legend states consistent
        graph_view_html = templates.env.get_template("qnr/_graph_view_content.html").render(
            {
                "graph": result["graph"],
                "visualization": result.get("visualization"),
                "qnr_id": qnr_id,
                "selected_node_id": node_id,
                "is_public": result.get("is_public", False),
                "is_read_only": result.get("is_public", False),
            }
        )

        checklist_ordered_nodes = ordered_nodes_for_checklist(result["graph"])
        checklist_template = templates.env.get_template("qnr/_graph_checklist.html")
        graph_checklist_html = checklist_template.render(
            {
                "graph": result["graph"],
                "qnr_id": qnr_id,
                "selected_node_id": node_id,
                "node_validation_status": result.get("node_validation_status", {}),
                "checklist_ordered_nodes": checklist_ordered_nodes,
            }
        )

        # Combine side panel + OOB swaps for graph and checklist views
        combined_html = f"""
        {rendered_html}
        <div id="view-graph" hx-swap-oob="innerHTML">
            {graph_view_html}
        </div>
        <div id="view-checklist" hx-swap-oob="innerHTML">
            {graph_checklist_html}
        </div>
        """

        logger.info(
            "Editor re-rendered with node selection",
            extra={"qnr_id": str(qnr_id), "node_id": node_id, "user_id": str(user.id)},
        )

        return HTMLResponse(content=combined_html)

    except Exception as e:
        logger.error(
            f"Error re-rendering editor with selection: {e}",
            extra={"qnr_id": str(qnr_id), "node_id": node_id, "user_id": str(user.id)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Error rendering editor") from e
