"""Utility routes: list generations, view generation, resume generation, legacy factors."""

import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.decision_tree.generation.agentic.routes._helpers import (
    logger,
    render_generation_layout,
    research_edit_template_context,
    templates,
    track_wizard_resume_enter,
)
from smeme.decision_tree.generation.agentic.services import checkpoint_manager
from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

router = APIRouter()


def _redirect_to_editor_response(request: Request, decision_tree_id: str) -> HTMLResponse | RedirectResponse:
    """Redirect from either HTMX flows or normal browser navigation."""
    editor_url = f"/decision-trees/{decision_tree_id}/editor"
    if request.headers.get("HX-Request", "").lower() == "true":
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = editor_url
        return response
    return RedirectResponse(url=editor_url, status_code=303)


@router.get("/generations/{generation_id}", response_class=HTMLResponse)
async def view_generation(
    request: Request,
    generation_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
):
    """
    Direct link to a specific generation (deep linking support).

    Loads the generation and renders it in the two-panel layout.
    """
    generation = await checkpoint_manager.get_generation(
        db=db,
        generation_id=generation_id,
        user_id=user.id,
    )

    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")

    thread_id = generation.langgraph_thread_id

    logger.info(
        "Viewing generation via direct link",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "generation_id": str(generation_id),
            "current_phase": generation.current_phase,
        },
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
            "db": db,
            "openai_client": openai_client,
            "tavily_client": None,
        }
    }

    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)

        if not state_snapshot.values or len(state_snapshot.values) == 0:
            logger.warning(f"Empty checkpoint found for generation {generation_id}")
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": "This generation was started before the persistence system was active. Please start a new generation.",
                    "error_recoverable": False,
                },
            )

        if state_snapshot.next:
            state = state_snapshot.values
            decision_tree_id = state.get("decision_tree_id")
            if decision_tree_id:
                logger.info(
                    "Generation has saved workflow, cleaning up and redirecting to editor",
                    extra={
                        "generation_id": str(generation_id),
                        "decision_tree_id": decision_tree_id,
                        "final_status": state.get("final_status"),
                    },
                )
                await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)
                return _redirect_to_editor_response(request, str(decision_tree_id))

            phase_history = state.get("phase_history", [])
            completed_phases = []
            for transition in phase_history:
                from_phase = transition.get("from")
                if from_phase and from_phase not in completed_phases:
                    completed_phases.append(from_phase)

            if "research_context" in state and not state.get("possible_conclusions"):
                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="research",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="view",
                )

                ctx = research_edit_template_context(
                    thread_id=thread_id,
                    state=state,
                    generation_id=generation.id,
                )
                ctx.update(
                    {
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    }
                )
                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_research_edit.html",
                    context=ctx,
                )

            if "possible_conclusions" in state and not state.get("questionnaire_design"):
                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="conclusions",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="view",
                )

                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_conclusions_edit.html",
                    context={
                        "thread_id": thread_id,
                        "possible_conclusions": state.get("possible_conclusions", ""),
                        "conclusions_source": state.get("conclusions_source", "llm_extracted"),
                        "current_phase": "conclusions",
                        "completed_phases": completed_phases,
                        "phase_history": phase_history,
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    },
                )

            if "questionnaire_design" in state and not state.get("decision_tree_id"):
                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="design",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="view",
                )

                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_design_edit.html",
                    context={
                        "thread_id": thread_id,
                        "questionnaire_design": state.get("questionnaire_design", ""),
                        "design_source": state.get("design_source", "llm_generated"),
                        "design_token_usage": state.get("design_token_usage"),
                        "current_phase": "design",
                        "completed_phases": completed_phases,
                        "phase_history": phase_history,
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    },
                )

            logger.warning(f"Unable to determine phase from state for generation {generation_id}")
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": "Unable to determine generation state. Please start a new generation.",
                    "error_recoverable": False,
                },
            )

        state = state_snapshot.values
        decision_tree_id = state.get("decision_tree_id")
        if decision_tree_id:
            logger.info(
                "Generation already complete, redirecting to editor",
                extra={
                    "generation_id": str(generation_id),
                    "decision_tree_id": decision_tree_id,
                    "final_status": state.get("final_status"),
                },
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)
            return _redirect_to_editor_response(request, str(decision_tree_id))

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": "Generation is in an unexpected state. Please start a new generation.",
                "error_recoverable": False,
            },
        )

    except Exception as e:
        logger.error(
            "Failed to view generation",
            extra={
                "user_id": str(user.id),
                "thread_id": thread_id,
                "generation_id": str(generation_id),
                "error": str(e),
            },
            exc_info=True,
        )

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": "An unexpected error occurred. Please try again.",
                "error_recoverable": True,
            },
        )


