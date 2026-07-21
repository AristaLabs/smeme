"""Structure research + conclusions for design-phase LLM input."""

from __future__ import annotations

import re


def _extract_section(text: str, section_name: str) -> str:
    """Extract body text for a named markdown section heading."""
    if not text:
        return ""

    pattern = re.compile(
        rf"^\*\*{re.escape(section_name)}:\*\*\s*\n(.*?)(?=^\*\*[A-Za-z ]+:\*\*|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def format_structured_design_context(
    *,
    research_context: str,
    conclusions: str,
    allowed_conclusions_block: str,
    conclusions_parse_ok: bool,
) -> str:
    """Build salient, labeled context for the design prompt."""
    thresholds = _extract_section(research_context, "Critical Decision Thresholds")
    cross_cutting = _extract_section(research_context, "Cross-Cutting Patterns")
    knowledge_gaps = _extract_section(research_context, "Knowledge Gaps")

    parse_note = ""
    if not conclusions_parse_ok:
        parse_note = (
            "\n\n⚠️ **Conclusion ID parse failed** — no `**CONCLUSION_N:**` blocks detected. "
            "Use only conclusion IDs from the Full Conclusions Reference below.\n"
        )

    return f"""## Approved Conclusions (closed list)
{allowed_conclusions_block}{parse_note}

## Critical Decision Thresholds
{thresholds or "(Not extracted — see full factor analysis below.)"}

## Cross-Cutting Patterns
{cross_cutting or "(Not extracted — see full factor analysis below.)"}

## Factor Dependencies and Knowledge Gaps
{knowledge_gaps or "(Not extracted — see full factor analysis below.)"}

## Approved Factor Analysis
{research_context}

## Full Conclusions Reference
{conclusions}
"""
