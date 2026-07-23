"""DecisionTree routes for questionnaire interaction."""

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.users import current_active_user
from smeme.core.callout_html import render_callout_html
from smeme.core.config import settings
from smeme.core.database import get_db
from smeme.core.models import DecisionTree, DecisionTreeSession, ReasoningCompiledArtifact, User
from smeme.core.templates import templates
from smeme.mcp.urls import mcp_connect_template_context
from smeme.decision_tree.helpers.db_queries import (
    get_or_create_session,
    get_decision_tree_by_id,
    get_session_by_id,
    save_session,
)
from smeme.decision_tree.helpers.export import build_decision_tree_export, export_download_filename
from smeme.decision_tree.helpers.workflow_delete import DELETE_CONFIRM_PHRASE
from smeme.decision_tree.workflow import build_decision_tree_session_workflow
from smeme.decision_tree.workflow_state import DecisionTreeSessionState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/decision-trees", tags=["decision_tree"])


async def _assistant_tools_row_map(db: AsyncSession, qnrs: list[DecisionTree]) -> dict[UUID, str]:
    """Per-DecisionTree tools column: ``live`` | ``not_built`` | ``stale`` (hash vs artifact)."""
    from smeme.reasoning.assistant_tools_row_status import reasoning_tools_row_state

    if not qnrs:
        return {}
    ids = [q.id for q in qnrs]
    result = await db.execute(
        select(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.decision_tree_id.in_(ids))
    )
    by_q = {a.decision_tree_id: a for a in result.scalars().all()}
    return {q.id: reasoning_tools_row_state(q, by_q.get(q.id)) for q in qnrs}


async def _fetch_dashboard_decision_trees(db: AsyncSession, user_id: UUID) -> list[DecisionTree]:
    """Current-version QNRs for the author (non-archived)."""
    authored_result = await db.execute(
        select(DecisionTree)
        .where(
            DecisionTree.author_id == user_id,
            DecisionTree.is_current == True,  # noqa: E712 - SQLAlchemy comparison
            DecisionTree.is_archived == False,  # noqa: E712
        )
        .order_by(DecisionTree.updated_at.desc())
    )
    return list(authored_result.scalars().all())


async def _prune_completed_dashboard_generations(
    db: AsyncSession,
    current_user: User,
    generations: list[Any],
) -> list[Any]:
    """Drop stale generation rows whose checkpoints already saved a workflow."""
    if not generations:
        return generations

    from smeme.decision_tree.generation.agentic.services import checkpoint_manager
    from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

    workflow = await get_compiled_workflow()
    active_generations: list[Any] = []
    for generation in generations:
        config = {
            "configurable": {
                "thread_id": generation.langgraph_thread_id,
                "user_id": current_user.id,
                "db": db,
            }
        }
        try:
            state_snapshot = await workflow.aget_state(config)
        except Exception:
            logger.warning(
                "Could not inspect in-progress generation checkpoint for dashboard",
                extra={
                    "generation_id": str(generation.id),
                    "thread_id": generation.langgraph_thread_id,
                    "user_id": str(current_user.id),
                },
                exc_info=True,
            )
            active_generations.append(generation)
            continue

        state = state_snapshot.values or {}
        decision_tree_id = state.get("decision_tree_id")
        if decision_tree_id:
            logger.info(
                "Pruning completed generation row from dashboard",
                extra={
                    "generation_id": str(generation.id),
                    "thread_id": generation.langgraph_thread_id,
                    "decision_tree_id": decision_tree_id,
                    "final_status": state.get("final_status"),
                },
            )
            await checkpoint_manager.complete_generation(
                db=db,
                thread_id=generation.langgraph_thread_id,
            )
            continue

        active_generations.append(generation)

    return active_generations


