"""Atomic P_v transitions over live admitted assertions. Not session state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from smeme.reasoning.ir.types import IR
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.input_validation import (
    ReasoningInputValidationError,
    validate_raw_answers_for_ir,
)
from smeme.reasoning.runtime.inquire.types import (
    AdmittedAssertion,
    CanonicalProvenanceId,
    VerificationKey,
    logical_evidence,
    verification_key_for,
)

TransitionStatus = Literal["applied", "admission_rejected", "assertion_mismatch"]


@dataclass(frozen=True, slots=True)
class Retain:
    """Keep ``e`` in ``E``; bind verification to the live assertion."""


@dataclass(frozen=True, slots=True)
class Retract:
    """REBASE: drop the live assertion from ``E``."""


@dataclass(frozen=True, slots=True)
class Replace:
    """REBASE: same ``q``, new option and caller-supplied provenance. Unverified."""

    option: str
    provenance_id: CanonicalProvenanceId

    def __post_init__(self) -> None:
        if not str(self.provenance_id).strip():
            raise PremiseInvariantError("empty provenance_id")


@dataclass(frozen=True, slots=True)
class Insufficient:
    """Do not modify ``E`` or verification state."""


VerificationDecision = Retain | Retract | Replace | Insufficient


@dataclass(frozen=True, slots=True)
class VerificationTransition:
    admitted: tuple[AdmittedAssertion, ...]
    verified: frozenset[VerificationKey]
    base_changed: bool
    status: TransitionStatus


def _unchanged(
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    status: TransitionStatus,
) -> VerificationTransition:
    return VerificationTransition(
        admitted=admitted,
        verified=verified,
        base_changed=False,
        status=status,
    )


def _live_assertion(
    admitted: tuple[AdmittedAssertion, ...], question_id: str
) -> AdmittedAssertion | None:
    matches = [item for item in admitted if item.question_id == question_id]
    if len(matches) != 1:
        return None
    return matches[0]


def _drop_keys_for_assertion(
    verified: frozenset[VerificationKey],
    assertion: AdmittedAssertion,
    *,
    artifact_identity: str,
) -> frozenset[VerificationKey]:
    provenance = str(assertion.provenance_id)
    return frozenset(
        key
        for key in verified
        if not (
            key.artifact_identity == artifact_identity
            and key.question_id == assertion.question_id
            and key.option == assertion.option
            and key.provenance_identity == provenance
        )
    )


def admit_assertion(
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    *,
    question_id: str,
    option: str,
    provenance_id: CanonicalProvenanceId,
) -> tuple[AdmittedAssertion, ...]:
    """ACQUIRE admission: unanswered ``q`` only. Not a public Inquire export."""
    evidence = logical_evidence(admitted)
    if question_id in evidence:
        msg = f"question {question_id!r} is already admitted; use REPLACE"
        raise PremiseInvariantError(msg)
    proposed = dict(evidence)
    proposed[question_id] = option
    validate_raw_answers_for_ir(ir, proposed)
    assertion = AdmittedAssertion(
        question_id=question_id,
        option=option,
        provenance_id=provenance_id,
    )
    return (*admitted, assertion)


def apply_verification_decision(
    *,
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    verified: frozenset[VerificationKey],
    assertion: AdmittedAssertion,
    artifact_identity: str,
    pv_version: str,
    decision: VerificationDecision,
) -> VerificationTransition:
    """Pure state transition. Does not call ``analyze_inquiry``."""
    live = _live_assertion(admitted, assertion.question_id)
    if live is None or live != assertion:
        return _unchanged(admitted, verified, "assertion_mismatch")

    if isinstance(decision, Insufficient):
        return _unchanged(admitted, verified, "applied")

    if isinstance(decision, Retain):
        key = verification_key_for(live, artifact_identity=artifact_identity, pv_version=pv_version)
        return VerificationTransition(
            admitted=admitted,
            verified=verified | {key},
            base_changed=False,
            status="applied",
        )

    if isinstance(decision, Retract):
        remaining = tuple(item for item in admitted if item.question_id != live.question_id)
        return VerificationTransition(
            admitted=remaining,
            verified=_drop_keys_for_assertion(verified, live, artifact_identity=artifact_identity),
            base_changed=True,
            status="applied",
        )

    if isinstance(decision, Replace):
        evidence = logical_evidence(admitted)
        proposed = dict(evidence)
        proposed[live.question_id] = decision.option
        try:
            validate_raw_answers_for_ir(ir, proposed)
        except ReasoningInputValidationError:
            return _unchanged(admitted, verified, "admission_rejected")
        replacement = AdmittedAssertion(
            question_id=live.question_id,
            option=decision.option,
            provenance_id=decision.provenance_id,
        )
        remaining = tuple(item for item in admitted if item.question_id != live.question_id)
        return VerificationTransition(
            admitted=(*remaining, replacement),
            verified=_drop_keys_for_assertion(verified, live, artifact_identity=artifact_identity),
            base_changed=True,
            status="applied",
        )

    msg = f"unknown verification decision {type(decision)!r}"
    raise PremiseInvariantError(msg)
