"""Inquire Phase 6 persist service: session resource around Phase 5 handlers.

Kernel stays stateless. This layer owns durable preimage + revision + receipts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import (
    DecisionTree,
    InquiryAdmittedAssertion,
    InquiryMutationReceipt,
    InquirySession,
    InquirySessionEvent,
    InquiryVerifiedAssertion,
    ReasoningCompiledArtifact,
    User,
)
from smeme.decision_tree.models import DTGraph
from smeme.mcp.inquire import handlers as inquire_handlers
from smeme.mcp.inquire.codec import (
    decode_worksheet_catalog,
    encode_admitted,
    encode_verified,
)
from smeme.mcp.inquire.handlers import InquireHandlerError, server_pv_version
from smeme.reasoning.ir.serialize import ir_from_json, ir_to_json
from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.persist.auth import load_owned_session
from smeme.reasoning.orchestration.inquire.persist.catalog import (
    catalog_json_dict,
    worksheet_catalog_from_graph_and_ir,
)
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    ReasoningAssumptions,
    assumptions_from_lists,
)

STATUS_ACTIVE = "ACTIVE"
STATUS_STOPPED = "STOPPED"
STATUS_ABANDONED = "ABANDONED"

EVENT_SESSION_STARTED = "SESSION_STARTED"
EVENT_ASSERTION_ADMITTED = "ASSERTION_ADMITTED"
EVENT_ACQUIRE_ABSTAINED = "ACQUIRE_ABSTAINED"
EVENT_VERIFICATION_RETAINED = "VERIFICATION_RETAINED"
EVENT_VERIFICATION_INSUFFICIENT = "VERIFICATION_INSUFFICIENT"
EVENT_SESSION_STOPPED = "SESSION_STOPPED"
EVENT_SESSION_ABANDONED = "SESSION_ABANDONED"


def canonical_request_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON (sorted object keys; arrays keep caller order)."""
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _assumptions_storage(assumptions: ReasoningAssumptions) -> dict[str, Any]:
    wire = assumptions.to_wire()
    return dict(wire) if wire is not None else {}


def _assumptions_from_storage(raw: dict[str, Any] | None) -> ReasoningAssumptions:
    if not raw:
        return EMPTY_ASSUMPTIONS
    return assumptions_from_lists(
        raw.get("force_reachable_ids"),
        raw.get("force_unreachable_ids"),
    )


def _force_lists(
    assumptions: ReasoningAssumptions,
) -> tuple[list[str] | None, list[str] | None]:
    if assumptions.is_empty():
        return None, None
    return sorted(assumptions.force_reachable) or None, sorted(
        assumptions.force_unreachable
    ) or None


async def _load_admitted(db: AsyncSession, session_id: UUID) -> tuple[list[dict[str, Any]], str]:
    from smeme.reasoning.runtime.inquire.types import (
        AdmittedAssertion,
        CanonicalProvenanceId,
    )

    result = await db.execute(
        select(InquiryAdmittedAssertion).where(InquiryAdmittedAssertion.session_id == session_id)
    )
    rows = list(result.scalars().all())
    admitted = tuple(
        AdmittedAssertion(
            question_id=r.question_id,
            option=r.option,
            provenance_id=CanonicalProvenanceId(r.provenance_id),
        )
        for r in rows
    )
    encoded = encode_admitted(admitted)
    return encoded, json.dumps(encoded)


async def _load_verified(db: AsyncSession, session_id: UUID) -> tuple[list[dict[str, Any]], str]:
    from smeme.reasoning.runtime.inquire.types import VerificationKey

    result = await db.execute(
        select(InquiryVerifiedAssertion).where(InquiryVerifiedAssertion.session_id == session_id)
    )
    rows = list(result.scalars().all())
    keys = tuple(
        VerificationKey(
            artifact_identity=r.artifact_identity,
            question_id=r.question_id,
            option=r.option,
            provenance_identity=r.provenance_identity,
            pv_version=r.pv_version,
        )
        for r in rows
    )
    encoded = encode_verified(keys)
    return encoded, json.dumps(encoded)


