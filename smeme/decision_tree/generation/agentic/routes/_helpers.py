"""Shared rendering helpers for agentic generation routes."""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from jinja2 import TemplateError
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.config import settings
from smeme.core.templates import templates
from smeme.decision_tree.generation.agentic.subgraphs.research import EXCLUDE_DOMAINS
from smeme.decision_tree.generation.agentic.telemetry import WizardPhase, track_phase_enter
from smeme.decision_tree.generation.agentic.user_messages import (
    wizard_error_page_message,
    wizard_render_error_message,
)

logger = logging.getLogger("smeme.decision_tree.generation.agentic")


def wizard_generation_error_recoverable(error: Exception | str) -> bool:
    """True when the in-progress checkpoint should be kept (user can resume/retry)."""
    if isinstance(error, TemplateError):
        return True
    error_str = str(error).lower()
    recoverable_keywords = (
        "timeout",
        "connection",
        "network",
        "ssl",
        "reset",
        "eof",
        "rate_limit",
        "rate limit",
        "429",
        "insufficient_quota",
        "quota",
        "too many requests",
        "jinja",
        "template",
        "templatesyntaxerror",
    )
    return any(k in error_str for k in recoverable_keywords)


def wizard_should_cleanup_generation(error: Exception | str) -> bool:
    """True when a failed wizard step should delete the in-progress row."""
    return not wizard_generation_error_recoverable(error)


def wizard_submit_failure_message(error: Exception | str, *, recoverable: bool) -> str:
    """User-facing HTML for wizard POST handlers after an exception."""
    if not recoverable:
        return "Something went wrong. Please try again."
    if isinstance(error, TemplateError):
        return wizard_render_error_message()
    return wizard_error_page_message(error, recoverable=True)


def research_edit_template_context(
    *,
    thread_id: str,
    state: dict,
    generation_id: Any = None,
) -> dict[str, Any]:
    """Shared context for the research review step."""
    default_exclude_domains = ", ".join(EXCLUDE_DOMAINS)
    phase_history = state.get("phase_history", [])
    completed_phases: list[str] = []
    for transition in phase_history:
        from_phase = transition.get("from")
        if from_phase and from_phase not in completed_phases:
            completed_phases.append(from_phase)
    research_context = state.get("research_context", "")
    failure_source = state.get("research_failure_source")
    skip_reason = state.get("search_skip_reason") or ""
    openai_api_failure = (
        failure_source == "openai"
        or bool(state.get("openai_failure_kind"))
        or "## What happened" in research_context
        or (state.get("research_degraded") and "ai research" in skip_reason.lower())
    )
    has_research_corpus = bool((state.get("research_corpus") or "").strip())
    web_search_user_opt_out = bool(state.get("skip_web_search"))
    research_notice: dict[str, str] | None = None
    if web_search_user_opt_out:
        if has_research_corpus:
            research_notice = {
                "style": "info",
                "title": "Web search not enabled",
                "message": (
                    "Analysis used your uploaded files and/or pasted text only "
                    "(no web search was run)."
                ),
            }
        else:
            research_notice = {
                "style": "info",
                "title": "Web search not enabled",
                "message": (
                    "Factors are based on your goal description and AI knowledge only, "
                    "which may be outdated."
                ),
            }
    elif (state.get("research_degraded") or state.get("search_skipped")) and not openai_api_failure:
        research_notice = {
            "style": "warning",
            "title": "Limited research",
            "message": state.get("search_skip_reason") or "Web search was unavailable.",
            "extra": "These factors may rely on AI knowledge only, which can be outdated.",
        }
    return {
        "thread_id": thread_id,
        "generation_id": str(generation_id) if generation_id else None,
        "workflow_title": state.get("title", ""),
        "research_context": state.get("research_context", ""),
        "openai_api_failure": openai_api_failure,
        "openai_failure_kind": state.get("openai_failure_kind"),
        "search_skipped": state.get("search_skipped", False),
        "search_skip_reason": state.get("search_skip_reason"),
        "research_degraded": state.get("research_degraded", False),
        "augmentation_count": state.get("augmentation_count", 0),
        "extraction_used": state.get("extraction_used", False),
        "user_prompt": state.get("user_prompt", ""),
        "default_exclude_domains": default_exclude_domains,
        "current_phase": "research",
        "completed_phases": completed_phases,
        "phase_history": phase_history,
        "web_search_user_opt_out": web_search_user_opt_out,
        "has_research_corpus": has_research_corpus,
        "research_notice": research_notice,
    }


