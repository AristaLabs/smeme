"""Parse approved conclusion markdown for downstream generation prompts."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CONCLUSION_TITLE = re.compile(
    r"\*\*CONCLUSION_(\d+):\s*([^*\n]+)\*\*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AllowedConclusions:
    """Parsed conclusion allowlist for design/build validation."""

    ids: tuple[str, ...]
    labels: tuple[tuple[str, str], ...]
    formatted_block: str
    parse_ok: bool


def extract_conclusion_ids(conclusions_text: str) -> list[tuple[str, str]]:
    """Return ordered (id, label) pairs, e.g. (``CONCLUSION_1``, ``Form an LLC``)."""
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for match in _CONCLUSION_TITLE.finditer(conclusions_text or ""):
        num = match.group(1)
        conclusion_id = f"CONCLUSION_{num}"
        if conclusion_id in seen:
            continue
        seen.add(conclusion_id)
        label = match.group(2).strip()
        results.append((conclusion_id, label))
    return results


def parse_allowed_conclusions(conclusions_text: str) -> AllowedConclusions:
    """Parse conclusions into a structured allowlist for state and validation."""
    entries = extract_conclusion_ids(conclusions_text)
    if not entries:
        block = (
            "⚠️ **PARSER WARNING:** No `**CONCLUSION_N:**` blocks were found in approved "
            "conclusions. You must use only conclusion IDs that appear in the Full "
            "Conclusions Reference below. Do not invent new conclusion IDs."
        )
        return AllowedConclusions(ids=(), labels=(), formatted_block=block, parse_ok=False)

    lines = ["You may ONLY reference these conclusion IDs (do not create, rename, merge, or omit):"]
    for conclusion_id, label in entries:
        lines.append(f"- {conclusion_id}: {label}")

    return AllowedConclusions(
        ids=tuple(conclusion_id for conclusion_id, _ in entries),
        labels=tuple(entries),
        formatted_block="\n".join(lines),
        parse_ok=True,
    )


def format_allowed_conclusions_list(conclusions_text: str) -> tuple[str, bool]:
    """Format a closed allowlist block for the design prompt."""
    parsed = parse_allowed_conclusions(conclusions_text)
    return parsed.formatted_block, parsed.parse_ok


def graph_conclusion_id_to_allowlist_id(node_id: str) -> str:
    """Map graph node ``conclusion_1`` → ``CONCLUSION_1``."""
    suffix = node_id.removeprefix("conclusion_")
    return f"CONCLUSION_{suffix.upper()}"
