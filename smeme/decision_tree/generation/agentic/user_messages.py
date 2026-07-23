"""User-facing copy for agentic DecisionTree generation (no API/infra jargon)."""

_IN_PROGRESS_LINK = (
    '<a href="/decision-trees/dashboard#in-progress" class="text-brand-600 underline hover:text-brand-800">'
    "in-progress decision trees</a>"
)


def _looks_like_ai_service_error(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "openai",
            "insufficient_quota",
            "quota",
            "rate_limit",
            "rate limit",
            "429",
        )
    )


def openai_research_message_for_kind(kind: str) -> str:
    """Short message for research-step banners and skip reasons."""
    if kind == "quota":
        return (
            "AI research has reached its usage limit. "
            "Try again later or edit the research manually."
        )
    if kind == "rate_limit":
        return "AI research is busy right now. Wait a minute, then try again."
    if kind == "timeout":
        return (
            "AI research took too long to finish. Try again, or edit the research manually "
            "using any web results below."
        )
    return "AI research could not be completed. Try again or edit the research manually."


def build_research_context_when_llm_fails(
    *,
    error_msg: str,
    search_raw: dict | None,
    extract_raw: dict | None,
) -> str:
    """Preserve Tavily/URL content when only the factor-analysis LLM call fails."""
    parts = [
        "## What happened",
        "",
        "We could not finish the AI analysis step. Any web research or URL content "
        "below is still available for you to review and edit.",
        "",
        error_msg,
        "",
    ]
    if search_raw and search_raw.get("answer"):
        parts.extend(["## Web Research Summary", str(search_raw["answer"]), ""])
    elif extract_raw:
        n = len(extract_raw.get("results", []))
        parts.extend(["## Content from Provided URLs", f"Extracted from {n} URL(s)", ""])
    parts.extend(
        [
            "## Key Factors Analysis",
            "_Add your own factors here, or use **Retry AI research** when the service is available._",
            "",
        ]
    )
    return "\n".join(parts)


def wizard_error_page_message(exc: Exception | str, *, recoverable: bool) -> str:
    """HTML-safe message for decision_tree/generation/_error.html."""
    if not recoverable:
        return "Something went wrong. Please try again."

    if _looks_like_ai_service_error(str(exc)):
        return (
            "We could not complete the AI research step. Your work is saved. "
            f"Resume from {_IN_PROGRESS_LINK} and try again."
        )
    return f"Your connection was interrupted. Your work is saved. Resume from {_IN_PROGRESS_LINK}."


def wizard_retry_failed_message() -> str:
    return (
        "We could not retry AI research. Your decision tree is still saved — "
        '<a href="/decision-trees/dashboard#in-progress" class="underline">resume from your dashboard</a>.'
    )


def wizard_render_error_message() -> str:
    """HTML-safe copy when LangGraph succeeded but Jinja rendering failed."""
    return (
        "We could not display the next step, but your progress is saved. "
        f"Resume from {_IN_PROGRESS_LINK}."
    )


def sanitize_wizard_error_for_user(error: str) -> str:
    """Map workflow error strings to user-safe copy; log raw errors separately."""
    if not error:
        return "Something went wrong. Please try again."
    if _looks_like_ai_service_error(error):
        return openai_research_message_for_kind("other")
    if (
        "failed to save questionnaire" in error.lower()
        or "failed to save decision tree" in error.lower()
    ):
        return "We could not save your decision tree. Please try again."
    if "web search not configured" in error.lower():
        return "Web search is not available right now. You can still continue by editing the research manually."
    # Avoid leaking exception details (status codes, JSON blobs, stack traces).
    if any(
        marker in error
        for marker in ("Error code:", "Traceback", "Exception", "{'", "HTTP", "api_key")
    ):
        return "Something went wrong. Please try again."
    return error
