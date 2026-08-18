"""Inquire MCP handlers (no FastMCP). Thin adapter over orchestration + kernel."""

from __future__ import annotations

from typing import Any

from smeme.mcp.inquire.codec import (
    InquireCodecError,
    assert_blind_task_payload,
    decode_admitted,
    decode_budget,
    decode_ir,
    decode_verification_key,
    decode_verified,
    decode_wire_observations,
    decode_worksheet_catalog,
    encode_admitted,
    encode_blind_task,
    encode_decision,
    encode_directive,
    encode_evaluations,
    encode_verified,
)
from smeme.reasoning.orchestration.inquire.admit import admit_extraction
from smeme.reasoning.orchestration.inquire.types import AnsweredExtraction
from smeme.reasoning.orchestration.inquire.verification.policy import (
    DEFAULT_VERIFICATION_POLICY,
)
from smeme.reasoning.orchestration.inquire.verification.transcript import (
    evaluate_verification_transcript,
    prepare_verification_battery,
)
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    AssumptionsError,
    assumptions_from_lists,
    validate_assumptions,
)
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.input_validation import ReasoningInputValidationError
from smeme.reasoning.runtime.inquire import analyze_inquiry, build_extractor_issue
from smeme.reasoning.runtime.inquire.types import CanonicalProvenanceId


