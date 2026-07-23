"""Phase 1 research routes: new generation form, start, research edit, research submit."""

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from langgraph.types import Command, Interrupt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.config import settings
from smeme.core.dependencies import AsyncSessionDep, CurrentUser, OpenAIClientDep
from smeme.core.models import User
from smeme.core.search import TavilyNotConfiguredError
from smeme.decision_tree.generation.agentic.background import (
    schedule_generation_workflow,
    schedule_retry_research_workflow,
)
from smeme.decision_tree.generation.agentic.brief_models import GenerationBriefInput
from smeme.decision_tree.generation.agentic.file_limits import MAX_FILES_PER_GENERATION, MAX_TOTAL_BYTES
from smeme.decision_tree.generation.agentic.ingestion import (
    parse_uploaded_file,
    prepare_research_corpus,
    validate_and_store_upload,
)
from smeme.decision_tree.generation.agentic.routes._helpers import (
    _render_initial_form,
    logger,
    render_step_template,
    render_wizard_step_safe,
    research_edit_template_context,
    templates,
    wizard_generation_error_recoverable,
    wizard_should_cleanup_generation,
    wizard_submit_failure_message,
)
from smeme.decision_tree.generation.agentic.services import (
    GenerationConcurrencyError,
    WizardStartBlockedError,
    checkpoint_manager,
)
from smeme.decision_tree.generation.agentic.streaming import get_bus, sse_event_stream
from smeme.decision_tree.generation.agentic.subgraphs.models import InterruptPayload
from smeme.decision_tree.generation.agentic.subgraphs.research import EXCLUDE_DOMAINS
from smeme.decision_tree.generation.agentic.telemetry import (
    WizardPhaseTimer,
    track_phase_enter,
    track_phase_error,
    track_phase_submit,
)
from smeme.decision_tree.generation.agentic.user_messages import (
    sanitize_wizard_error_for_user,
    wizard_retry_failed_message,
)
from smeme.decision_tree.generation.agentic.workflow import get_compiled_workflow

router = APIRouter()


async def _wizard_start_context(db: AsyncSession, user: User):
    from smeme.billing.quota import check_wizard_start_block

    in_progress = await checkpoint_manager.list_user_generations(db=db, user_id=user.id)
    in_progress_count = len(in_progress)
    block = await check_wizard_start_block(db, user, in_progress_count=in_progress_count)
    return block, in_progress_count