async def _replace_admitted(
    db: AsyncSession, session_id: UUID, admitted_rows: list[dict[str, Any]]
) -> None:
    await db.execute(
        delete(InquiryAdmittedAssertion).where(InquiryAdmittedAssertion.session_id == session_id)
    )
    for row in admitted_rows:
        db.add(
            InquiryAdmittedAssertion(
                session_id=session_id,
                question_id=str(row["question_id"]),
                option=str(row["option"]),
                provenance_id=str(row["provenance_id"]),
            )
        )


async def _replace_verified(
    db: AsyncSession, session_id: UUID, verified_rows: list[dict[str, Any]]
) -> None:
    await db.execute(
        delete(InquiryVerifiedAssertion).where(InquiryVerifiedAssertion.session_id == session_id)
    )
    for row in verified_rows:
        db.add(
            InquiryVerifiedAssertion(
                session_id=session_id,
                artifact_identity=str(row["artifact_identity"]),
                question_id=str(row["question_id"]),
                option=str(row["option"]),
                provenance_identity=str(row["provenance_identity"]),
                pv_version=str(row["pv_version"]),
            )
        )


def _append_event(
    db: AsyncSession,
    *,
    session: InquirySession,
    event_type: str,
    payload: dict[str, Any] | None = None,
    receipt_id: UUID | None = None,
) -> None:
    db.add(
        InquirySessionEvent(
            session_id=session.id,
            event_type=event_type,
            revision=int(session.revision),
            receipt_id=receipt_id,
            payload=dict(payload or {}),
        )
    )


