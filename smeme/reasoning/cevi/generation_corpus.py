"""Merge agentic generation state into one durable research corpus string (no Tavily in CEVI path)."""

from __future__ import annotations

from typing import Any


def build_research_corpus_text_from_generation_state(state: dict[str, Any]) -> str:
    """Combine pasted corpus and factor-research markdown from LangGraph state."""
    parts: list[str] = []
    pasted = state.get("research_corpus")
    if isinstance(pasted, str) and pasted.strip():
        parts.append("# Pasted / uploaded research\n\n" + pasted.strip())
    ctx = state.get("research_context_edited") or state.get("research_context")
    if isinstance(ctx, str) and ctx.strip():
        parts.append("# Factor research (from generation)\n\n" + ctx.strip())
    return "\n\n".join(parts)