async def _dashboard_page_context(
    db: AsyncSession,
    current_user: User,
    request: Request,
    *,
    success_message: str | None = None,
) -> dict[str, Any]:
    """Single context dict for every ``decision_tree/dashboard.html`` render (HTMX full swaps included)."""
    from smeme.decision_tree.generation.agentic.services import checkpoint_manager

    decision_trees = await _fetch_dashboard_decision_trees(db, current_user.id)
    tools_row = await _assistant_tools_row_map(db, decision_trees)
    in_progress_generations = await checkpoint_manager.list_user_generations(
        db=db,
        user_id=current_user.id,
    )
    in_progress_generations = await _prune_completed_dashboard_generations(
        db,
        current_user,
        in_progress_generations,
    )
    show_deploy_success = request.query_params.get("deployed") == "1"
    show_generation_deleted = request.query_params.get("generation_deleted") == "1"
    from smeme.billing.access_policy import (
        billing_lifecycle_context,
        count_active_root_workflows,
        is_decision_tree_dashboard_grayed,
    )
    from smeme.billing.providers import hosted_quota_enforcement_enabled
    from smeme.billing.quota import check_wizard_start_block
    from smeme.billing.usage import build_usage_summary, mcp_weighted_by_decision_tree_month

    mcp_connect_ctx = {
        "mcp_enabled": settings.mcp_enabled,
        **mcp_connect_template_context(settings),
    }
    usage_summary = await build_usage_summary(db, current_user)
    wizard_start_block = await check_wizard_start_block(
        db,
        current_user,
        in_progress_count=len(in_progress_generations),
    )
    mcp_calls_by_decision_tree = await mcp_weighted_by_decision_tree_month(db, current_user)
    active_root_count = await count_active_root_workflows(db, current_user.id)
    billing_ctx = billing_lifecycle_context(current_user, active_root_count=active_root_count)
    decision_tree_grayed = {q.id: is_decision_tree_dashboard_grayed(current_user, q) for q in decision_trees}
    show_upgraded = request.query_params.get("upgraded") == "true"
    ctx: dict[str, Any] = {
        "request": request,
        "user": current_user,
        "decision_trees": decision_trees,
        "in_progress_generations": in_progress_generations,
        "tools_row": tools_row,
        "active_page": "dashboard",
        "stripe_configured": settings.stripe_configured,
        "quota_enforcement_enabled": hosted_quota_enforcement_enabled(),
        "usage_summary": usage_summary,
        "wizard_start_block": wizard_start_block,
        "mcp_calls_by_decision_tree": mcp_calls_by_decision_tree,
        "show_upgraded": show_upgraded,
        "show_deploy_success": show_deploy_success,
        "show_generation_deleted": show_generation_deleted,
        "decision_tree_grayed": decision_tree_grayed,
        **billing_ctx,
        **mcp_connect_ctx,
    }
    if success_message is not None:
        ctx["success_message"] = success_message
    return ctx


def _dashboard_no_store_headers(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ============================================================================
# Dashboard
# ============================================================================


@router.post("/mcp/discoverable", response_class=HTMLResponse)
async def mcp_post_discoverable(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
    decision_tree_id: Annotated[UUID, Form()],
    enabled: Annotated[str | None, Form()] = None,
    return_next: Annotated[str | None, Form()] = None,
):
    """Owner-only: opt a compiled DecisionTree into MCP list + evaluate-by-id."""
    result = await db.execute(select(DecisionTree).where(DecisionTree.id == decision_tree_id))
    decision_tree = result.scalar_one_or_none()
    if decision_tree is None or decision_tree.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this workflow.")
    from smeme.billing.access_policy import raise_if_workflow_edit_denied

    raise_if_workflow_edit_denied(current_user, decision_tree)
    decision_tree.mcp_discoverable = enabled in ("1", "true", "on", "yes")
    db.add(decision_tree)
    await db.commit()
    if (
        request.headers.get("HX-Request") or request.headers.get("hx-request") or ""
    ).lower() == "true":
        return HTMLResponse("", status_code=200)
    if return_next == "tools":
        redirect_url = f"/decision-trees/{decision_tree_id}/editor?view=tools"
    else:
        redirect_url = "/decision-trees/dashboard#mcp-listed"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def decision_tree_dashboard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
):
    """
    Creator dashboard: own QNRs in one table, entry to agentic generation.

    Archived current versions are listed separately for restore.
    """
    ctx = await _dashboard_page_context(db, current_user, request)
    response = templates.TemplateResponse("decision_tree/dashboard.html", ctx)
    return _dashboard_no_store_headers(response)