def _brief_page_context(
    request: Request,
    user: CurrentUser,
    *,
    block: Any,
    in_progress_count: int,
    open_block_modal: bool = False,
    form_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    default_exclude_domains = "\n".join(EXCLUDE_DOMAINS)
    form = form_values or {}
    return {
        "request": request,
        "user": user,
        "main_content_template": "decision_tree/generation/_main_initial_form.html",
        "default_exclude_domains": default_exclude_domains,
        "current_phase": None,
        "in_progress_generation_count": in_progress_count,
        "wizard_start_block": block,
        "wizard_start_blocked": block is not None,
        "open_wizard_block_modal": open_block_modal and block is not None,
        "stripe_configured": settings.stripe_configured,
        "form_title": form.get("title", ""),
        "form_goal": form.get("user_prompt", ""),
        "form_include_domains": form.get("include_domains", ""),
        "form_pasted_text": form.get("pasted_text", ""),
        "form_exclude_domains": form.get("exclude_domains") or default_exclude_domains,
        "form_country": (
            form.get("country", "") if settings.show_decision_tree_generation_region_selector else ""
        ),
        "form_enable_web_search": form.get("enable_web_search", "") in ("on", "true", "1", "yes"),
        "form_enable_user_materials": (
            form.get("enable_user_materials", "") in ("on", "true", "1", "yes")
            or bool((form.get("pasted_text") or "").strip())
        ),
    }


@router.get("/wizard-start")
async def wizard_start_entry(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Entry point for all “start workflow” links — redirects or shows block modal."""
    block, in_progress_count = await _wizard_start_context(db, user)
    if block is None:
        return RedirectResponse(url="/decision-trees/agentic/brief", status_code=303)

    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            "decision_tree/generation/_wizard_start_blocked_modal.html",
            {
                "request": request,
                "wizard_start_block": block,
                "stripe_configured": settings.stripe_configured,
            },
        )

    return templates.TemplateResponse(
        "decision_tree/generation/_generation_layout.html",
        _brief_page_context(
            request,
            user,
            block=block,
            in_progress_count=in_progress_count,
            open_block_modal=True,
        ),
    )


@router.get("/wizard-start-blocked-modal", response_class=HTMLResponse)
async def wizard_start_blocked_modal(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """HTMX: modal explaining why a new wizard cannot start."""
    block, _ = await _wizard_start_context(db, user)
    if block is None:
        # Empty 200 (not 204): HTMX swaps into #modal-container and clears the overlay.
        # HX-Trigger refreshes the brief form so a stale block banner disappears.
        response = HTMLResponse(content="")
        response.headers["HX-Trigger"] = "refreshWizardBrief"
        return response

    return templates.TemplateResponse(
        "decision_tree/generation/_wizard_start_blocked_modal.html",
        {
            "request": request,
            "wizard_start_block": block,
            "stripe_configured": settings.stripe_configured,
        },
    )


@router.get("/brief-partial", response_class=HTMLResponse)
async def agentic_generation_brief_partial(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """HTMX: refresh the initial brief form (e.g. after wizard start block clears)."""
    block, in_progress_count = await _wizard_start_context(db, user)
    return templates.TemplateResponse(
        "decision_tree/generation/_main_initial_form.html",
        _brief_page_context(
            request,
            user,
            block=block,
            in_progress_count=in_progress_count,
            open_block_modal=False,
        ),
    )


@router.get("/brief", response_class=HTMLResponse)
async def agentic_generation_brief(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """Display the agentic generation brief form (start a new workflow)."""
    await track_phase_enter(db, user_id=user.id, phase="brief", source="new")
    block, in_progress_count = await _wizard_start_context(db, user)

    return templates.TemplateResponse(
        "decision_tree/generation/_generation_layout.html",
        _brief_page_context(
            request,
            user,
            block=block,
            in_progress_count=in_progress_count,
            open_block_modal=block is not None,
        ),
    )


@router.get("/research/edit", response_class=HTMLResponse)
async def get_research_edit_form(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str,
):
    """Render the research edit form for a given generation. Used by 'Back to Research' link."""
    generation = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)
    if not generation or generation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Generation not found")

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
            "db": db,
            "openai_client": openai_client,
        }
    }
    workflow = await get_compiled_workflow()
    state_snapshot = await workflow.aget_state(config)
    state = state_snapshot.values or {}
    research_context = state.get("research_context_edited") or state.get("research_context", "")

    await track_phase_enter(
        db,
        user_id=user.id,
        phase="research",
        thread_id=thread_id,
        generation_id=generation.id,
        source="back_link",
    )

    ctx = research_edit_template_context(
        thread_id=thread_id,
        state={**state, "research_context": research_context},
        generation_id=generation.id,
    )
    return render_step_template(
        request=request,
        main_content_template="decision_tree/generation/_main_research_edit.html",
        context=ctx,
        user=user,
    )


@router.post("/retry-research", response_class=HTMLResponse)
async def retry_research_generation(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    thread_id: str = Form(...),
):
    """Re-run web search + factor analysis with streaming preview (same UX as initial generate)."""
    generation = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)
    if not generation or generation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Generation not found")

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
        }
    }
    try:
        workflow = await get_compiled_workflow()
        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values or {}
        if not state:
            raise HTTPException(
                status_code=404, detail="No saved workflow state for this generation"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to load workflow state for retry research",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )
        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": wizard_retry_failed_message(),
                "error_recoverable": True,
                "generation_id": str(generation.id),
            },
        )

    enable_web_search = not bool(state.get("skip_web_search"))
    goal = state.get("user_prompt") or generation.user_prompt_preview or ""

    schedule_retry_research_workflow(
        thread_id=thread_id,
        user_id=user.id,
        generation_id=generation.id,
        goal=goal,
        enable_web_search=enable_web_search,
    )

    return render_step_template(
        request=request,
        main_content_template="decision_tree/generation/_main_research_loading.html",
        context={
            "thread_id": thread_id,
            "workflow_title": state.get("title", ""),
            "user_prompt": goal,
            "stream_url": f"/decision-trees/agentic/generate/{thread_id}/stream",
            "loading_title": "Retrying AI research…",
            "current_phase": "research",
        },
        user=user,
    )


@router.get("/generate/{thread_id}/stream")
async def research_generation_stream(
    user: CurrentUser,
    db: AsyncSessionDep,
    thread_id: str,
):
    """SSE stream of research preview events for an in-progress generation."""
    generation = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)
    if not generation or generation.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    bus = get_bus(thread_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Stream not found")

    return StreamingResponse(
        sse_event_stream(thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/generate/{thread_id}/cancel")
async def cancel_generation(
    user: CurrentUser,
    db: AsyncSessionDep,
    thread_id: str,
):
    """Best-effort cancel for an in-progress research stream."""
    generation = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)
    if not generation or generation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Generation not found")

    bus = get_bus(thread_id)
    if not bus:
        raise HTTPException(status_code=404, detail="Stream not found")

    if bus.state != "running":
        return JSONResponse({"cancelled": False}, status_code=409)

    bus.cancel_event.set()
    return JSONResponse({"cancelled": True})


@router.post("/generate", response_class=HTMLResponse)
async def start_generation(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
):
    """
    Start the agentic generation workflow.

    Schedules Phase 1 (search + factor analysis) in the background and returns
    a loading shell immediately. The client connects to SSE for live preview,
    then loads the research edit form when research_complete fires.

    Form is parsed manually so we can re-render with preserved values on validation error.
    """
    form_data = await request.form()
    form_dict = {k: (v or "") for k, v in form_data.items() if isinstance(v, str)}
    if not settings.show_decision_tree_generation_region_selector:
        form_dict["country"] = ""

    try:
        brief = GenerationBriefInput.model_validate(form_dict)
    except ValidationError as e:
        error_messages = []
        for err in e.errors():
            msg = str(err.get("msg", err))
            if "\n" in msg:
                error_messages.append(msg)
            else:
                field = err.get("loc", ["?"])[-1]
                error_messages.append(f"{field}: {msg}")
        return _render_initial_form(
            request,
            user=user,
            form_values=form_dict,
            validation_errors=error_messages,
        )

    if (
        not brief.enable_web_search
        and not brief.enable_user_materials
        and not brief.confirm_goal_only
    ):
        return _render_initial_form(
            request,
            user=user,
            form_values=form_dict,
            show_research_source_confirm=True,
        )

    # Phase B: File ingestion (validate -> store -> parse -> merge)
    file_items: list[tuple[str, str]] = []
    temp_paths: list[Path] = []
    uploads = (
        form_data.getlist("source_files")
        if brief.enable_user_materials and "source_files" in form_data
        else []
    )

    if uploads:
        if not isinstance(uploads, list):
            uploads = [uploads] if uploads else []
        uploads = [u for u in uploads if hasattr(u, "read") and u.filename]

        if len(uploads) > MAX_FILES_PER_GENERATION:
            return _render_initial_form(
                request,
                user=user,
                form_values=form_dict,
                validation_errors=[f"Maximum {MAX_FILES_PER_GENERATION} files allowed."],
            )

        total_bytes = 0
        for i, upload in enumerate(uploads):
            path, err = await validate_and_store_upload(upload, i)
            if err:
                for p in temp_paths:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                return _render_initial_form(
                    request,
                    user=user,
                    form_values=form_dict,
                    validation_errors=[f"{upload.filename or 'File'}: {err}"],
                )
            if path:
                temp_paths.append(path)
                total_bytes += path.stat().st_size

        if total_bytes > MAX_TOTAL_BYTES:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            return _render_initial_form(
                request,
                user=user,
                form_values=form_dict,
                validation_errors=[
                    f"Total file size exceeds {MAX_TOTAL_BYTES // (1024 * 1024)} MB.",
                ],
            )

        parse_failures: list[tuple[str, str]] = []
        for path, orig_name in [
            (p, (u.filename or "file")) for p, u in zip(temp_paths, uploads, strict=True)
        ]:
            result = await parse_uploaded_file(path, orig_name)
            if not result.success:
                parse_failures.append((orig_name, result.error or "Parse failed"))
            elif result.text:
                file_items.append((result.filename, result.text))
        if parse_failures:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            return _render_initial_form(
                request,
                user=user,
                form_values=form_dict,
                parse_failure_errors=parse_failures,
            )
        for p in temp_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    # Fast-path pre-check: catches obviously blocked users before any DB write.
    block, in_progress_count = await _wizard_start_context(db, user)
    if block:
        ctx = _brief_page_context(
            request,
            user,
            block=block,
            in_progress_count=in_progress_count,
            open_block_modal=True,
            form_values=form_dict,
        )
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            return templates.TemplateResponse("decision_tree/generation/_main_initial_form.html", ctx)
        return templates.TemplateResponse("decision_tree/generation/_generation_layout.html", ctx)

    # start_new_generation acquires a per-user advisory lock and re-checks all
    # quota dimensions atomically before inserting the in-progress row.  Any
    # concurrent request for the same user that slipped past the fast-path
    # pre-check above will be caught here.
    try:
        in_progress_gen = await checkpoint_manager.start_new_generation(
            db=db,
            user=user,
            user_prompt=brief.user_prompt,
            graph_version="v2",
            ttl_days=7,
        )
    except WizardStartBlockedError as exc:
        # Locked re-check caught a concurrent-start race.  Show the same block
        # modal the pre-check would have shown, with the correct reason.
        ctx = _brief_page_context(
            request,
            user,
            block=exc.block,
            in_progress_count=in_progress_count,
            open_block_modal=True,
            form_values=form_dict,
        )
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            return templates.TemplateResponse("decision_tree/generation/_main_initial_form.html", ctx)
        return templates.TemplateResponse("decision_tree/generation/_generation_layout.html", ctx)
    except GenerationConcurrencyError:
        # Another start request for this user is in the middle of its lock
        # transaction (window: milliseconds).  Surface a friendly retry message.
        return _render_initial_form(
            request,
            user=user,
            form_values=form_dict,
            validation_errors=[
                "Your previous request is still being processed. "
                "Please wait a moment and try again."
            ],
        )
    thread_id = in_progress_gen.langgraph_thread_id

    include_domains_list: list[str] = []
    exclude_domains_list: list[str] = EXCLUDE_DOMAINS
    if brief.enable_web_search:
        include_domains_list = [u for u in brief.include_domains.split("\n") if u.strip()]
        if brief.exclude_domains:
            parsed = []
            for part in brief.exclude_domains.replace(",", "\n").split("\n"):
                d = part.strip()
                if d:
                    parsed.append(d)
            if parsed:
                exclude_domains_list = parsed

    logger.info(
        "Starting agentic generation",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "generation_id": str(in_progress_gen.id),
            "title_length": len(brief.title),
            "prompt_length": len(brief.user_prompt),
            "country": brief.country or "auto",
            "enable_user_materials": brief.enable_user_materials,
            "enable_web_search": brief.enable_web_search,
            "include_domains_count": len(include_domains_list),
            "exclude_domains_count": len(exclude_domains_list) if brief.enable_web_search else 0,
            "has_pasted_text": bool(brief.pasted_text and brief.pasted_text.strip()),
            "has_user_conclusions": bool(brief.user_conclusions and brief.user_conclusions.strip()),
            "user_conclusions_length": len(brief.user_conclusions) if brief.user_conclusions else 0,
        },
    )

    initial_state: dict[str, Any] = {
        "title": brief.title.strip()[:200],
        "user_prompt": brief.user_prompt,
        "user_id": str(user.id),
    }
    if brief.enable_web_search:
        if brief.country:
            initial_state["country"] = brief.country
        if include_domains_list:
            initial_state["include_domains"] = include_domains_list
        if exclude_domains_list:
            initial_state["exclude_domains"] = exclude_domains_list
    else:
        initial_state["skip_web_search"] = True
    corpus = (
        prepare_research_corpus(brief.pasted_text or "", file_items)
        if brief.enable_user_materials
        else None
    )
    if corpus:
        initial_state["research_corpus"] = corpus

    if brief.user_conclusions and brief.user_conclusions.strip():
        initial_state["user_conclusions"] = brief.user_conclusions.strip()

    phase_started_at = time.perf_counter()

    logger.debug(
        "Initial state prepared",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "state_keys": list(initial_state.keys()),
            "has_user_conclusions": "user_conclusions" in initial_state,
        },
    )

    schedule_generation_workflow(
        thread_id=thread_id,
        user_id=user.id,
        generation_id=in_progress_gen.id,
        initial_state=initial_state,
        phase_started_at=phase_started_at,
        goal=brief.user_prompt,
        enable_web_search=brief.enable_web_search,
    )

    return render_step_template(
        request=request,
        main_content_template="decision_tree/generation/_main_research_loading.html",
        context={
            "thread_id": thread_id,
            "workflow_title": brief.title.strip()[:200],
            "user_prompt": brief.user_prompt,
            "stream_url": f"/decision-trees/agentic/generate/{thread_id}/stream",
            "current_phase": "research",
        },
        user=user,
    )


@router.post("/research/submit", response_class=HTMLResponse)
async def submit_research_context(
    request: Request,
    user: CurrentUser,
    db: AsyncSessionDep,
    openai_client: OpenAIClientDep,
    thread_id: str = Form(...),
    research_context_edited: str = Form(...),
    action: str = Form(default="continue"),
    augment_prompt: str = Form(default=""),
    augment_include_domains: str = Form(default=""),
    augment_exclude_domains: str = Form(default=""),
):
    """
    Resume workflow after research context edit.

    User can either:
    - Continue to conclusions (action="continue") - Runs AI extraction
    - Augment with additional search (action="augment") - Loops back to research
    - Skip AI conclusions (action="skip_conclusions") - Show form to provide own conclusions
    """
    augment_include_list = []
    if augment_include_domains:
        augment_include_list = [d.strip() for d in augment_include_domains.split(",") if d.strip()]

    augment_exclude_list = []
    if augment_exclude_domains:
        augment_exclude_list = [d.strip() for d in augment_exclude_domains.split(",") if d.strip()]

    phase_timer = WizardPhaseTimer()

    if action == "skip_conclusions":
        logger.info(
            "User chose to skip AI and provide own conclusions",
            extra={"user_id": str(user.id), "thread_id": thread_id},
        )

        workflow = await get_compiled_workflow()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user.id,
                "db": db,
                "openai_client": openai_client,
            }
        }

        await workflow.aupdate_state(
            config,
            {"research_context_edited": research_context_edited},
        )

        state_snapshot = await workflow.aget_state(config)
        state = state_snapshot.values
        phase_history = state.get("phase_history", [])
        completed_phases = []
        for transition in phase_history:
            from_phase = transition.get("from")
            if from_phase and from_phase not in completed_phases:
                completed_phases.append(from_phase)

        await track_phase_submit(
            db,
            user_id=user.id,
            phase="research",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            action="skip_conclusions",
        )
        await track_phase_enter(
            db,
            user_id=user.id,
            phase="conclusions",
            thread_id=thread_id,
            source="skip_ai",
        )

        return render_step_template(
            request=request,
            main_content_template="decision_tree/generation/_main_conclusions_input.html",
            context={
                "thread_id": thread_id,
                "current_phase": "conclusions",
            },
            user=user,
        )

    logger.info(
        "Resuming with edited research context",
        extra={
            "user_id": str(user.id),
            "thread_id": thread_id,
            "context_length": len(research_context_edited),
            "action": action,
            "has_augment_params": bool(augment_prompt or augment_include_list),
        },
    )

    try:
        workflow = await get_compiled_workflow()
        temp_config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user.id,
                "db": db,
                "openai_client": openai_client,
                "tavily_client": None,
            }
        }
        state_snapshot = await workflow.aget_state(temp_config)
        logger.info(
            "Current workflow state before resume",
            extra={
                "user_id": str(user.id),
                "thread_id": thread_id,
                "state_keys": list(state_snapshot.values.keys()) if state_snapshot.values else [],
                "has_user_conclusions": "user_conclusions" in state_snapshot.values
                if state_snapshot.values
                else False,
            },
        )
    except Exception as e:
        logger.warning(f"Failed to get state snapshot: {e}")

    tavily_client = None
    if action == "augment":
        try:
            from smeme.core.search import get_tavily_client

            tavily_client = get_tavily_client()
        except TavilyNotConfiguredError:
            logger.warning("Tavily not configured, cannot augment")
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": "Web search not configured. Cannot augment research.",
                    "error_recoverable": True,
                },
            )

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user.id,
            "db": db,
            "openai_client": openai_client,
            "tavily_client": tavily_client,
        }
    }

    try:
        resume_payload = {
            "research_context_edited": research_context_edited,
            "user_action": action,
        }

        if action == "augment":
            resume_payload["augment_prompt"] = augment_prompt
            resume_payload["augment_include_domains"] = augment_include_list
            resume_payload["augment_exclude_domains"] = augment_exclude_list
        else:
            await checkpoint_manager.update_phase(
                db=db,
                thread_id=thread_id,
                phase="conclusions",
            )

        workflow = await get_compiled_workflow()
        result = await workflow.ainvoke(Command(resume=resume_payload), config)

        interrupts = result.get("__interrupt__", [])
        logger.info(
            f"After resuming workflow, found {len(interrupts)} interrupts",
            extra={
                "user_id": str(user.id),
                "thread_id": thread_id,
                "interrupt_count": len(interrupts),
                "action": action,
            },
        )

        if interrupts:
            interrupt_obj: Interrupt = interrupts[0]

            state_snapshot = await workflow.aget_state(config)
            state = state_snapshot.values

            payload = None
            if isinstance(interrupt_obj.value, dict):
                try:
                    payload = InterruptPayload(**interrupt_obj.value)
                    logger.info(
                        "Using Sprint 6 InterruptPayload format",
                        extra={
                            "phase": payload.phase,
                            "user_id": payload.user_id,
                            "action_required": payload.action_required,
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "InterruptPayload validation failed, using legacy format",
                        extra={"error": str(e)},
                    )

            phase = payload.phase if payload else state.get("current_phase", "unknown")

            if phase == "research" or (
                "research_context" in state and not state.get("possible_conclusions")
            ):
                logger.info(
                    "Workflow interrupted for research edit (after augmentation)",
                    extra={
                        "user_id": str(user.id),
                        "thread_id": thread_id,
                        "augmentation_count": state.get("augmentation_count", 0),
                    },
                )

                if payload:
                    research_context = payload.data_to_edit.get("research_context", "")
                elif isinstance(interrupt_obj.value, str):
                    research_context = interrupt_obj.value
                else:
                    research_context = state.get("research_context", "")

                await track_phase_submit(
                    db,
                    user_id=user.id,
                    phase="research",
                    thread_id=thread_id,
                    duration_ms=phase_timer.duration_ms,
                    action="augment",
                )
                await track_phase_enter(
                    db,
                    user_id=user.id,
                    phase="research",
                    thread_id=thread_id,
                    source="augment",
                )

                gen = await checkpoint_manager.get_generation_by_thread_id(
                    db=db, thread_id=thread_id
                )
                return render_wizard_step_safe(
                    request=request,
                    main_content_template="decision_tree/generation/_main_research_edit.html",
                    context=research_edit_template_context(
                        thread_id=thread_id,
                        state={**state, "research_context": research_context},
                        generation_id=gen.id if gen else None,
                    ),
                    user=user,
                    thread_id=thread_id,
                )

            if payload:
                possible_conclusions = payload.data_to_edit.get("possible_conclusions", "")
            elif isinstance(interrupt_obj.value, str):
                possible_conclusions = interrupt_obj.value
            else:
                possible_conclusions = state.get("possible_conclusions", "")

            logger.info(
                "Workflow interrupted for conclusions edit",
                extra={
                    "user_id": str(user.id),
                    "thread_id": thread_id,
                    "conclusions_length": len(possible_conclusions),
                    "has_conclusions": bool(possible_conclusions),
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
                phase="research",
                thread_id=thread_id,
                duration_ms=phase_timer.duration_ms,
                action=action,
            )
            await track_phase_enter(
                db,
                user_id=user.id,
                phase="conclusions",
                thread_id=thread_id,
                source="continue",
            )

            gen = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)

            return render_wizard_step_safe(
                request=request,
                main_content_template="decision_tree/generation/_main_conclusions_edit.html",
                context={
                    "thread_id": thread_id,
                    "generation_id": str(gen.id) if gen else None,
                    "possible_conclusions": possible_conclusions,
                    "conclusions_source": state.get("conclusions_source", "unknown"),
                    "current_phase": "conclusions",
                },
                user=user,
                thread_id=thread_id,
            )

        if result.get("error"):
            return templates.TemplateResponse(
                "decision_tree/generation/_error.html",
                {
                    "request": request,
                    "error_message": sanitize_wizard_error_for_user(result["error"]),
                    "error_recoverable": result.get("error_recoverable", True),
                },
            )

        logger.warning("Workflow completed without conclusions interrupt - unexpected")
        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": "Workflow completed unexpectedly.",
                "error_recoverable": True,
            },
        )

    except Exception as e:
        await track_phase_error(
            db,
            user_id=user.id,
            phase="research",
            thread_id=thread_id,
            duration_ms=phase_timer.duration_ms,
            error_message=str(e),
            action=action,
        )
        logger.error(
            "Research context submission failed",
            extra={"user_id": str(user.id), "thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )

        is_recoverable = wizard_generation_error_recoverable(e)
        gen = await checkpoint_manager.get_generation_by_thread_id(db=db, thread_id=thread_id)

        if wizard_should_cleanup_generation(e):
            logger.info(
                "Fatal error during research submission, cleaning up generation",
                extra={"thread_id": thread_id, "error": str(e)},
            )
            await checkpoint_manager.complete_generation(db=db, thread_id=thread_id)

        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": wizard_submit_failure_message(e, recoverable=is_recoverable),
                "error_recoverable": is_recoverable,
                "generation_id": str(gen.id) if gen else None,
            },
        )
