"""Run a blind verification battery to a Phase-2 VerificationDecision."""

from __future__ import annotations

from dataclasses import dataclass

from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.types import ExtractionResult, Extractor
from smeme.reasoning.orchestration.inquire.verification.policy import (
    DEFAULT_VERIFICATION_POLICY,
    BlindVerificationPolicy,
)
from smeme.reasoning.orchestration.inquire.verification.present import (
    observation_from_result,
    render_blind_task,
)
from smeme.reasoning.orchestration.inquire.verify import VerificationStep
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.policy import VerificationRequest
from smeme.reasoning.runtime.inquire.transition import (
    VerificationDecision,
    apply_verification_decision,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    ExtractionTask,
    InquiryDirective,
    VerificationKey,
    WorksheetCatalog,
)


@dataclass(frozen=True, slots=True)
class VerificationBatteryOutcome:
    """Terminal battery result plus the last blind task/result for observability."""

    step: VerificationStep
    task: ExtractionTask | None
    result: ExtractionResult | None


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


def _bind_result(
    *,
    question_id: str,
    task: ExtractionTask,
    result: ExtractionResult,
) -> None:
    if task.question.question_id != question_id:
        msg = (
            f"issued task question_id {task.question.question_id!r} does not match "
            f"directive question_id {question_id!r}"
        )
        raise PremiseInvariantError(msg)
    if result.question_id != task.question.question_id:
        msg = (
            f"extraction result question_id {result.question_id!r} does not match "
            f"issued task {task.question.question_id!r}"
        )
        raise PremiseInvariantError(msg)


def run_verification(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    directive: InquiryDirective,
    worksheet_catalog: WorksheetCatalog,
    extractor: Extractor,
    artifact_identity: str,
    verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY,
) -> VerificationBatteryOutcome:
    """Schedule → extract → observe → decide → ``apply_verification_decision``.

    Protocol/invariant failures raise. ``Insufficient`` means the experiment
    completed but did not satisfy the policy.
    """
    if directive.action != "VERIFY":
        msg = f"run_verification requires VERIFY directive, got {directive.action!r}"
        raise PremiseInvariantError(msg)
    if directive.verification_key is None:
        raise PremiseInvariantError("VERIFY directive missing verification_key")
    if directive.question_id is None:
        raise PremiseInvariantError("VERIFY directive missing question_id")

    key = directive.verification_key
    if key.question_id != directive.question_id:
        msg = "directive.verification_key.question_id must match directive.question_id"
        raise PremiseInvariantError(msg)
    if key.pv_version != verification_policy.pv_version:
        msg = (
            f"directive verification_key.pv_version {key.pv_version!r} does not match "
            f"verification_policy.pv_version {verification_policy.pv_version!r}"
        )
        raise PremiseInvariantError(msg)

    assertion = _live_assertion_for_key(admitted, key)
    catalog_item = worksheet_catalog[directive.question_id]
    canonical_options = catalog_item.options

    state = verification_policy.initial_state(
        VerificationRequest(verification_key=key),
        canonical_options=canonical_options,
    )

    last_task: ExtractionTask | None = None
    last_result: ExtractionResult | None = None
    decision: VerificationDecision | None = None

    while True:
        decision = verification_policy.decision(state)
        if decision is not None:
            break
        request = verification_policy.next_evaluation(state)
        if request is None:
            raise PremiseInvariantError("verification schedule exhausted without decision")
        task = render_blind_task(
            worksheet_catalog,
            directive.question_id,
            request.presentation,
        )
        result = extractor.extract(task)
        _bind_result(question_id=directive.question_id, task=task, result=result)
        observation = observation_from_result(result=result, request=request)
        state = verification_policy.observe(state, observation)
        last_task = task
        last_result = result

    assert decision is not None
    transition = apply_verification_decision(
        ir=ir,
        admitted=admitted,
        verified=verified,
        assertion=assertion,
        artifact_identity=artifact_identity,
        pv_version=verification_policy.pv_version,
        decision=decision,
    )
    return VerificationBatteryOutcome(
        step=VerificationStep(
            admitted=transition.admitted,
            verified=transition.verified,
            base_changed=transition.base_changed,
            status=transition.status,
            decision=decision,
        ),
        task=last_task,
        result=last_result,
    )
