"""Chat-facing Inquire facade over durable persist (ACQUIRE-only; no VERIFY battery).

``smeme_reasoning_evaluate`` / ``smeme_reasoning_evaluate_continue`` strip the
control channel. Kernel/persist semantics are unchanged. VERIFY does **not**
STOP the session — chat Applies admitted answers and returns a report with
``isolated_verification_not_run``. The session remains ACTIVE for the
orchestrator mount.

On true Inquire STOP, chat Applies admitted answers and merges ``stop_reason`` /
``inquire_stop_reason`` onto the report (see ``merge_chat_stop_onto_apply``).
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
    chat_report_issued_payload,
    get_chat_task_for_session,
    lookup_admit_receipt,
    start_inquiry,
)
from smeme.reasoning.orchestration.inquire.persist.auth import load_owned_session

CHAT_ISOLATED_VERIFICATION_NOT_RUN = "isolated_verification_not_run"


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
    answer_guidance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extractor-facing ACTIVE payload — no directive / battery / pv_version.

    ``answer_guidance`` (author hints on where to look) sits beside ``task``; the
    task object itself keeps the exact blind shape.
    """
    out: dict[str, Any] = {
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
    if answer_guidance:
        out["answer_guidance"] = answer_guidance
    return out


def isolated_evaluations_required_payload(
    *,
    inquiry_session_id: str,
    revision: int,
    status: str,
) -> dict[str, Any]:
    """Legacy chat error shape. Chat no longer returns this on VERIFY."""
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


_OPERATIONAL_OR_INCOMPLETE_STOPS = frozenset(
    {
        "operational_budget",
        "operational_timeout",
        "operational_unknown",
        "resolving_support_incomplete",
    }
)


def merge_chat_stop_onto_apply(
    apply_payload: dict[str, Any],
    *,
    inquiry_session_id: str,
    stop_reason: str | None,
    operational_status: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach Inquire terminal metadata onto a successful Apply report payload.

    ``stop_reason`` is the Inquire ANALYZE reason, or the chat-only
    ``isolated_verification_not_run`` when ANALYZE issued VERIFY. The report
    itself is Apply over admitted answers — not an MCP quota denial. Operational /
    S_R-incomplete stops get an explicit warning so clients do not read
    ``operational_budget`` as “cut off without a conclusion.”
    """
    out = dict(apply_payload)
    out["inquiry_session_id"] = inquiry_session_id
    out["stop_reason"] = stop_reason
    out["inquire_stop_reason"] = stop_reason
    if stop_reason == CHAT_ISOLATED_VERIFICATION_NOT_RUN:
        out["status"] = STATUS_ACTIVE
    else:
        out["status"] = STATUS_STOPPED
    if operational_status is not None:
        out["inquire_operational_status"] = operational_status
    if diagnostics is not None:
        out["inquire_diagnostics"] = dict(diagnostics)
    report = dict(out.get("report") or {})
    if stop_reason is not None:
        report["inquire_stop_reason"] = stop_reason
    out["report"] = report
    warnings = list(out.get("warnings") or [])
    if stop_reason == CHAT_ISOLATED_VERIFICATION_NOT_RUN:
        warnings.append(
            {
                "code": "inquire_verification_not_run",
                "message": (
                    "The deciding answers were not independently re-checked. "
                    "This report is Apply over admitted answers."
                ),
            }
        )
        out["warnings"] = warnings
    elif stop_reason in _OPERATIONAL_OR_INCOMPLETE_STOPS:
        warnings.append(
            {
                "code": "inquire_operational_stop",
                "message": (
                    "Inquire ANALYZE stopped for an operational or resolving-support "
                    f"reason ({stop_reason}) before verified_resolved_consequence. "
                    "This report is Apply over admitted answers; it is not an MCP "
                    "quota denial."
                ),
            }
        )
        out["warnings"] = warnings
    return out


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


def _chat_stop_marker(
    *,
    inquiry_session_id: str,
    revision: int,
    status: str,
    stop_reason: str | None,
    operational_status: Any = None,
    diagnostics: Any = None,
    admitted: Any = None,
    already_issued: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "_chat_stop": True,
        "inquiry_session_id": inquiry_session_id,
        "revision": revision,
        "status": status,
        "stop_reason": stop_reason,
        "admitted": admitted,
    }
    if operational_status is not None:
        out["operational_status"] = operational_status
    if diagnostics is not None:
        out["diagnostics"] = diagnostics
    if already_issued:
        out["_chat_report_already_issued"] = True
    return out


async def _active_task_or_terminal(
    db: AsyncSession,
    *,
    user: User,
    wire: dict[str, Any],
    already_issued: bool = False,
) -> dict[str, Any]:
    """Map persist wire → chat JSON (ACTIVE task or Apply-report marker)."""
    session_id = str(wire["inquiry_session_id"])
    revision = int(wire["revision"])
    status = str(wire["status"])
    action = _directive_action(wire)

    if action == "VERIFY":
        return _chat_stop_marker(
            inquiry_session_id=session_id,
            revision=revision,
            status=STATUS_ACTIVE,
            stop_reason=CHAT_ISOLATED_VERIFICATION_NOT_RUN,
            admitted=wire.get("admitted"),
            already_issued=already_issued,
        )

    if action == "STOP" or status == STATUS_STOPPED:
        directive = wire.get("directive")
        directive = directive if isinstance(directive, dict) else {}
        return _chat_stop_marker(
            inquiry_session_id=session_id,
            revision=revision,
            status=STATUS_STOPPED,
            stop_reason=wire.get("stop_reason"),
            operational_status=directive.get("operational_status"),
            diagnostics=directive.get("diagnostics"),
            admitted=wire.get("admitted"),
            already_issued=already_issued,
        )

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
    task, answer_guidance = await get_chat_task_for_session(
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
        answer_guidance=answer_guidance,
    )


async def chat_evaluate_start(
    db: AsyncSession,
    *,
    user: User,
    decision_tree: DecisionTree,
    artifact: ReasoningCompiledArtifact,
    graph: DTGraph,
) -> dict[str, Any]:
    """Start inquiry (φ empty); return blind task or Apply-report marker."""
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
    """Admit one ACQUIRE answer; never VERIFY. Return next task or Apply-report marker."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    issued = await chat_report_issued_payload(
        db, user=user, inquiry_session_id=inquiry_session_id
    )
    if issued is not None:
        stop_reason = issued.get("stop_reason")
        status = (
            STATUS_ACTIVE
            if stop_reason == CHAT_ISOLATED_VERIFICATION_NOT_RUN
            else STATUS_STOPPED
        )
        return _chat_stop_marker(
            inquiry_session_id=str(inquiry_session_id),
            revision=int(issued.get("revision") or session.revision),
            status=status,
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
            operational_status=issued.get("operational_status"),
            diagnostics=issued.get("diagnostics"),
            already_issued=True,
        )

    idempotency_key = chat_admit_idempotency_key(
        inquiry_session_id=inquiry_session_id,
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=provenance_id,
    )
    replay = await lookup_admit_receipt(
        db,
        user=user,
        inquiry_session_id=inquiry_session_id,
        idempotency_key=idempotency_key,
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=provenance_id,
        reject_stale_replay=True,
    )
    if replay is not None:
        return await _active_task_or_terminal(
            db, user=user, wire=replay, already_issued=True
        )

    expected_revision = int(session.revision)
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


async def _admitted_assertions_for_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
) -> list[InquiryAdmittedAssertion]:
    """Load authorized admitted assertions in deterministic question order."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    result = await db.execute(
        select(InquiryAdmittedAssertion).where(
            InquiryAdmittedAssertion.session_id == session.id  # type: ignore[arg-type]
        )
    )
    return list(result.scalars().all())


def admitted_assertions_to_apply_envelope(
    rows: list[InquiryAdmittedAssertion],
) -> dict[str, Any]:
    """Map admitted ``(question, option, provenance)`` rows to an Apply envelope."""
    answers: dict[str, str] = {}
    evidence_items: list[dict[str, str]] = []
    evidence_refs: dict[str, list[str]] = {}
    for index, row in enumerate(sorted(rows, key=lambda item: item.question_id), start=1):
        evidence_id = f"inquire-provenance-{index:04d}"
        answers[row.question_id] = row.option
        evidence_items.append(
            {
                "id": evidence_id,
                "source_id": row.provenance_id,
            }
        )
        evidence_refs[row.question_id] = [evidence_id]
    return {
        "answers": answers,
        "evidence_items": evidence_items,
        "evidence_refs": evidence_refs,
    }


async def admitted_apply_envelope_for_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
) -> dict[str, Any]:
    """Load admitted answers and preserve provenance for terminal Apply."""
    rows = await _admitted_assertions_for_session(
        db,
        user=user,
        inquiry_session_id=inquiry_session_id,
    )
    return admitted_assertions_to_apply_envelope(rows)


def apply_envelope_to_raw_json(envelope: dict[str, Any]) -> str:
    """Serialize a provenance-preserving Apply ingest envelope."""
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def should_persist_chat_report(facade: dict[str, Any]) -> bool:
    """True on the first chat report for a session; false on replay or later continue."""
    return bool(facade.get("_chat_stop")) and not facade.get("_chat_report_already_issued")


def chat_merge_kwargs(facade: dict[str, Any]) -> dict[str, Any]:
    """Keyword args for ``merge_chat_stop_onto_apply`` from a facade terminal."""
    return {
        "inquiry_session_id": str(facade["inquiry_session_id"]),
        "stop_reason": facade.get("stop_reason"),
        "operational_status": facade.get("operational_status"),
        "diagnostics": facade.get("diagnostics"),
    }
