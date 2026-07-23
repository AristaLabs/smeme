"""Strip conversational LLM tails from extracted conclusion markdown."""

from __future__ import annotations

import re

_CONCLUSION_HEADING = re.compile(r"^\s*\*\*CONCLUSION_\d+:", re.MULTILINE | re.IGNORECASE)
_HRULE_SPLIT = re.compile(r"\n---+\n")
_ASSISTANT_TAIL = re.compile(
    r"\n+(?:---+\s*\n+)?"
    r"(?:(?:If you want|Would you like|Let me know if|I can also|Feel free to ask)\b.*)$",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_extracted_conclusions(text: str) -> str:
    """
    Keep only ``**CONCLUSION_N:**`` blocks; drop chat-style closings the model sometimes appends.

    User-provided conclusions are not passed through this helper (see conclusions subgraph).
    """
    stripped = text.strip()
    if not stripped:
        return ""

    segments = [seg.strip() for seg in _HRULE_SPLIT.split(stripped) if seg.strip()]
    conclusion_segments = [seg for seg in segments if _CONCLUSION_HEADING.search(seg)]

    if conclusion_segments:
        body = "\n\n---\n\n".join(conclusion_segments)
    elif _CONCLUSION_HEADING.search(stripped):
        body = stripped
    else:
        return stripped

    body = _ASSISTANT_TAIL.sub("", body).strip()
    return re.sub(r"\n---+\s*$", "", body).strip()
