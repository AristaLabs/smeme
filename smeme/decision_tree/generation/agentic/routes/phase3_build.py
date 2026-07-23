"""Phase 3 build routes: retry build generation."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from langgraph.types import Command

from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.decision_tree.generation.agentic.routes._helpers import logger, templates
from smeme.decision_tree.generation.agentic.services import checkpoint_manager
from smeme.decision_tree.generation.agentic.telemetry import (
    WizardPhaseTimer,
    track_phase_error,
    track_phase_submit,
    track_wizard_complete,
)
from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

router = APIRouter()


def _redirect_to_editor_response(
    request: Request, decision_tree_id: str
) -> HTMLResponse | RedirectResponse:
    editor_url = f"/decision-trees/{decision_tree_id}/editor"
    if request.headers.get("HX-Request", "").lower() == "true":
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = editor_url
        return response
    return RedirectResponse(url=editor_url, status_code=303)


@router.post("/retry-build", response_class=HTMLResponse)
async def retry_build_generation(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
):
    """Retry LLM generation if build failed previously."""
    logger.info(
        "Retrying build generation",
        extra={"user_id": str(user.id), "thread_id": thread_id},
    )

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": str(user.id),
            "db": db,
            "openai_client": openai_client,
        }
    }

    phase_timer = WizardPhaseTimer()

    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values

        resume_state = {
            "generated_graph": {},
            "build_source": "",
            "build_raw": None,
            "validation_errors": [],
            "validation_warnings": [],
            "fix_source": "no_fix_needed",
            "fix_iteration_count": 0,
            "fixes_applied": [],
            "final_status": "",
            "user_prompt": state.get("user_prompt"),
            "decision_tree_design_edited": state.get("decision_tree_design_edited", ""),
        }

        await workflow.ainvoke(Command(resume=resume_state), config)

        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values

        final_status = state.get("final_status", "has_errors")
        decision_tree_id = state.get("decision_tree_id")

        if decision_tree_id:
            generation = await checkpoint_manager.get_generation_by_thread_id(db, thread_id)
            await track_phase_submit(
                db,
                user_id=user.id,
                phase="build",
                thread_id=thread_id,
                duration_ms=phase_timer.duration_ms,
                generation_id=generation.id if generation else None,
                action="retry",
            )
            await track_wizard_complete(
                db,
                user_id=user.id,
                thread_id=thread_id,
                duration_ms=phase_timer.duration_ms,
                decision_tree_id=str(decision_tree_id),
                generation_id=generation.id if generation else None,
                final_status=final_status,
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)
            logger.info(
                "Retry build saved workflow, redirecting to editor",
                extra={
                    "thread_id": thread_id,
                    "decision_tree_id": decision_tree_id,
                    "final_status": final_status,
                },
            )
            return _redirect_to_editor_response(request, str(decision_tree_id))

        return templates.TemplateResponse(
            "decision_tree/generation/_build_error.html",
            {
                "request": request,
                "thread_id": thread_id,
                "build_source": state.get("build_source", "unknown"),
                "validation_errors": state.get("validation_errors", []),
                "can_retry": True,
                "current_phase": "build",
            },
        )

    except Exception as e:
        await track_phase_error(
            db,
            user_id=user.id,
            phase="build",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            error_message=str(e),
            action="retry",
        )
        logger.error(
            "Failed to retry build generation",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": f"Retry failed: {str(e)}. Please try again.",
                "error_recoverable": True,
            },
        )
