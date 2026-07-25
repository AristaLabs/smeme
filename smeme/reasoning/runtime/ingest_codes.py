"""Canonical wire codes for reasoning ingest (provenance envelope) and deterministic ordering.

``warnings[]`` items use ``code`` from :class:`IngestWarningCode`.
MCP ``error.code`` for ingest hard rejects uses :class:`IngestErrorCode` values
(also listed in ``smeme.mcp.tool_contract.REASONING_TOOL_ERROR_CODES``).

**Sort order (deterministic JSON):**

- ``warnings[]``: ascending by ``code``, then by joined ``question_ids`` (sorted
  lexicographically, comma-separated). Items without ``question_ids`` sort before
  those with (empty join string).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

# --- Orchestration hint (M0 option A; see D018) --------------------------------

HarnessNext = Literal["phase_1_continue", "phase_2_ok", "user_input_needed"]

HARNESS_NEXT_VALUES: tuple[HarnessNext, ...] = (
    "phase_1_continue",
    "phase_2_ok",
    "user_input_needed",
)


def harness_next_for_ingest(*, warnings: list[dict[str, Any]]) -> HarnessNext:
    """Derive ``harness_next`` from ingest warnings (server policy, no LLM prose)."""
    if not warnings:
        return "phase_2_ok"
    codes = {w.get("code") for w in warnings if isinstance(w, dict)}
    if codes == {"missing_evidence_ref"}:
        return "user_input_needed"
    return "phase_1_continue"


# --- Registry -----------------------------------------------------------------


class IngestWarningCode(StrEnum):
    """Non-blocking ingest / provenance hygiene (success path)."""

    missing_evidence_ref = "missing_evidence_ref"


class IngestErrorCode(StrEnum):
    """Blocking ingest failures (MCP / REST error channel)."""

    ingest_malformed = "ingest_malformed"
    ingest_cap_exceeded = "ingest_cap_exceeded"
    ingest_unknown_question_id = "ingest_unknown_question_id"
    ingest_invalid_answer_option = "ingest_invalid_answer_option"
    ingest_dangling_evidence_ref = "ingest_dangling_evidence_ref"
    ingest_duplicate_evidence_item_id = "ingest_duplicate_evidence_item_id"
    ingest_invalid_timestamp = "ingest_invalid_timestamp"
    ingest_invalid_evidence_id = "ingest_invalid_evidence_id"
    ingest_grounding_failed = "ingest_grounding_failed"


def sort_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new list sorted for stable wire JSON (mutates nothing).

    Each item's ``question_ids`` list is copied sorted lexicographically when present.
    """

    def key(w: dict[str, Any]) -> tuple[str, str]:
        code = w.get("code")
        code_s = str(code) if code is not None else ""
        qids = w.get("question_ids")
        if isinstance(qids, list) and all(isinstance(x, str) for x in qids):
            joined = ",".join(sorted(qids))
        else:
            joined = ""
        return (code_s, joined)

    out: list[dict[str, Any]] = []
    for w in sorted((dict(x) for x in warnings), key=key):
        w = dict(w)
        qids = w.get("question_ids")
        if isinstance(qids, list) and all(isinstance(x, str) for x in qids):
            w["question_ids"] = sorted(qids)
        out.append(w)
    return out


__all__ = [
    "HARNESS_NEXT_VALUES",
    "HarnessNext",
    "IngestErrorCode",
    "IngestWarningCode",
    "harness_next_for_ingest",
    "sort_warnings",
]
