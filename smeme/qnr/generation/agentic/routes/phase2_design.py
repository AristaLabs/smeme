"""Phase 2 design routes: retry design generation, submit design."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from langgraph.types import Command

from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.qnr.generation.agentic.routes._helpers import (
    logger,
    render_wizard_step_safe,
    templates,
    wizard_generation_error_recoverable,
    wizard_should_cleanup_generation,
    wizard_submit_failure_message,
)
from smeme.qnr.generation.agentic.services import checkpoint_manager
from smeme.qnr.generation.agentic.telemetry import (
    WizardPhaseTimer,
    track_phase_error,
    track_phase_submit,
    track_wizard_complete,
)
from smeme.qnr.generation.agentic.workflow import get_compiled_workflow

router = APIRouter()


def _redirect_to_editor_response(request: Request, qnr_id: str) -> HTMLResponse | RedirectResponse:
    editor_url = f"/qnr/{qnr_id}/editor"
    if request.headers.get("HX-Request", "").lower() == "true":
        response = HTMLResponse(content="", status_code=200)
        response.headers["HX-Redirect"] = editor_url
        return response
    return RedirectResponse(url=editor_url, status_code=303)


@router.post("/retry-design", response_class=HTMLResponse)
async def retry_design_generation(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
):
    """Retry LLM generation if design failed previously."""
    logger.info(
        "Retrying design generation",
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

    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values

        resume_state = {
            "questionnaire_design": "",
            "design_source": "",
            "design_raw": None,
            "user_prompt": state.get("user_prompt"),
            "research_context_edited": state.get("research_context_edited", ""),
            "possible_conclusions_edited": state.get("possible_conclusions_edited", ""),
        }

        await workflow.ainvoke(Command(resume=resume_state), config)

        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values

        phase_history = state.get("phase_history", [])
        completed_phases = []
        for transition in phase_history:
            from_phase = transition.get("from")
            if from_phase and from_phase not in completed_phases:
                completed_phases.append(from_phase)

        return render_wizard_step_safe(
            request=request,
            main_content_template="qnr/generation/_main_design_edit.html",
            context={
                "thread_id": thread_id,
                "questionnaire_design": state.get("questionnaire_design", ""),
                "design_source": state.get("design_source", "unknown"),
                "design_token_usage": state.get("design_token_usage"),
                "current_phase": "design",
            },
            user=user,
            thread_id=thread_id,
        )
    except Exception as e:
        logger.error(
            "Failed to retry design generation",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        return templates.TemplateResponse(
            "qnr/generation/_error.html",
            {
                "request": request,
                "error_message": f"Retry failed: {str(e)}. Please try again or edit manually.",
                "error_recoverable": True,
            },
        )


@router.post("/design/submit", response_class=HTMLResponse)
async def submit_design(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
    questionnaire_design_edited: str = Form(...),
):
    """
    Resume workflow after design edit.

    Passes the edited design text directly to interrupt() via Command(resume=...).
    Runs Phase 3 (build + validate + fix + save) to completion.
    """
    logger.info(
        "Resuming with edited design",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "design_length": len(questionnaire_design_edited),
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

    await checkpoint_manager.update_phase(db=db, thread_id=thread_id, phase="build")

    phase_timer = WizardPhaseTimer()

    try:
        workflow = await get_compiled_workflow()

        result = await workflow.ainvoke(
            Command(resume=questionnaire_design_edited),
            config,
        )

        interrupts = result.get("__interrupt__", [])
        if interrupts:
            logger.error("Unexpected interrupt in Phase 3")
            return templates.TemplateResponse(
                "qnr/generation/_error.html",
                {
                    "request": request,
                    "error_message": "Unexpected workflow pause. Please try again.",
                    "error_recoverable": True,
                },
            )

        if result.get("error"):
            return templates.TemplateResponse(
                "qnr/generation/_error.html",
                {
                    "request": request,
                    "error_message": result["error"],
                    "error_recoverable": result.get("error_recoverable", True),
                },
            )

        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values
        qnr_id = state.get("qnr_id")

        generation = await checkpoint_manager.get_generation_by_thread_id(db, thread_id)

        await track_phase_submit(
            db,
            user_id=user.id,
            phase="design",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            generation_id=generation.id if generation else None,
        )
        await track_phase_submit(
            db,
            user_id=user.id,
            phase="build",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            generation_id=generation.id if generation else None,
        )

        final_status = state.get("final_status", "has_errors")
        if qnr_id:
            await track_wizard_complete(
                db,
                user_id=user.id,
                thread_id=thread_id,
                duration_ms=phase_timer.duration_ms,
                qnr_id=str(qnr_id),
                generation_id=generation.id if generation else None,
                final_status=final_status,
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)

            logger.info(
                "QNR generation saved, redirecting to editor",
                extra={
                    "user_id": str(user.id),
                    "thread_id": thread_id,
                    "qnr_id": qnr_id,
                    "final_status": final_status,
                },
            )

            return _redirect_to_editor_response(request, str(qnr_id))

        return templates.TemplateResponse(
            "qnr/generation/_build_error.html",
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
            phase="design",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            error_message=str(e),
        )
        logger.error(
            "Design submission failed",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        is_recoverable = wizard_generation_error_recoverable(e)
        gen = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)

        if wizard_should_cleanup_generation(e):
            logger.info(
                "Fatal error during design submission, cleaning up generation",
                extra={"thread_id": thread_id, "error": str(e)},
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)

        return templates.TemplateResponse(
            "qnr/generation/_error.html",
            {
                "request": request,
                "error_message": wizard_submit_failure_message(e, recoverable=is_recoverable),
                "error_recoverable": is_recoverable,
                "generation_id": str(gen.id) if gen else None,
            },
        )
