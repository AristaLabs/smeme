"""VERIFY bridge: bind result to issued task, construct ``VerificationRequest``, apply ``P_v``."""

from __future__ import annotations

from dataclasses import dataclass

from smeme.reasoning.ir.types import IR
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.policy import (
    VerificationPolicy,
    VerificationRequest,
    VerificationResult,
)
from smeme.reasoning.runtime.inquire.transition import (
    TransitionStatus,
    VerificationDecision,
    VerificationTransition,
    apply_verification_decision,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    ExtractionTask,
    InquiryDirective,
    VerificationKey,
)
from smeme.reasoning.orchestration.inquire.types import ExtractionResult


@dataclass(frozen=True, slots=True)
class VerificationStep:
    admitted: tuple[AdmittedAssertion, ...]
    verified: frozenset[VerificationKey]
    base_changed: bool
    status: TransitionStatus
    decision: VerificationDecision


def _require_result_matches_task(
    task: ExtractionTask,
    *,
    question_id: str,
) -> None:
    if question_id != task.question.question_id:
        msg = (
            f"extraction result question_id {question_id!r} does not match "
            f"issued task {task.question.question_id!r}"
        )
        raise PremiseInvariantError(msg)


def _live_assertion_for_key(
    admitted: tuple[AdmittedAssertion, ...],
    key: VerificationKey,
) -> AdmittedAssertion:
    matches = [
        item
        for item in admitted
        if item.question_id == key.question_id
        and item.option == key.option
        and str(item.provenance_id) == key.provenance_identity
    ]
    if len(matches) != 1:
        msg = (
            f"no unique live assertion for verification_key "
            f"({key.question_id!r}, {key.option!r}, {key.provenance_identity!r})"
        )
        raise PremiseInvariantError(msg)
    return matches[0]


def verify_extraction(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    directive: InquiryDirective,
    task: ExtractionTask,
    result: ExtractionResult,
    policy: VerificationPolicy,
    artifact_identity: str,
    pv_version: str,
) -> VerificationStep:
    """Run ``P_v`` on a bound extraction result; apply the decision atomically.

    The assertion under verification comes from ``directive.verification_key``,
    never from ``result``. Disagreement between live option and
    ``AnsweredExtraction.selected_option`` is evidence for ``P_v``, not an
    automatic REPLACE.
    """
    if directive.action != "VERIFY":
        msg = f"verify_extraction requires VERIFY directive, got {directive.action!r}"
        raise PremiseInvariantError(msg)
    if directive.verification_key is None:
        raise PremiseInvariantError("VERIFY directive missing verification_key")
    if directive.question_id is None:
        raise PremiseInvariantError("VERIFY directive missing question_id")
    if result.question_id != directive.question_id:
        msg = (
            f"extraction result question_id {result.question_id!r} does not match "
            f"directive question_id {directive.question_id!r}"
        )
        raise PremiseInvariantError(msg)
    _require_result_matches_task(task, question_id=result.question_id)

    key = directive.verification_key
    if key.question_id != directive.question_id:
        msg = "directive.verification_key.question_id must match directive.question_id"
        raise PremiseInvariantError(msg)

    assertion = _live_assertion_for_key(admitted, key)
    request = VerificationRequest(verification_key=key)
    kernel_result = VerificationResult(payload=result)
    decision = policy.decide(request, kernel_result)
    transition: VerificationTransition = apply_verification_decision(
        ir=ir,
        admitted=admitted,
        verified=verified,
        assertion=assertion,
        artifact_identity=artifact_identity,
        pv_version=pv_version,
        decision=decision,
    )
    return VerificationStep(
        admitted=transition.admitted,
        verified=transition.verified,
        base_changed=transition.base_changed,
        status=transition.status,
        decision=decision,
    )