class InquireHandlerError(Exception):
    """Domain failure with stable MCP ``error.code``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _map_invariant(exc: PremiseInvariantError) -> InquireHandlerError:
    msg = str(exc)
    lower = msg.lower()
    if "already admitted" in lower or "not among" in lower or "admission" in lower:
        return InquireHandlerError("admission_rejected", msg)
    if "assertion" in lower and "mismatch" in lower:
        return InquireHandlerError("assertion_mismatch", msg)
    if "no unique live assertion" in lower:
        return InquireHandlerError("assertion_mismatch", msg)
    if "unknown question" in lower:
        return InquireHandlerError("inquire_unknown_question", msg)
    if "verification" in lower or "evaluation_id" in lower or "transcript" in lower:
        return InquireHandlerError("inquire_verification_protocol", msg)
    return InquireHandlerError("inquire_verification_protocol", msg)


def server_pv_version() -> str:
    return DEFAULT_VERIFICATION_POLICY.pv_version


def get_task(*, worksheet_catalog_json: str, question_id: str) -> dict[str, Any]:
    """Blind catalog render. Not directive authorization. No ``ir_json``."""
    if not isinstance(question_id, str) or not question_id.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "question_id must be a non-empty string"
        )
    try:
        catalog = decode_worksheet_catalog(worksheet_catalog_json)
    except InquireCodecError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc
    if question_id not in catalog:
        raise InquireHandlerError(
            "inquire_unknown_question",
            f"question_id {question_id!r} is not in the worksheet catalog",
        )
    task = build_extractor_issue(catalog, question_id)
    payload = encode_blind_task(task)
    assert_blind_task_payload(payload)
    return payload


def analyze(
    *,
    ir_json: str,
    worksheet_catalog_json: str,
    admitted_json: str,
    verified_json: str,
    artifact_identity: str,
    force_reachable_ids: list[str] | None = None,
    force_unreachable_ids: list[str] | None = None,
    budget_json: str | None = None,
) -> dict[str, Any]:
    """Run ANALYZE with server-owned ``pv_version``; attach VERIFY evaluations when needed."""
    if not isinstance(artifact_identity, str) or not artifact_identity.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "artifact_identity must be a non-empty string"
        )
    try:
        ir = decode_ir(ir_json)
        catalog = decode_worksheet_catalog(worksheet_catalog_json)
        admitted = decode_admitted(admitted_json)
        verified = decode_verified(verified_json)
        budget = decode_budget(budget_json)
    except InquireCodecError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc

    assumptions = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
    try:
        validate_assumptions(ir, assumptions)
    except AssumptionsError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc

    pv = server_pv_version()
    try:
        directive = analyze_inquiry(
            ir,
            admitted,
            assumptions if not assumptions.is_empty() else EMPTY_ASSUMPTIONS,
            verified,
            budget,
            catalog,
            artifact_identity=artifact_identity,
            pv_version=pv,
        )
    except PremiseInvariantError as exc:
        raise _map_invariant(exc) from exc

    out: dict[str, Any] = {
        "directive": encode_directive(directive),
        "pv_version": pv,
        "admitted": encode_admitted(admitted),
        "verified": encode_verified(verified),
    }
    if directive.action == "VERIFY":
        if directive.verification_key is None:
            raise InquireHandlerError(
                "inquire_verification_protocol",
                "VERIFY directive missing verification_key",
            )
        try:
            prepared = prepare_verification_battery(
                verification_key=directive.verification_key,
                worksheet_catalog=catalog,
                verification_policy=DEFAULT_VERIFICATION_POLICY,
            )
        except PremiseInvariantError as exc:
            raise _map_invariant(exc) from exc
        out["evaluations"] = encode_evaluations(prepared.evaluations)
    return out


def admit(
    *,
    ir_json: str,
    worksheet_catalog_json: str,
    admitted_json: str,
    question_id: str,
    selected_option: str | None,
    provenance_id: str | None,
) -> dict[str, Any]:
    """Admit an ACQUIRE answer, or report abstain without mutation."""
    try:
        ir = decode_ir(ir_json)
        catalog = decode_worksheet_catalog(worksheet_catalog_json)
        admitted = decode_admitted(admitted_json)
    except InquireCodecError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc

    if not isinstance(question_id, str) or not question_id.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "question_id must be a non-empty string"
        )
    if question_id not in catalog:
        raise InquireHandlerError(
            "inquire_unknown_question",
            f"question_id {question_id!r} is not in the worksheet catalog",
        )

    if selected_option is None:
        return {
            "admitted": encode_admitted(admitted),
            "status": "abstained",
        }

    if not isinstance(selected_option, str) or not selected_option.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload",
            "selected_option must be a non-empty string when not abstaining",
        )
    if provenance_id is None or not isinstance(provenance_id, str) or not provenance_id.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload",
            "provenance_id is required when admitting an answered extraction",
        )

    task = build_extractor_issue(catalog, question_id)
    result = AnsweredExtraction(
        question_id=question_id,
        selected_option=selected_option,
        provenance_id=CanonicalProvenanceId(provenance_id),
    )
    try:
        step = admit_extraction(ir, admitted, task=task, result=result)
    except PremiseInvariantError as exc:
        raise _map_invariant(exc) from exc
    except ReasoningInputValidationError as exc:
        raise InquireHandlerError("admission_rejected", str(exc)) from exc

    return {
        "admitted": encode_admitted(step.admitted),
        "status": step.status,
    }


def verify(
    *,
    ir_json: str,
    worksheet_catalog_json: str,
    admitted_json: str,
    verified_json: str,
    artifact_identity: str,
    verification_key_json: str,
    observations_json: str,
    force_reachable_ids: list[str] | None = None,
    force_unreachable_ids: list[str] | None = None,
    budget_json: str | None = None,
) -> dict[str, Any]:
    """Re-ANALYZE gate, then evaluate observation transcript under server ``P_v``."""
    if not isinstance(artifact_identity, str) or not artifact_identity.strip():
        raise InquireHandlerError(
            "inquire_invalid_payload", "artifact_identity must be a non-empty string"
        )
    try:
        ir = decode_ir(ir_json)
        catalog = decode_worksheet_catalog(worksheet_catalog_json)
        admitted = decode_admitted(admitted_json)
        verified = decode_verified(verified_json)
        budget = decode_budget(budget_json)
        from smeme.mcp.inquire.codec import parse_json_object

        key = decode_verification_key(
            parse_json_object(verification_key_json, label="verification_key_json")
        )
        observations = decode_wire_observations(observations_json)
    except InquireCodecError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc

    assumptions = assumptions_from_lists(force_reachable_ids, force_unreachable_ids)
    try:
        validate_assumptions(ir, assumptions)
    except AssumptionsError as exc:
        raise InquireHandlerError(exc.code, exc.message) from exc

    pv = server_pv_version()
    try:
        directive = analyze_inquiry(
            ir,
            admitted,
            assumptions if not assumptions.is_empty() else EMPTY_ASSUMPTIONS,
            verified,
            budget,
            catalog,
            artifact_identity=artifact_identity,
            pv_version=pv,
        )
    except PremiseInvariantError as exc:
        raise _map_invariant(exc) from exc

    if directive.action != "VERIFY":
        raise InquireHandlerError(
            "inquire_verify_target_mismatch",
            f"current directive is {directive.action!r}, not VERIFY",
        )
    if directive.verification_key is None:
        raise InquireHandlerError(
            "inquire_verification_protocol",
            "VERIFY directive missing verification_key",
        )
    if directive.verification_key != key:
        raise InquireHandlerError(
            "inquire_verify_target_mismatch",
            "submitted verification_key is not the currently issued VERIFY target",
        )
    if key.pv_version != pv:
        raise InquireHandlerError(
            "inquire_verification_protocol",
            f"verification_key.pv_version {key.pv_version!r} does not match server policy {pv!r}",
        )

    try:
        step = evaluate_verification_transcript(
            ir=ir,
            admitted=admitted,
            verified=verified,
            verification_key=key,
            worksheet_catalog=catalog,
            observations=observations,
            artifact_identity=artifact_identity,
            verification_policy=DEFAULT_VERIFICATION_POLICY,
        )
    except PremiseInvariantError as exc:
        raise _map_invariant(exc) from exc

    return {
        "admitted": encode_admitted(step.admitted),
        "verified": encode_verified(step.verified),
        "status": step.status,
        "base_changed": step.base_changed,
        "decision": encode_decision(step.decision),
    }


__all__ = [
    "InquireHandlerError",
    "admit",
    "analyze",
    "get_task",
    "server_pv_version",
    "verify",
]