@router.post("/generations/{generation_id}/delete")
async def delete_generation(
    request: Request,
    generation_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Abandon an in-progress generation (checkpoints + DB row)."""
    started = time.perf_counter()
    is_htmx = request.headers.get("HX-Request") == "true"

    deleted = await checkpoint_manager.abandon_generation(
        db=db,
        generation_id=generation_id,
        user_id=user.id,
        defer_heavy_cleanup=is_htmx,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Generation not found")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Deleted in-progress generation from dashboard",
        extra={
            "user_id": str(user.id),
            "generation_id": str(generation_id),
            "elapsed_ms": elapsed_ms,
            "htmx": is_htmx,
            "deferred_cleanup": is_htmx,
        },
    )

    if is_htmx:
        in_progress = await checkpoint_manager.list_user_generations(db=db, user_id=user.id)
        return templates.TemplateResponse(
            "decision_tree/_dashboard_in_progress.html",
            {
                "request": request,
                "in_progress_generations": in_progress,
                "show_generation_deleted": True,
            },
        )

    return RedirectResponse(url="/decision-trees/dashboard?generation_deleted=1", status_code=303)


@router.post("/generations/{generation_id}/resume", response_class=HTMLResponse)
async def resume_generation(
    request: Request,
    generation_id: UUID,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
):
    """Resume an in-progress generation from its current checkpoint."""
    generation = await checkpoint_manager.get_generation(
        db=db,
        generation_id=generation_id,
        user_id=user.id,
    )

    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")

    thread_id = generation.langgraph_thread_id

    logger.info(
        "Resuming generation from checkpoint",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "generation_id": str(generation_id),
            "current_phase": generation.current_phase,
        },
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
            "db": db,
            "openai_client": openai_client,
            "tavily_client": None,
        }
    }

    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)

        logger.info(
            f"Retrieved workflow state for resume: "
            f"has_next={bool(state_snapshot.next)}, "
            f"next_nodes={list(state_snapshot.next) if state_snapshot.next else []}, "
            f"state_keys={list(state_snapshot.values.keys()) if state_snapshot.values else []}"
        )

        if not state_snapshot.values or len(state_snapshot.values) == 0:
            logger.warning(
                f"Empty checkpoint found for generation {generation_id} - likely created before persistence was implemented"
            )
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": "This generation was started before the persistence system was active. Please start a new generation.",
                    "error_recoverable": False,
                },
            )

        if state_snapshot.next:
            state = state_snapshot.values
            decision_tree_id = state.get("decision_tree_id")
            if decision_tree_id:
                logger.info(
                    "Resume found saved workflow, cleaning up and redirecting to editor",
                    extra={
                        "generation_id": str(generation_id),
                        "decision_tree_id": decision_tree_id,
                        "final_status": state.get("final_status"),
                    },
                )
                await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)
                return _redirect_to_editor_response(request, str(decision_tree_id))

            logger.debug(
                f"Checking phase conditions: research_context={'research_context' in state}, "
                f"possible_conclusions={state.get('possible_conclusions') is not None}, "
                f"questionnaire_design={state.get('questionnaire_design') is not None}, "
                f"decision_tree_id={state.get('decision_tree_id') is not None}"
            )

            if "research_context" in state and not state.get("possible_conclusions"):
                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="research",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="resume",
                )

                ctx = research_edit_template_context(
                    thread_id=thread_id,
                    state=state,
                    generation_id=generation.id,
                )
                ctx.update(
                    {
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    }
                )
                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_research_edit.html",
                    context=ctx,
                )
            if "possible_conclusions" in state and not state.get("questionnaire_design"):
                phase_history = state.get("phase_history", [])
                completed_phases = []
                for transition in phase_history:
                    from_phase = transition.get("from")
                    if from_phase and from_phase not in completed_phases:
                        completed_phases.append(from_phase)

                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="conclusions",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="resume",
                )

                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_conclusions_edit.html",
                    context={
                        "thread_id": thread_id,
                        "possible_conclusions": state.get("possible_conclusions", ""),
                        "conclusions_source": state.get("conclusions_source", "llm_extracted"),
                        "current_phase": "conclusions",
                        "completed_phases": completed_phases,
                        "phase_history": phase_history,
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    },
                )
            if "questionnaire_design" in state and not state.get("decision_tree_id"):
                phase_history = state.get("phase_history", [])
                completed_phases = []
                for transition in phase_history:
                    from_phase = transition.get("from")
                    if from_phase and from_phase not in completed_phases:
                        completed_phases.append(from_phase)

                await track_wizard_resume_enter(
                    db,
                    user_id=user.id,
                    phase="design",
                    thread_id=thread_id,
                    generation_id=generation.id,
                    source="resume",
                )

                return render_generation_layout(
                    request,
                    user=user,
                    main_content_template="decision_tree/generation/_main_design_edit.html",
                    context={
                        "thread_id": thread_id,
                        "questionnaire_design": state.get("questionnaire_design", ""),
                        "design_source": state.get("design_source", "llm_generated"),
                        "design_token_usage": state.get("design_token_usage"),
                        "current_phase": "design",
                        "completed_phases": completed_phases,
                        "phase_history": phase_history,
                        "thread_status": "Interrupted",
                        "workflow_version": "2.0.0",
                    },
                )
            logger.warning(
                f"Unable to determine phase from state: "
                f"state_keys={list(state.keys())}, "
                f"has_research={'research_context' in state}, "
                f"has_conclusions={'possible_conclusions' in state}, "
                f"has_design={'questionnaire_design' in state}, "
                f"has_decision_tree_id={'decision_tree_id' in state}"
            )
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": "Unable to determine generation state. Please start a new generation.",
                    "error_recoverable": False,
                },
            )

        state = state_snapshot.values
        decision_tree_id = state.get("decision_tree_id")
        logger.info(
            f"No pending interrupts - checking if completed: "
            f"has_decision_tree_id={decision_tree_id is not None}, "
            f"has_research={state.get('research_context') is not None}, "
            f"has_conclusions={state.get('possible_conclusions') is not None}, "
            f"has_design={state.get('questionnaire_design') is not None}, "
            f"state_keys={list(state.keys())}"
        )
        if decision_tree_id:
            logger.info(
                "Resume found completed generation, redirecting to editor",
                extra={
                    "generation_id": str(generation_id),
                    "decision_tree_id": decision_tree_id,
                    "final_status": state.get("final_status"),
                },
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)
            return _redirect_to_editor_response(request, str(decision_tree_id))

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": "Generation is in an unexpected state. Please start a new generation.",
                "error_recoverable": False,
            },
        )

    except Exception as e:
        logger.error(
            "Failed to resume generation",
            extra={
                "user_id": str(user.id),
                "thread_id": thread_id,
                "generation_id": str(generation_id),
                "error": str(e),
            },
            exc_info=True,
        )

        error_msg = "An unexpected error occurred. Please try again."
        if "connection" in str(e).lower() or "ssl" in str(e).lower():
            error_msg = "Connection to database timed out. Please try resuming again."

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": error_msg,
                "error_recoverable": True,
            },
        )