# ============================================================================
# Start DecisionTree Session
# ============================================================================


@router.post("/start", response_class=HTMLResponse)
async def start_decision_tree(
    request: Request,
    decision_tree_id: Annotated[UUID, Form(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Start or resume a DecisionTree session."""
    logger.info(f"User {current_user.id} starting DecisionTree {decision_tree_id}")

    # Verify DecisionTree exists
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Workflow not found")

    is_author = decision_tree.author_id == current_user.id

    # Block starting sessions on archived QNRs (unless author)
    if decision_tree.is_archived and not is_author:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found",  # Don't reveal archived status
        )

    # Only authors can start private workflows. Public viewer routes already
    # enforce this; the session creation path must match that visibility gate.
    if not decision_tree.is_public and not is_author:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found",  # Don't reveal private workflow ids
        )

    # Block answering QNRs with validation errors
    # Authors can edit broken QNRs but no one can answer them until errors are fixed
    from smeme.decision_tree.helpers.db_queries import parse_graph_data
    from smeme.decision_tree.helpers.validation import validate_graph_for_editing

    graph = parse_graph_data(decision_tree)
    validation_result = validate_graph_for_editing(graph)

    if not validation_result["is_valid"]:
        error_count = len(validation_result["errors"])

        if is_author:
            error_html = f"""
            <div class="max-w-2xl mx-auto mt-8">
            {
                render_callout_html(
                    title="Cannot Start: Workflow Has Validation Errors",
                    body=(
                        f'<p class="mb-4">This workflow has <strong>{error_count} validation error(s)</strong> '
                        f"that must be fixed before it can be answered.</p>"
                        f'<div class="flex gap-3">'
                        f'<a href="/decision-trees/{decision_tree_id}/editor" '
                        f'class="px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white font-medium rounded-lg">'
                        f"Open in Editor</a>"
                        f'<a href="/decision-trees/dashboard" '
                        f'class="px-4 py-2 bg-ui-surface-hover hover:bg-ui-line text-ui-ink-secondary font-medium rounded-lg">'
                        f"Back to Dashboard</a></div>"
                    ),
                    type="error",
                )
            }
            </div>
            """
        else:
            error_html = f"""
            <div class="max-w-2xl mx-auto mt-8">
            {
                render_callout_html(
                    title="Workflow Temporarily Unavailable",
                    body=(
                        '<p class="mb-4">This workflow is currently being updated by its author. '
                        "Please try again later.</p>"
                        '<a href="/decision-trees/dashboard" '
                        'class="px-4 py-2 bg-ui-surface-hover hover:bg-ui-line text-ui-ink-secondary font-medium rounded-lg inline-block">'
                        "Back to Dashboard</a>"
                    ),
                    type="warning",
                )
            }
            </div>
            """

        logger.warning(
            "Blocked DecisionTree start due to validation errors",
            extra={
                "decision_tree_id": str(decision_tree_id),
                "user_id": str(current_user.id),
                "error_count": error_count,
                "is_author": is_author,
            },
        )

        return HTMLResponse(content=error_html)

    # Get or create session
    session = await get_or_create_session(db, current_user.id, decision_tree_id)

    # Execute workflow
    result_html = await execute_decision_tree_session_workflow(
        db=db,
        decision_tree_id=str(decision_tree_id),
        user_id=str(current_user.id),
        session=session,
        navigation_intent=None,  # First load
    )

    return HTMLResponse(content=result_html)


# ============================================================================
# Submit Answer
# ============================================================================


@router.post("/submit_answer", response_class=HTMLResponse)
async def submit_answer(
    session_id: Annotated[UUID, Form(...)],
    question_node_id: Annotated[str, Form(...)],
    answer_text: Annotated[str, Form(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
    finish: Annotated[bool, Form()] = False,
):
    """Submit answer to a question and get next question."""
    logger.info(
        f"User {current_user.id} submitting answer for session {session_id}, "
        f"question {question_node_id}"
    )

    # Get session (for validation and workflow)
    session = await get_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify ownership
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Save answer to session
    if session.user_responses is None:
        session.user_responses = {}
    session.user_responses[question_node_id] = answer_text
    await save_session(db, session)

    # Determine navigation intent
    intent = "finish" if finish else "next"

    # Execute workflow
    result_html = await execute_decision_tree_session_workflow(
        db=db,
        decision_tree_id=str(session.decision_tree_id),
        user_id=str(current_user.id),
        session=session,
        navigation_intent=intent,
    )

    return HTMLResponse(content=result_html)


# ============================================================================
# Navigate (Next/Previous/Skip)
# ============================================================================


@router.post("/navigate", response_class=HTMLResponse)
async def navigate(
    session_id: Annotated[UUID, Form(...)],
    direction: Annotated[str, Form(...)],  # "next", "previous", "skip", "review"
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
):
    """Navigate between questions."""
    logger.info(f"User {current_user.id} navigating: {direction}")

    # Get session
    session = await get_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify ownership
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Execute workflow with navigation intent
    result_html = await execute_decision_tree_session_workflow(
        db=db,
        decision_tree_id=str(session.decision_tree_id),
        user_id=str(current_user.id),
        session=session,
        navigation_intent=direction,
    )

    return HTMLResponse(content=result_html)


# ============================================================================
# Workflow export (owner download)
# ============================================================================
# ============================================================================
# Workflow export (owner download)
# ============================================================================


@router.get("/{decision_tree_id}/download")
async def download_workflow(
    decision_tree_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
) -> JSONResponse:
    """Owner-only: download the current saved workflow graph as JSON."""
    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if decision_tree is None or decision_tree.author_id != current_user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    filename = export_download_filename(decision_tree)
    return JSONResponse(
        content=build_decision_tree_export(decision_tree),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# DecisionTree Management (Permanent delete)
# ============================================================================


async def _delete_modal_context(
    db: AsyncSession,
    decision_tree_id: UUID,
    current_user: User,
) -> tuple[DecisionTree, int] | HTMLResponse:
    """Load DecisionTree for delete modals; return error HTML on validation failure."""
    from smeme.decision_tree.helpers.db_queries import get_version_family_from_db

    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        return HTMLResponse(
            content="<div class='alert alert-error'>Workflow not found</div>", status_code=404
        )

    if decision_tree.author_id != current_user.id:
        return HTMLResponse(
            content="<div class='alert alert-error'>You can only delete your own workflows</div>",
            status_code=403,
        )

    if not decision_tree.is_current:
        return HTMLResponse(
            content=(
                "<div class='alert alert-error'>"
                "Only the current version can be deleted. "
                "Delete from the current version to remove the entire family."
                "</div>"
            ),
            status_code=400,
        )

    family = await get_version_family_from_db(db, decision_tree)
    return decision_tree, len(family)


@router.get("/{decision_tree_id}/delete-confirm", response_class=HTMLResponse)
async def delete_decision_tree_confirm(
    decision_tree_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
) -> HTMLResponse:
    """Step 1: explain permanent delete scope."""
    loaded = await _delete_modal_context(db, decision_tree_id, current_user)
    if isinstance(loaded, HTMLResponse):
        return loaded

    decision_tree, version_count = loaded
    return templates.TemplateResponse(
        request=request,
        name="decision_tree/_delete_confirm_step1.html",
        context={"decision_tree": decision_tree, "version_count": version_count},
    )


@router.get("/{decision_tree_id}/delete-confirm-phrase", response_class=HTMLResponse)
async def delete_decision_tree_confirm_phrase(
    decision_tree_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
) -> HTMLResponse:
    """Step 2: typed confirmation phrase."""
    loaded = await _delete_modal_context(db, decision_tree_id, current_user)
    if isinstance(loaded, HTMLResponse):
        return loaded

    decision_tree, _version_count = loaded
    return templates.TemplateResponse(
        request=request,
        name="decision_tree/_delete_confirm_step2.html",
        context={
            "decision_tree": decision_tree,
            "confirm_phrase": DELETE_CONFIRM_PHRASE,
        },
    )


@router.delete("/{decision_tree_id}/delete", response_class=HTMLResponse)
async def delete_decision_tree(
    decision_tree_id: UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(current_active_user)],
    confirm_phrase: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """Permanently delete the workflow version family."""
    from smeme.decision_tree.helpers.workflow_delete import delete_workflow_family

    if confirm_phrase.strip() != DELETE_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f'Type "{DELETE_CONFIRM_PHRASE}" to confirm permanent delete.',
        )

    decision_tree = await get_decision_tree_by_id(db, decision_tree_id)
    if not decision_tree:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if decision_tree.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own workflows")

    if not decision_tree.is_current:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only the current version can be deleted. "
                "Delete from the current version to remove the entire family."
            ),
        )

    title = decision_tree.title
    logger.info(
        f"Deleting DecisionTree family permanently: {title}",
        extra={"decision_tree_id": str(decision_tree_id), "user_id": str(current_user.id)},
    )

    family = await delete_workflow_family(db, decision_tree, author_id=current_user.id)
    await db.commit()

    logger.info(
        "DecisionTree family deleted permanently",
        extra={
            "root_decision_tree_id": str(decision_tree_id),
            "deleted_count": len(family),
            "user_id": str(current_user.id),
        },
    )

    ctx = await _dashboard_page_context(
        db,
        current_user,
        request,
        success_message=f'Workflow "{title}" was permanently deleted.',
    )
    response = templates.TemplateResponse(request=request, name="decision_tree/dashboard.html", context=ctx)
    return _dashboard_no_store_headers(response)


# ============================================================================
# Workflow Execution Helper
# ============================================================================


async def execute_decision_tree_session_workflow(
    db: AsyncSession,
    decision_tree_id: str,
    user_id: str,
    session: DecisionTreeSession,
    navigation_intent: str | None = None,
) -> str:
    """
    Execute the DecisionTree workflow and return rendered HTML.

    Args:
        db: Database session (passed to workflow via config)
        decision_tree_id: DecisionTree UUID as string
        user_id: User UUID as string
        session: DecisionTreeSession instance
        navigation_intent: Navigation direction (None, "next", "previous", "skip", "finish", "review")

    Returns:
        Rendered HTML string
    """
    logger.info(f"Executing workflow: decision_tree={decision_tree_id}, user={user_id}, intent={navigation_intent}")

    # Build workflow (no db parameter needed)
    workflow = build_decision_tree_session_workflow()

    # Prepare initial state
    inputs: DecisionTreeSessionState = {
        "decision_tree_id": decision_tree_id,
        "user_id": user_id,
        "session": session,
    }

    # Add navigation intent if provided
    if navigation_intent:
        inputs["navigation_intent"] = navigation_intent

    # Execute workflow with db passed via config
    try:
        result = await workflow.ainvoke(inputs, config={"configurable": {"db": db}})
        rendered = result.get("rendered_output", "<p>Error: no output</p>")
        logger.info("Workflow execution completed successfully")
        return rendered

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
        return f"<p>Error: {str(e)}</p>"