async def _resolve_execution_artifact(
    db: AsyncSession, session: InquirySession
) -> tuple[ReasoningCompiledArtifact, IR]:
    if session.artifact_id is None:
        raise InquireHandlerError(
            "inquire_artifact_unavailable",
            "Compiled artifact for this inquiry session is no longer available.",
        )
    result = await db.execute(
        select(ReasoningCompiledArtifact).where(ReasoningCompiledArtifact.id == session.artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise InquireHandlerError(
            "inquire_artifact_unavailable",
            "Compiled artifact for this inquiry session is no longer available.",
        )
    if not artifact.artifact_hash or artifact.artifact_hash != session.artifact_identity:
        raise InquireHandlerError(
            "inquire_artifact_mismatch",
            "Compiled artifact identity does not match the frozen session snapshot.",
        )
    try:
        ir = ir_from_json(dict(artifact.ir_json))
    except (KeyError, ValueError, TypeError) as exc:
        raise InquireHandlerError(
            "inquire_invalid_payload",
            f"Stored IR could not be loaded: {exc}",
        ) from exc
    return artifact, ir


def _require_active(session: InquirySession) -> None:
    if session.status != STATUS_ACTIVE:
        raise InquireHandlerError(
            "inquire_session_not_active",
            f"Inquiry session status is {session.status!r}; mutations require ACTIVE.",
        )


def _require_policy_pin(session: InquirySession) -> None:
    pv = server_pv_version()
    if session.pv_version != pv:
        raise InquireHandlerError(
            "inquire_policy_mismatch",
            f"Session pv_version {session.pv_version!r} does not match server {pv!r}.",
        )


def _check_expected_revision(session: InquirySession, expected_revision: int | None) -> None:
    if expected_revision is None:
        return
    if int(expected_revision) != int(session.revision):
        raise InquireHandlerError(
            "inquire_revision_conflict",
            f"expected_revision {expected_revision} but session revision is {session.revision}.",
        )


def _apply_stop_if_needed(session: InquirySession, directive: dict[str, Any]) -> bool:
    """If directive is STOP and session ACTIVE, persist STOP. Returns whether status changed."""
    if directive.get("action") != "STOP":
        return False
    if session.status != STATUS_ACTIVE:
        return False
    session.status = STATUS_STOPPED
    session.stop_reason = directive.get("stop_reason")
    session.stopped_at = datetime.now(UTC)
    session.revision = int(session.revision) + 1
    session.updated_at = datetime.now(UTC)
    return True


def _session_wire_envelope(
    session: InquirySession,
    analyze_payload: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "inquiry_session_id": str(session.id),
        "revision": int(session.revision),
        "status": session.status,
        "directive": analyze_payload["directive"],
        "pv_version": analyze_payload.get("pv_version", session.pv_version),
    }
    if "evaluations" in analyze_payload:
        out["evaluations"] = analyze_payload["evaluations"]
    if session.stop_reason is not None:
        out["stop_reason"] = session.stop_reason
    if extra:
        out.update(extra)
    return out


def _run_analyze_for_session(
    *,
    ir: IR,
    session: InquirySession,
    admitted_json: str,
    verified_json: str,
) -> dict[str, Any]:
    _require_policy_pin(session)
    catalog_json = json.dumps(session.worksheet_catalog)
    fr, fu = _force_lists(_assumptions_from_storage(session.assumptions))
    return inquire_handlers.analyze(
        ir_json=json.dumps(ir_to_json(ir)),
        worksheet_catalog_json=catalog_json,
        admitted_json=admitted_json,
        verified_json=verified_json,
        artifact_identity=session.artifact_identity,
        force_reachable_ids=fr,
        force_unreachable_ids=fu,
    )


async def start_inquiry(
    db: AsyncSession,
    *,
    user: User,
    decision_tree: DecisionTree,
    artifact: ReasoningCompiledArtifact,
    graph: DTGraph,
    force_reachable_ids: list[str] | None = None,
    force_unreachable_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create session on frozen artifact; ANALYZE; persist STOP if needed."""
    if not artifact.artifact_hash:
        raise InquireHandlerError(
            "no_reasoning_artifact",
            "This decision tree's compiled artifact is missing identity.",
        )
    try:
        ir = ir_from_json(dict(artifact.ir_json))
    except (KeyError, ValueError, TypeError) as exc:
        raise InquireHandlerError(
            "inquire_invalid_payload",
            f"Compiled IR could not be loaded: {exc}",
        ) from exc

    catalog = worksheet_catalog_from_graph_and_ir(graph, ir)
    assumptions = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
    pv = server_pv_version()

    session = InquirySession(
        owner_user_id=user.id,
        decision_tree_id=decision_tree.id,
        artifact_id=artifact.id,
        artifact_identity=artifact.artifact_hash,
        worksheet_catalog=catalog_json_dict(catalog),
        pv_version=pv,
        assumptions=_assumptions_storage(assumptions),
        status=STATUS_ACTIVE,
        revision=1,
    )
    db.add(session)
    await db.flush()

    analyze_payload = _run_analyze_for_session(
        ir=ir,
        session=session,
        admitted_json="[]",
        verified_json="[]",
    )
    stopped = _apply_stop_if_needed(session, analyze_payload["directive"])
    _append_event(
        db,
        session=session,
        event_type=EVENT_SESSION_STARTED,
        payload={
            "decision_tree_id": str(decision_tree.id),
            "artifact_identity": session.artifact_identity,
        },
    )
    if stopped:
        _append_event(
            db,
            session=session,
            event_type=EVENT_SESSION_STOPPED,
            payload={"stop_reason": session.stop_reason},
        )
    await db.commit()
    await db.refresh(session)
    return _session_wire_envelope(session, analyze_payload)


async def next_directive(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Re-ANALYZE persisted state. Read-only — never writes."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    _check_expected_revision(session, expected_revision)
    _require_policy_pin(session)
    _, ir = await _resolve_execution_artifact(db, session)
    _, admitted_json = await _load_admitted(db, session.id)
    _, verified_json = await _load_verified(db, session.id)
    analyze_payload = _run_analyze_for_session(
        ir=ir,
        session=session,
        admitted_json=admitted_json,
        verified_json=verified_json,
    )
    if session.status == STATUS_ACTIVE and analyze_payload["directive"].get("action") == "STOP":
        raise InquireHandlerError(
            "inquire_session_invariant",
            "ANALYZE returned STOP while session status is still ACTIVE; "
            "mutations must persist STOP.",
        )
    # Explicitly no commit / no write
    return _session_wire_envelope(session, analyze_payload)


async def get_task_for_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    question_id: str,
) -> dict[str, Any]:
    """Blind render from frozen catalog only."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=False
    )
    catalog_json = json.dumps(session.worksheet_catalog)
    # Validate catalog still decodes; never touch live graph
    decode_worksheet_catalog(catalog_json)
    return inquire_handlers.get_task(
        worksheet_catalog_json=catalog_json,
        question_id=question_id,
    )


async def _lookup_receipt(
    db: AsyncSession,
    *,
    session_id: UUID,
    idempotency_key: str,
    request_hash: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        select(InquiryMutationReceipt).where(
            InquiryMutationReceipt.session_id == session_id,
            InquiryMutationReceipt.idempotency_key == idempotency_key,
        )
    )
    receipt = result.scalar_one_or_none()
    if receipt is None:
        return None
    if receipt.request_hash != request_hash:
        raise InquireHandlerError(
            "inquire_idempotency_conflict",
            "idempotency_key was already used with a different request payload.",
        )
    return dict(receipt.response_json)


async def admit_to_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    expected_revision: int,
    question_id: str,
    selected_option: str | None,
    provenance_id: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "idempotency_key must be a non-empty string"
        )
    request_hash = canonical_request_hash(
        {
            "operation": "admit",
            "inquiry_session_id": str(inquiry_session_id),
            "question_id": question_id,
            "selected_option": selected_option,
            "provenance_id": provenance_id,
        }
    )

    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=True
    )
    replay = await _lookup_receipt(
        db,
        session_id=session.id,
        idempotency_key=idempotency_key.strip(),
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    _require_active(session)
    _check_expected_revision(session, expected_revision)
    _require_policy_pin(session)
    _, ir = await _resolve_execution_artifact(db, session)
    admitted_list, admitted_json = await _load_admitted(db, session.id)
    catalog_json = json.dumps(session.worksheet_catalog)

    admit_payload = inquire_handlers.admit(
        ir_json=json.dumps(ir_to_json(ir)),
        worksheet_catalog_json=catalog_json,
        admitted_json=admitted_json,
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=provenance_id,
    )

    event_type = EVENT_ACQUIRE_ABSTAINED
    if admit_payload["status"] == "applied":
        await _replace_admitted(db, session.id, admit_payload["admitted"])
        session.revision = int(session.revision) + 1
        session.updated_at = datetime.now(UTC)
        event_type = EVENT_ASSERTION_ADMITTED
        admitted_json = json.dumps(admit_payload["admitted"])
    else:
        # abstain: no revision bump
        admitted_json = json.dumps(admitted_list)

    _, verified_json = await _load_verified(db, session.id)
    analyze_payload = _run_analyze_for_session(
        ir=ir,
        session=session,
        admitted_json=admitted_json,
        verified_json=verified_json,
    )
    stopped = _apply_stop_if_needed(session, analyze_payload["directive"])

    response = _session_wire_envelope(
        session,
        analyze_payload,
        extra={
            "admit_status": admit_payload["status"],
            "admitted": admit_payload["admitted"],
        },
    )

    receipt = InquiryMutationReceipt(
        session_id=session.id,
        idempotency_key=idempotency_key.strip(),
        operation="admit",
        request_hash=request_hash,
        response_json=response,
    )
    db.add(receipt)
    await db.flush()
    _append_event(
        db,
        session=session,
        event_type=event_type,
        payload={"question_id": question_id},
        receipt_id=receipt.id,
    )
    if stopped:
        _append_event(
            db,
            session=session,
            event_type=EVENT_SESSION_STOPPED,
            payload={"stop_reason": session.stop_reason},
            receipt_id=receipt.id,
        )
    await db.commit()
    return response


async def verify_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    expected_revision: int,
    verification_key: dict[str, Any],
    observations: list[dict[str, Any]],
    idempotency_key: str,
) -> dict[str, Any]:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "idempotency_key must be a non-empty string"
        )
    request_hash = canonical_request_hash(
        {
            "operation": "verify",
            "inquiry_session_id": str(inquiry_session_id),
            "verification_key": verification_key,
            "observations": observations,
        }
    )

    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=True
    )
    replay = await _lookup_receipt(
        db,
        session_id=session.id,
        idempotency_key=idempotency_key.strip(),
        request_hash=request_hash,
    )
    if replay is not None:
        return replay

    _require_active(session)
    _check_expected_revision(session, expected_revision)
    _require_policy_pin(session)
    _, ir = await _resolve_execution_artifact(db, session)
    _, admitted_json = await _load_admitted(db, session.id)
    _, verified_json = await _load_verified(db, session.id)
    catalog_json = json.dumps(session.worksheet_catalog)
    fr, fu = _force_lists(_assumptions_from_storage(session.assumptions))

    verify_payload = inquire_handlers.verify(
        ir_json=json.dumps(ir_to_json(ir)),
        worksheet_catalog_json=catalog_json,
        admitted_json=admitted_json,
        verified_json=verified_json,
        artifact_identity=session.artifact_identity,
        verification_key_json=json.dumps(verification_key),
        observations_json=json.dumps(observations),
        force_reachable_ids=fr,
        force_unreachable_ids=fu,
    )

    decision = verify_payload.get("decision") or {}
    kind = decision.get("kind")
    bumped = False
    if kind == "retain":
        await _replace_admitted(db, session.id, verify_payload["admitted"])
        await _replace_verified(db, session.id, verify_payload["verified"])
        session.revision = int(session.revision) + 1
        session.updated_at = datetime.now(UTC)
        bumped = True
        event_type = EVENT_VERIFICATION_RETAINED
        admitted_json = json.dumps(verify_payload["admitted"])
        verified_json = json.dumps(verify_payload["verified"])
    elif kind == "insufficient":
        event_type = EVENT_VERIFICATION_INSUFFICIENT
        # no revision bump; state unchanged
    else:
        # Retract/Replace not expected on MCP path; still treat as preimage change
        await _replace_admitted(db, session.id, verify_payload["admitted"])
        await _replace_verified(db, session.id, verify_payload["verified"])
        session.revision = int(session.revision) + 1
        session.updated_at = datetime.now(UTC)
        bumped = True
        event_type = EVENT_VERIFICATION_RETAINED
        admitted_json = json.dumps(verify_payload["admitted"])
        verified_json = json.dumps(verify_payload["verified"])

    analyze_payload = _run_analyze_for_session(
        ir=ir,
        session=session,
        admitted_json=admitted_json,
        verified_json=verified_json,
    )
    stopped = _apply_stop_if_needed(session, analyze_payload["directive"])

    response = _session_wire_envelope(
        session,
        analyze_payload,
        extra={
            "decision": decision,
            "verify_status": verify_payload.get("status"),
            "base_changed": verify_payload.get("base_changed"),
            "admitted": verify_payload["admitted"],
            "verified": verify_payload["verified"],
            "revision_bumped": bumped or stopped,
        },
    )

    receipt = InquiryMutationReceipt(
        session_id=session.id,
        idempotency_key=idempotency_key.strip(),
        operation="verify",
        request_hash=request_hash,
        response_json=response,
    )
    db.add(receipt)
    await db.flush()
    _append_event(
        db,
        session=session,
        event_type=event_type,
        payload={"decision_kind": kind},
        receipt_id=receipt.id,
    )
    if stopped:
        _append_event(
            db,
            session=session,
            event_type=EVENT_SESSION_STOPPED,
            payload={"stop_reason": session.stop_reason},
            receipt_id=receipt.id,
        )
    await db.commit()
    return response


async def abandon_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
) -> dict[str, Any]:
    """Mark session ABANDONED (service API; no MCP tool in Phase 6)."""
    session = await load_owned_session(
        db, user=user, inquiry_session_id=inquiry_session_id, for_update=True
    )
    if session.status == STATUS_ABANDONED:
        return {
            "inquiry_session_id": str(session.id),
            "revision": int(session.revision),
            "status": session.status,
        }
    session.status = STATUS_ABANDONED
    session.revision = int(session.revision) + 1
    session.updated_at = datetime.now(UTC)
    _append_event(db, session=session, event_type=EVENT_SESSION_ABANDONED)
    await db.commit()
    await db.refresh(session)
    return {
        "inquiry_session_id": str(session.id),
        "revision": int(session.revision),
        "status": session.status,
    }


__all__ = [
    "STATUS_ABANDONED",
    "STATUS_ACTIVE",
    "STATUS_STOPPED",
    "abandon_session",
    "admit_to_session",
    "canonical_request_hash",
    "get_task_for_session",
    "next_directive",
    "start_inquiry",
    "verify_session",
]
