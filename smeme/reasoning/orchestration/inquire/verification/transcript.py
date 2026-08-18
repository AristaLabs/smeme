"""Verification battery prepare/evaluate without owning an Extractor.

MCP and other transports collect blind observations externally, then call
``evaluate_verification_transcript``. ``run_verification`` remains the
in-process Extractor loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.verification.policy import (
    DEFAULT_VERIFICATION_POLICY,
    BlindVerificationPolicy,
)
from smeme.reasoning.orchestration.inquire.verification.present import render_blind_task
from smeme.reasoning.orchestration.inquire.verification.types import (
    EvaluationId,
    EvaluationRequest,
    PresentationVariant,
    VerificationObservation,
    VerificationState,
)
from smeme.reasoning.orchestration.inquire.verify import VerificationStep
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.policy import VerificationRequest
from smeme.reasoning.runtime.inquire.transition import (
    Insufficient,
    Retain,
    apply_verification_decision,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    CanonicalProvenanceId,
    ExtractionTask,
    VerificationKey,
    WorksheetCatalog,
)


@dataclass(frozen=True, slots=True)
class PreparedEvaluation:
    """One scheduled blind trial for a trusted orchestrator (not an extractor)."""

    evaluation_id: EvaluationId
    task: ExtractionTask
    request: EvaluationRequest


@dataclass(frozen=True, slots=True)
class PreparedVerificationBattery:
    """Core-authored VERIFY plan: schedule + rendered blind tasks."""

    verification_key: VerificationKey
    evaluations: tuple[PreparedEvaluation, ...]
    state: VerificationState


@dataclass(frozen=True, slots=True)
class WireVerificationObservation:
    """Client-supplied trial result. Presentation is Core-owned."""

    evaluation_id: EvaluationId
    question_id: str
    selected_option: str | None
    provenance_id: CanonicalProvenanceId | None
    presentation: PresentationVariant | None = None


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


def prepare_verification_battery(
    *,
    verification_key: VerificationKey,
    worksheet_catalog: WorksheetCatalog,
    verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY,
) -> PreparedVerificationBattery:
    """Build ``ExpectedBattery = f(verification_key, catalog, server_policy)``."""
    if verification_key.pv_version != verification_policy.pv_version:
        msg = (
            f"verification_key.pv_version {verification_key.pv_version!r} does not match "
            f"verification_policy.pv_version {verification_policy.pv_version!r}"
        )
        raise PremiseInvariantError(msg)
    if verification_key.question_id not in worksheet_catalog:
        msg = f"unknown question_id {verification_key.question_id!r} in worksheet catalog"
        raise PremiseInvariantError(msg)

    canonical_options = worksheet_catalog[verification_key.question_id].options
    state = verification_policy.initial_state(
        VerificationRequest(verification_key=verification_key),
        canonical_options=canonical_options,
    )
    evaluations: list[PreparedEvaluation] = []
    for request in state.schedule:
        task = render_blind_task(
            worksheet_catalog,
            verification_key.question_id,
            request.presentation,
        )
        evaluations.append(
            PreparedEvaluation(
                evaluation_id=request.evaluation_id,
                task=task,
                request=request,
            )
        )
    return PreparedVerificationBattery(
        verification_key=verification_key,
        evaluations=tuple(evaluations),
        state=state,
    )


def evaluate_verification_transcript(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    verification_key: VerificationKey,
    worksheet_catalog: WorksheetCatalog,
    observations: tuple[WireVerificationObservation, ...],
    artifact_identity: str,
    verification_policy: BlindVerificationPolicy = DEFAULT_VERIFICATION_POLICY,
) -> VerificationStep:
    """Reconstruct expected battery, observe transcript, apply Core ``P_v`` decision.

    Protocol/invariant failures raise. ``Insufficient`` means the experiment
    completed but did not satisfy the policy.
    """
    if verification_key.artifact_identity != artifact_identity:
        msg = (
            f"verification_key.artifact_identity {verification_key.artifact_identity!r} "
            f"does not match artifact_identity {artifact_identity!r}"
        )
        raise PremiseInvariantError(msg)
    if verification_key.pv_version != verification_policy.pv_version:
        msg = (
            f"verification_key.pv_version {verification_key.pv_version!r} does not match "
            f"verification_policy.pv_version {verification_policy.pv_version!r}"
        )
        raise PremiseInvariantError(msg)

    assertion = _live_assertion_for_key(admitted, verification_key)
    prepared = prepare_verification_battery(
        verification_key=verification_key,
        worksheet_catalog=worksheet_catalog,
        verification_policy=verification_policy,
    )
    state = prepared.state
    by_id = {req.evaluation_id: req for req in state.schedule}

    if len(observations) != len(state.schedule):
        msg = (
            f"incomplete verification transcript: got {len(observations)} observations, "
            f"expected {len(state.schedule)}"
        )
        raise PremiseInvariantError(msg)

    seen_ids: set[EvaluationId] = set()
    for wire in observations:
        if wire.evaluation_id not in by_id:
            msg = f"unscheduled evaluation_id {wire.evaluation_id!r}"
            raise PremiseInvariantError(msg)
        if wire.evaluation_id in seen_ids:
            msg = f"duplicate observation for evaluation_id {wire.evaluation_id!r}"
            raise PremiseInvariantError(msg)
        seen_ids.add(wire.evaluation_id)
        expected = by_id[wire.evaluation_id]
        if wire.presentation is not None and wire.presentation != expected.presentation:
            msg = (
                f"presentation mismatch for {wire.evaluation_id!r}: "
                f"got {wire.presentation!r}, expected {expected.presentation!r}"
            )
            raise PremiseInvariantError(msg)
        observation = VerificationObservation(
            evaluation_id=wire.evaluation_id,
            question_id=wire.question_id,
            selected_option=wire.selected_option,
            provenance_id=wire.provenance_id,
            presentation=expected.presentation,
        )
        state = verification_policy.observe(state, observation)

    decision = verification_policy.decision(state)
    if decision is None:
        raise PremiseInvariantError("verification schedule exhausted without decision")
    if not isinstance(decision, (Retain, Insufficient)):
        msg = f"unexpected verification decision type {type(decision)!r}"
        raise PremiseInvariantError(msg)

    transition = apply_verification_decision(
        ir=ir,
        admitted=admitted,
        verified=verified,
        assertion=assertion,
        artifact_identity=artifact_identity,
        pv_version=verification_policy.pv_version,
        decision=decision,
    )
    return VerificationStep(
        admitted=transition.admitted,
        verified=transition.verified,
        base_changed=transition.base_changed,
        status=transition.status,
        decision=decision,
    )


__all__ = [
    "PreparedEvaluation",
    "PreparedVerificationBattery",
    "WireVerificationObservation",
    "evaluate_verification_transcript",
    "prepare_verification_battery",
]
