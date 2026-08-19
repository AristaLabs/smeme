"""Structured JSON contract for SMEme reasoning MCP tools.

MCP tool handlers return **strings** (JSON). Clients should parse the payload and
branch on ``error.code`` when present.

**Success** — tool-specific shape (e.g. ``outcome`` for evaluate, ``decision_trees`` for list).

**Expected failure** (caller can recover)::

    {"error": {"code": "<stable_code>", "message": "<human-readable>", ...}}

**Unexpected failure** — same envelope with ``code: "internal_error"``; details are
logged server-side only.

Authoritative list for docs and tests: ``REASONING_TOOL_ERROR_CODES``. Cowork / LLM
guidance: ``agent-skills/``.

**Agent-facing copy:** ``error.message`` and ``blockers.message`` use the same product
vocabulary as shipped skills (see ``agent-skills/README.md``) — no Z3/SAT/entailment
wording in user-quoted strings. Wire ``error.code`` literals (e.g. ``solver_timeout``) are
unchanged.

LangGraph on the MCP path is intentionally out of scope for now; tools call the
reasoning runtime directly.
"""

from __future__ import annotations

import json
from typing import Any

# Stable codes returned in ``error.code``. Keep in sync with SKILL files and tool docstrings.
REASONING_TOOL_ERROR_CODES: frozenset[str] = frozenset(
    {
        "auth_error",
        "invalid_answers_json",
        "invalid_evidence_blob_json",
        "invalid_decision_tree_id",
        "not_found",
        "no_reasoning_artifact",
        "no_compiled_theory",
        "invalid_graph",
        "stale_theory",
        "invalid_answers",
        # Provenance ingest gate (M0 / D018)
        "ingest_malformed",
        "ingest_cap_exceeded",
        "ingest_unknown_question_id",
        "ingest_invalid_answer_option",
        "ingest_dangling_evidence_ref",
        "ingest_duplicate_evidence_item_id",
        "ingest_invalid_timestamp",
        "ingest_invalid_evidence_id",
        "ingest_grounding_failed",
        "not_discoverable",
        "internal_error",
        "payload_too_large",
        "quota_exceeded",
        "concurrency_limit",
        "account_downgrade_pending",
        "graph_conflict",
        "draft_not_editable",
        "ir_parse_or_validate_failed",
        "unsupported_ir_format_version",
        # Counterfactual tools (what_if / how_to_reach)
        "invalid_target_conclusion_id",
        "invalid_locked_question_id",
        "target_not_reachable_under_locks",
        "search_cap_exceeded",
        "no_plan_within_max_changes",
        "target_not_entailed",
        "solver_timeout",
        "solver_unknown",
        "persist_not_implemented",
        "invalid_reach_mode",
        "invalid_assumption_node_id",
        "conflicting_assumptions",
        "assumptions_cap_exceeded",
        # Path under edit (``smeme_reasoning_edit_affects_path``)
        "path_not_entailed_at_baseline",
        # Inquire MCP (Phase 5 + Phase 6 persist)
        "assertion_mismatch",
        "admission_rejected",
        "inquire_invalid_payload",
        "inquire_unknown_question",
        "inquire_verification_protocol",
        "inquire_verify_target_mismatch",
        "inquire_revision_conflict",
        "inquire_idempotency_conflict",
        "inquire_policy_mismatch",
        "inquire_session_not_active",
        "inquire_artifact_mismatch",
        "inquire_artifact_unavailable",
        "inquire_session_invariant",
        "isolated_evaluations_required",
    }
)

# Shown to MCP clients when an unhandled exception occurs (no stack traces).
INTERNAL_ERROR_MESSAGE = (
    "Unexpected server error while handling this tool call. "
    "Retry once; if it persists, contact the operator with the approximate time."
)


def tool_error_payload(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build the ``error`` object as a dict (for tests or composition)."""
    return {"code": code, "message": message, **extra}


def tool_error_json(code: str, message: str, **extra: Any) -> str:
    """JSON string for MCP tool return: ``{"error": {...}}``."""
    payload = tool_error_payload(code, message, **extra)
    return json.dumps({"error": payload})


def parse_tool_error_code(payload_str: str) -> str | None:
    """If ``payload_str`` is JSON with ``error.code``, return the code; else None."""
    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        return None
    err = data.get("error")
    if not isinstance(err, dict):
        return None
    code = err.get("code")
    return str(code) if isinstance(code, str) else None
