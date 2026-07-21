"""Research subgraph: LLM failure preserves Tavily content."""

from openai import APITimeoutError

from smeme.qnr.generation.agentic.routes._helpers import research_edit_template_context
from smeme.qnr.generation.agentic.subgraphs.research import (
    _openai_failure_return,
    openai_failure_kind,
    openai_research_error_message,
)
from smeme.qnr.generation.agentic.user_messages import build_research_context_when_llm_fails


def test_openai_quota_message_user_friendly():
    exc = Exception(
        "Error code: 429 - {'error': {'code': 'insufficient_quota', 'message': 'quota'}}"
    )
    msg = openai_research_error_message(exc)
    assert "insufficient_quota" not in msg
    assert "api key" not in msg.lower()
    assert "usage limit" in msg.lower()
    assert "openai.com" not in msg


def test_openai_timeout_message_user_friendly():
    exc = APITimeoutError(request=None)  # type: ignore[arg-type]
    assert openai_failure_kind(exc) == "timeout"
    msg = openai_research_error_message(exc)
    assert "too long" in msg.lower()
    assert "APITimeoutError" not in msg


def test_build_research_context_keeps_tavily_answer():
    search_raw = {"answer": "Summary from the web."}
    body = build_research_context_when_llm_fails(
        error_msg="AI research has reached its usage limit.",
        search_raw=search_raw,
        extract_raw=None,
    )
    assert "Web Research Summary" in body
    assert "Summary from the web." in body
    assert "Key Factors Analysis" in body
    assert "Retry AI research" in body
    assert "What happened" in body
    assert "server's OpenAI" not in body


def test_openai_failure_with_tavily_does_not_mark_search_skipped():
    exc = AttributeError("'ContentDeltaEvent' object has no attribute 'content'")
    search_raw = {"answer": "Summary from the web."}
    result = _openai_failure_return(exc=exc, search_raw=search_raw, extract_raw=None)
    assert result["research_failure_source"] == "openai"
    assert result["search_skipped"] is False
    assert result["research_degraded"] is False


def test_research_edit_shows_retry_for_llm_failure_content_without_persisted_source():
    body = build_research_context_when_llm_fails(
        error_msg="AI research could not be completed. Try again or edit the research manually.",
        search_raw={"answer": "Summary from the web."},
        extract_raw=None,
    )
    ctx = research_edit_template_context(
        thread_id="t-1",
        state={
            "research_context": body,
            "search_skipped": True,
            "search_skip_reason": "AI research could not be completed.",
            "research_degraded": True,
        },
    )
    assert ctx["openai_api_failure"] is True
    assert ctx["research_notice"] is None
