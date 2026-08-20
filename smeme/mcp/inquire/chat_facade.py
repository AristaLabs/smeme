"""Chat-facing Inquire facade over durable persist (ACQUIRE-only; VERIFY fail-closed).

``smeme_reasoning_evaluate`` / ``smeme_reasoning_evaluate_continue`` strip the
control channel. Kernel/persist semantics are unchanged. VERIFY does **not**
STOP the session — chat ends the loop with ``isolated_evaluations_required``;
the session remains ACTIVE for the orchestrator mount.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import (
    DecisionTree,
    InquiryAdmittedAssertion,
    ReasoningCompiledArtifact,
    User,
)
from smeme.decision_tree.models import DTGraph
from smeme.mcp.inquire.handlers import InquireHandlerError
from smeme.reasoning.orchestration.inquire.persist import (
    STATUS_ACTIVE,
    STATUS_STOPPED,
    admit_to_session,
    canonical_request_hash,
    get_task_for_session,
    start_inquiry,
)
from smeme.reasoning.orchestration.inquire.persist.auth import load_owned_session


def chat_admit_idempotency_key(
    *,
    inquiry_session_id: UUID,
    question_id: str,
    selected_option: str | None,
    provenance_id: str | None,
) -> str:
    """Stable chat continue key from the same admit identity as ``request_hash``."""
    digest = canonical_request_hash(
        {
            "operation": "admit",
            "inquiry_session_id": str(inquiry_session_id),
            "question_id": question_id,
            "selected_option": selected_option,
            "provenance_id": provenance_id,
        }
    )
    return f"chat-{digest}"


def strip_chat_active_response(
    *,
    inquiry_session_id: str,
    revision: int,
    status: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Extractor-facing ACTIVE payload — no directive / battery / pv_version."""
    return {
        "inquiry_session_id": inquiry_session_id,
        "revision": revision,
        "status": status,
        "harness_next": "continue_evaluate",
        "task": {
            "question_id": task["question_id"],
            "stem": task["stem"],
            "options": list(task["options"]),
        },
    }


def isolated_evaluations_required_payload(
    *,
    inquiry_session_id: str,
    revision: int,
    status: str,
) -> dict[str, Any]:
    """Chat-invocation terminal when ANALYZE issues VERIFY. Session stays ACTIVE."""
    return {
        "error": {
            "code": "isolated_evaluations_required",
            "message": (
                "This inquiry needs isolated verification trials that ordinary "
                "chat context cannot provide. The session remains ACTIVE for an "
                "orchestrator that can run blind evaluations; do not continue "
                "VERIFY from this chat connector."
            ),
            "inquiry_session_id": inquiry_session_id,
            "revision": revision,
            "status": status,
        }
    }


def _directive_action(wire: dict[str, Any]) -> str | None:
    directive = wire.get("directive")
    if not isinstance(directive, dict):
        return None
    action = directive.get("action")
    return action if isinstance(action, str) else None


def _directive_question_id(wire: dict[str, Any]) -> str | None:
    directive = wire.get("directive")
    if not isinstance(directive, dict):
        return None
    qid = directive.get("question_id")
    return qid if isinstance(qid, str) and qid else None


async def _active_task_or_terminal(
    db: AsyncSession,
    *,
    user: User,
    wire: dict[str, Any],
) -> dict[str, Any]:
    """Map persist wire → chat JSON (ACTIVE task, VERIFY error, or STOP marker)."""
    session_id = str(wire["inquiry_session_id"])
    revision = int(wire["revision"])
    status = str(wire["status"])
    action = _directive_action(wire)

    if action == "VERIFY":
        # Do not STOP. Chat cannot run the battery.
        return isolated_evaluations_required_payload(
            inquiry_session_id=session_id,
            revision=revision,
            status=status if status else STATUS_ACTIVE,
        )

    if action == "STOP" or status == STATUS_STOPPED:
        return {
            "_chat_stop": True,
            "inquiry_session_id": session_id,
            "revision": revision,
            "status": STATUS_STOPPED,
            "stop_reason": wire.get("stop_reason"),
            "admitted": wire.get("admitted"),
        }

    if action != "ACQUIRE":
        raise InquireHandlerError(
            "inquire_session_invariant",
            f"Unexpected Inquire directive action for chat facade: {action!r}",
        )

    qid = _directive_question_id(wire)
    if qid is None:
        raise InquireHandlerError(
            "inquire_session_invariant",
            "ACQUIRE directive missing question_id",
        )
    task = await get_task_for_session(
        db,
        user=user,
        inquiry_session_id=UUID(session_id),
        question_id=qid,
    )
    return strip_chat_active_response(
        inquiry_session_id=session_id,
        revision=revision,
        status=status,
        task=task,
    )


async def chat_evaluate_start(
    db: AsyncSession,
    *,
    user: User,
    decision_tree: DecisionTree,
    artifact: ReasoningCompiledArtifact,
    graph: DTGraph,
) -> dict[str, Any]:
    """Start inquiry (φ empty); return blind task, VERIFY error, or STOP marker."""
    wire = await start_inquiry(
        db,
        user=user,
        decision_tree=decision_tree,
        artifact=artifact,
        graph=graph,
        force_reachable_ids=None,
        force_unreachable_ids=None,
    )
    return await _active_task_or_terminal(db, user=user, wire=wire)


async def chat_evaluate_continue(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    question_id: str,
    selected_option: str | None,
    provenance_id: str | None,
) -> dict[str, Any]:
    """Admit one ACQUIRE answer; never VERIFY. Return next task / VERIFY error / STOP."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    expected_revision = int(session.revision)
    idempotency_key = chat_admit_idempotency_key(
        inquiry_session_id=inquiry_session_id,
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=provenance_id,
    )
    wire = await admit_to_session(
        db,
        user=user,
        inquiry_session_id=inquiry_session_id,
        expected_revision=expected_revision,
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=provenance_id,
        idempotency_key=idempotency_key,
        reject_stale_replay=True,
    )
    return await _active_task_or_terminal(db, user=user, wire=wire)


async def admitted_flat_answers_for_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
) -> dict[str, str]:
    """Load admitted (q → option) for Apply after Inquire STOP."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    result = await db.execute(
        select(InquiryAdmittedAssertion).where(InquiryAdmittedAssertion.session_id == session.id)
    )
    flat: dict[str, str] = {}
    for row in result.scalars().all():
        flat[row.question_id] = row.option
    return flat


def flat_answers_to_legacy_raw_json(flat: dict[str, str]) -> str:
    """Legacy flat answers object for Apply ingest."""
    return json.dumps(flat, ensure_ascii=False, separators=(",", ":"))