async def track_wizard_resume_enter(
    db: AsyncSession,
    *,
    user_id: UUID,
    phase: WizardPhase,
    thread_id: str,
    generation_id: UUID,
    source: str = "resume",
) -> None:
    """Record phase enter when resuming or deep-linking an in-progress generation."""
    await track_phase_enter(
        db,
        user_id=user_id,
        phase=phase,
        thread_id=thread_id,
        generation_id=generation_id,
        source=source,
    )


def _render_initial_form(
    request: Request,
    *,
    user: Any = None,
    form_values: dict[str, str] | None = None,
    validation_errors: list[str] | None = None,
    parse_failure_errors: list[tuple[str, str]] | None = None,
    in_progress_generation_count: int = 0,
    wizard_start_block: Any = None,
    show_research_source_confirm: bool = False,
) -> templates.TemplateResponse:
    """Render the initial generation form, optionally with pre-filled values and errors."""
    form = form_values or {}
    default_exclude_domains = "\n".join(EXCLUDE_DOMAINS)
    # Parse failures: (filename, reason) for template
    parse_errors = [{"filename": f, "reason": r} for f, r in (parse_failure_errors or [])]
    context = {
        "request": request,
        "user": user,
        "main_content_template": "decision_tree/generation/_main_initial_form.html",
        "default_exclude_domains": default_exclude_domains,
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
        "validation_errors": validation_errors or [],
        "parse_failure_errors": parse_errors,
        "in_progress_generation_count": in_progress_generation_count,
        "wizard_start_block": wizard_start_block,
        "wizard_start_blocked": wizard_start_block is not None,
        "open_wizard_block_modal": False,
        "show_research_source_confirm": show_research_source_confirm,
        "stripe_configured": settings.stripe_configured,
        "current_phase": None,
    }
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            "decision_tree/generation/_main_initial_form.html",
            context,
        )
    return templates.TemplateResponse(
        "decision_tree/generation/_generation_layout.html",
        context,
    )


def render_generation_layout(
    request: Request,
    *,
    user: Any,
    main_content_template: str,
    context: dict[str, Any] | None = None,
) -> templates.TemplateResponse:
    """Full-page generation wizard shell (nav needs ``user`` for Dashboard vs Log in)."""
    return templates.TemplateResponse(
        "decision_tree/generation/_generation_layout.html",
        {
            "request": request,
            "user": user,
            "main_content_template": main_content_template,
            **(context or {}),
        },
    )


def render_step_template(
    request: Request,
    main_content_template: str,
    context: dict[str, Any],
    *,
    user: Any,
) -> templates.TemplateResponse:
    """
    Render template for both HTMX and direct browser requests.

    - HTMX requests: Returns just the partial (main content)
    - Direct requests: Returns full layout with partial included

    This prevents layout nesting when HTMX swaps innerHTML.
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    merged = {"request": request, "user": user, **context}

    if is_htmx:
        response = templates.TemplateResponse(main_content_template, merged)
    else:
        response = render_generation_layout(
            request,
            user=user,
            main_content_template=main_content_template,
            context=context,
        )

    # Refresh during the wizard returns to the dashboard hub (in-progress table).
    if is_htmx and context.get("generation_id"):
        response.headers["HX-Push-Url"] = "/decision-trees/dashboard"

    return response


def render_wizard_step_safe(
    request: Request,
    *,
    main_content_template: str,
    context: dict[str, Any],
    user: Any,
    thread_id: str,
) -> templates.TemplateResponse:
    """Render a wizard step; on template failure keep checkpoints and show resume link."""
    try:
        return render_step_template(
            request,
            main_content_template,
            context,
            user=user,
        )
    except Exception as e:
        logger.error(
            "Wizard step template render failed",
            extra={
                "thread_id": thread_id,
                "template": main_content_template,
                "error": str(e),
            },
            exc_info=True,
        )
        return templates.TemplateResponse(
            "decision_tree/generation/_error.html",
            {
                "request": request,
                "error_message": wizard_render_error_message(),
                "error_recoverable": True,
                "generation_id": context.get("generation_id"),
            },
        )
