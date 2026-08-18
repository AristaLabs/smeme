"""Blind verification policy battery (Phase 4). Not a shipped public surface."""

from smeme.reasoning.orchestration.inquire.verification.policy import (
    DEFAULT_PV_VERSION,
    DEFAULT_VERIFICATION_POLICY,
    BlindVerificationPolicy,
    DefaultVerificationPolicy,
)
from smeme.reasoning.orchestration.inquire.verification.present import (
    build_option_order_schedule,
    observation_from_result,
    render_blind_task,
    schedule_size,
)
from smeme.reasoning.orchestration.inquire.verification.runner import (
    VerificationBatteryOutcome,
    run_verification,
)
from smeme.reasoning.orchestration.inquire.verification.types import (
    EvaluationId,
    EvaluationRequest,
    EvaluatorSlot,
    PresentationVariant,
    VerificationObservation,
    VerificationState,
)

__all__ = [
    "DEFAULT_PV_VERSION",
    "DEFAULT_VERIFICATION_POLICY",
    "BlindVerificationPolicy",
    "DefaultVerificationPolicy",
    "EvaluationId",
    "EvaluationRequest",
    "EvaluatorSlot",
    "PresentationVariant",
    "VerificationBatteryOutcome",
    "VerificationObservation",
    "VerificationState",
    "build_option_order_schedule",
    "observation_from_result",
    "render_blind_task",
    "run_verification",
    "schedule_size",
]
