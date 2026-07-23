"""Phase 1.5 conclusions routes: submit conclusions, retry conclusions extraction."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from langgraph.types import Command, Interrupt

from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.decision_tree.generation.agentic.routes._helpers import (
    logger,
    render_step_template,
    render_wizard_step_safe,
    templates,
    wizard_generation_error_recoverable,
    wizard_should_cleanup_generation,
    wizard_submit_failure_message,
)
from smeme.decision_tree.generation.agentic.services import checkpoint_manager
from smeme.decision_tree.generation.agentic.subgraphs.conclusions import (
    create_conclusions_subgraph,
    merge_conclusions_output,
)
from smeme.decision_tree.generation.agentic.subgraphs.models import (
    ConclusionsSubgraphInput,
    ConclusionsSubgraphOutput,
    InterruptPayload,
)
from smeme.decision_tree.generation.agentic.telemetry import (
    WizardPhaseTimer,
    track_phase_enter,
    track_phase_error,
    track_phase_submit,
)
from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

router = APIRouter()


@router.post("/conclusions/submit", response_class=HTMLResponse)
async def submit_conclusions(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
    possible_conclusions_edited: str = Form(...),
    user_provided: str = Form(default="false"),
):
    """
    Resume workflow after conclusions edit.

    Two paths:
    1. Normal: User edited AI-generated conclusions → Resume workflow with edits
    2. Skip AI: User provided own conclusions → Set state fields directly, skip subgraph
    """
    is_user_provided = user_provided == "true"

    phase_timer = WizardPhaseTimer()

    logger.info(
        "Resuming with edited conclusions",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "conclusions_length": len(possible_conclusions_edited),
            "user_provided": is_user_provided,
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

    workflow = await get_compiled_workflow()

    if is_user_provided:
        logger.info(
            "User provided own conclusions (skipped AI)",
            extra={"user_id": str(user.id), "thread_id": thread_id},
        )

        await workflow.aupdate_state(
            config,
            {
                "possible_conclusions": possible_conclusions_edited,
                "possible_conclusions_edited": possible_conclusions_edited,
                "conclusions_source": "user_provided",
                "conclusions_raw": None,
            },
        )

        await checkpoint_manager.update_phase(db=db, thread_id=thread_id, phase="design")

        result = await workflow.ainvoke(
            Command(resume=possible_conclusions_edited),
            config,
        )
    else:
        await checkpoint_manager.update_phase(db=db, thread_id=thread_id, phase="design")

        result = await workflow.ainvoke(
            Command(resume=possible_conclusions_edited),
            config,
        )

    try:
        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_obj: Interrupt = interrupts[0]

            state_snapshot = await workflow.aget_state(config)
            state = state_snapshot.values

            questionnaire_design = ""
            if isinstance(interrupt_obj.value, dict):
                try:
                    payload = InterruptPayload(**interrupt_obj.value)
                    questionnaire_design = payload.data_to_edit.get("questionnaire_design", "")
                    logger.info(
                        "Using Sprint 6 InterruptPayload format",
                        extra={"phase": payload.phase, "user_id": payload.user_id},
                    )
                except Exception as e:
                    logger.warning(
                        "InterruptPayload validation failed, using legacy format",
                        extra={"error": str(e)},
                    )
                    questionnaire_design = ""
            elif isinstance(interrupt_obj.value, str):
                questionnaire_design = interrupt_obj.value

            if not questionnaire_design:
                questionnaire_design = state.get("questionnaire_design", "")

            logger.info(
                "Workflow interrupted for design edit",
                extra={
                    "user_id": str(user.id),
                    "thread_id": thread_id,
                    "design_length": len(questionnaire_design),
                    "design_source": state.get("design_source", "unknown"),
                },
            )

            phase_history = state.get("phase_history", [])
            completed_phases = []
            for transition in phase_history:
                from_phase = transition.get("from")
                if from_phase and from_phase not in completed_phases:
                    completed_phases.append(from_phase)

            await track_phase_submit(
                db,
                user_id=user.id,
                phase="conclusions",
                thread_id=thread_id,
                duration_ms=phase_timer.duration_ms,
                user_provided=is_user_provided,
            )
            await track_phase_enter(
                db,
                user_id=user.id,
                phase="design",
                thread_id=thread_id,
                source="conclusions_submit",
            )

            gen = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)

            return render_wizard_step_safe(
                request=request,
                main_content_template="decision_tree/generation/_main_design_edit.html",
                context={
                    "thread_id": thread_id,
                    "generation_id": str(gen.id) if gen else None,
                    "questionnaire_design": questionnaire_design,
                    "design_source": state.get("design_source", "unknown"),
                    "design_token_usage": state.get("design_token_usage"),
                    "current_phase": "design",
                },
                user=user,
                thread_id=thread_id,
            )

        if result.get("error"):
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": result["error"],
                    "error_recoverable": result.get("error_recoverable", True),
                },
            )

        logger.warning("Workflow completed without design interrupt - unexpected")
        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": "Unexpected workflow completion. Please try again.",
                "error_recoverable": True,
            },
        )

    except Exception as e:
        await track_phase_error(
            db,
            user_id=user.id,
            phase="conclusions",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            error_message=str(e),
        )
        logger.error(
            "Failed to resume workflow with conclusions",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        is_recoverable = wizard_generation_error_recoverable(e)

        if wizard_should_cleanup_generation(e):
            logger.info(
                "Fatal error during conclusions submission, cleaning up generation",
                extra={"thread_id": thread_id, "error": str(e)},
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)

        gen = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": wizard_submit_failure_message(e, recoverable=is_recoverable),
                "error_recoverable": is_recoverable,
                "generation_id": str(gen.id) if gen else None,
            },
        )


@router.post("/retry-conclusions", response_class=HTMLResponse)
async def retry_conclusions_extraction(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
):
    """Re-run LLM conclusion extraction (same research factors, fresh AI output)."""
    generation = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)
    if not generation or generation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Generation not found")

    logger.info(
        "Retrying conclusions extraction",
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
        state = state_snapshot.values or {}
        if not state:
            raise ValueError("No saved workflow state for this generation")

        research_context = (
            state.get("research_context_edited") or state.get("research_context") or ""
        ).strip()
        if not research_context:
            raise ValueError("Missing approved research context for conclusion extraction")

        conclusions_input = ConclusionsSubgraphInput(
            user_prompt=state["user_prompt"],
            user_id=state["user_id"],
            research_context=research_context,
            user_conclusions=None,
        )
        conclusions_subgraph = create_conclusions_subgraph().compile()
        subgraph_result = await conclusions_subgraph.ainvoke(
            conclusions_input.model_dump(),
            config,
        )
        output = ConclusionsSubgraphOutput(**subgraph_result)
        await workflow.aupdate_state(config, merge_conclusions_output(state, output))

        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values or {}

        return render_step_template(
            request=request,
            main_content_template="decision_tree/generation/_main_conclusions_edit.html",
            context={
                "thread_id": thread_id,
                "possible_conclusions": state.get("possible_conclusions", ""),
                "conclusions_source": state.get("conclusions_source", "unknown"),
                "current_phase": "conclusions",
            },
            user=user,
        )

    except Exception as e:
        logger.error(
            "Failed to retry conclusions extraction",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": f"Retry failed: {str(e)}. Please provide conclusions manually.",
                "error_recoverable": True,
            },
        )
