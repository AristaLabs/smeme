"""Parse questionnaire design markdown for generation validation."""

from __future__ import annotations

import re

_QUESTION_HEADER = re.compile(r"^####\s+(Q\d+)\s*:", re.MULTILINE | re.IGNORECASE)
_COLLECT_ONLY_KIND = re.compile(
    r"^\s*-\s*\*\*Node kind\*\*:\s*collect_only\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def parse_collect_only_question_ids(design_markdown: str) -> frozenset[str]:
    """Return lowercase question node IDs marked ``- **Node kind**: collect_only``."""
    if not design_markdown.strip():
        return frozenset()

    collect_only: set[str] = set()
    blocks = re.split(r"(?=^####\s+Q\d+\s*:)", design_markdown, flags=re.MULTILINE | re.IGNORECASE)

    for block in blocks:
        header = _QUESTION_HEADER.search(block)
        if not header:
            continue
        if not _COLLECT_ONLY_KIND.search(block):
            continue
        collect_only.add(header.group(1).lower())

    return frozenset(collect_only)
