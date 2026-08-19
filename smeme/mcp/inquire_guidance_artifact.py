"""Inquire orchestrator protocol guidance (VERIFY isolation contract)."""

from __future__ import annotations

import hashlib
import json

INQUIRE_GUIDANCE_CONTENT_VERSION = "1.0.0"

INQUIRE_GUIDANCE_MARKDOWN = r"""# SMEme Inquire — Orchestrator Protocol

This MCP surface exposes the **explicit Inquire orchestration protocol**.

It is for deterministic workflow orchestration (for example LangGraph), **not**
ordinary chat-driven evaluation.

## VERIFY requirements

- Each evaluation task must be executed in a **fresh isolated evaluator context**.
- Forward only the inner blind task: `{question_id, stem, options}`.
- Do **not** expose prior answers, `verification_key`, `evaluation_id`, conclusions,
  other trial results, or parent conversation history to the evaluator.
- Do **not** reuse semantic-response caches for verification trials.
- Return observations to `smeme_inquire_verify`; do **not** decide RETAIN yourself.

## Guarantees and responsibilities

- SMEme enforces **task blindness** of the payload it emits and runs Core \(P_v\).
- **Evaluator isolation is the caller's responsibility.** SMEme does not and cannot
  verify downstream isolation.
- If your environment cannot provide that isolation, do **not** use VERIFY through
  this surface; use the standard chat evaluate connector instead (ACQUIRE gather
  only — chat will not fake a verification battery).

## Protocol tools

`smeme_inquire_start` → `smeme_inquire_get_task` → `smeme_inquire_admit` /
`smeme_inquire_verify` as directed. Carry `inquiry_session_id`, `expected_revision`,
and `idempotency_key` on mutations. Never forward VERIFY metadata to extractors.
"""

INQUIRE_GUIDANCE_CONTENT_DIGEST = (
    "sha256:" + hashlib.sha256(INQUIRE_GUIDANCE_MARKDOWN.encode("utf-8")).hexdigest()
)


def inquire_guidance_payload() -> dict[str, str]:
    """JSON object for ``smeme_inquire_guidance_get``."""
    return {
        "content_version": INQUIRE_GUIDANCE_CONTENT_VERSION,
        "content_digest": INQUIRE_GUIDANCE_CONTENT_DIGEST,
        "content_markdown": INQUIRE_GUIDANCE_MARKDOWN,
    }


def inquire_guidance_check_payload() -> dict[str, str]:
    """JSON object for ``smeme_inquire_guidance_check``."""
    return {
        "content_version": INQUIRE_GUIDANCE_CONTENT_VERSION,
        "content_digest": INQUIRE_GUIDANCE_CONTENT_DIGEST,
    }


def inquire_guidance_as_json() -> str:
    return json.dumps(inquire_guidance_payload(), ensure_ascii=False)
