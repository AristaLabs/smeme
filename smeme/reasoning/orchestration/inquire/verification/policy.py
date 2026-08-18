"""Default blind verification policy (option-order battery → Retain | Insufficient)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from smeme.reasoning.orchestration.inquire.verification.present import (
    build_option_order_schedule,
)
from smeme.reasoning.orchestration.inquire.verification.types import (
    EvaluationRequest,
    VerificationObservation,
    VerificationState,
)
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.policy import VerificationRequest
from smeme.reasoning.runtime.inquire.transition import Insufficient, Retain

# Encodes algorithm + parameters. Bump when schedule or decision rule changes.
DEFAULT_PV_VERSION = "pv-blind-option-order-v1-max3-retain-insufficient-isolated-provenance-present"


class BlindVerificationPolicy(Protocol):
    """Stateful multi-trial ``P_v``. Emits Phase-2 decisions only at completion."""

    @property
    def pv_version(self) -> str: ...

    def initial_state(
        self,
        request: VerificationRequest,
        *,
        canonical_options: tuple[str, ...],
    ) -> VerificationState: ...

    def next_evaluation(self, state: VerificationState) -> EvaluationRequest | None: ...

    def observe(
        self,
        state: VerificationState,
        observation: VerificationObservation,
    ) -> VerificationState: ...

    def decision(self, state: VerificationState) -> Retain | Insufficient | None: ...


@dataclass(frozen=True, slots=True)
class DefaultVerificationPolicy:
    """Canonical Core policy: adaptive option-order battery; Retain or Insufficient."""

    _pv_version: str = DEFAULT_PV_VERSION

    @property
    def pv_version(self) -> str:
        return self._pv_version

    def initial_state(
        self,
        request: VerificationRequest,
        *,
        canonical_options: tuple[str, ...],
    ) -> VerificationState:
        if not canonical_options:
            raise PremiseInvariantError("canonical_options must be non-empty")
        if len(set(canonical_options)) != len(canonical_options):
            msg = f"canonical_options must be unique: {canonical_options!r}"
            raise PremiseInvariantError(msg)
        schedule = build_option_order_schedule(canonical_options)
        return VerificationState(
            verification_key=request.verification_key,
            canonical_options=canonical_options,
            schedule=schedule,
            observations=(),
        )

    def next_evaluation(self, state: VerificationState) -> EvaluationRequest | None:
        done = {obs.evaluation_id for obs in state.observations}
        for req in state.schedule:
            if req.evaluation_id not in done:
                return req
        return None

    def observe(
        self,
        state: VerificationState,
        observation: VerificationObservation,
    ) -> VerificationState:
        scheduled = {req.evaluation_id: req for req in state.schedule}
        if observation.evaluation_id not in scheduled:
            msg = f"unscheduled evaluation_id {observation.evaluation_id!r}"
            raise PremiseInvariantError(msg)
        if any(obs.evaluation_id == observation.evaluation_id for obs in state.observations):
            msg = f"duplicate observation for evaluation_id {observation.evaluation_id!r}"
            raise PremiseInvariantError(msg)
        expected = scheduled[observation.evaluation_id]
        if observation.presentation != expected.presentation:
            msg = (
                f"presentation mismatch for {observation.evaluation_id!r}: "
                f"got {observation.presentation!r}, expected {expected.presentation!r}"
            )
            raise PremiseInvariantError(msg)
        live_q = state.verification_key.question_id
        if observation.question_id != live_q:
            msg = (
                f"observation question_id {observation.question_id!r} does not match "
                f"live verification question {live_q!r}"
            )
            raise PremiseInvariantError(msg)
        if observation.selected_option is not None:
            if observation.selected_option not in state.canonical_options:
                msg = (
                    f"selected_option {observation.selected_option!r} is not in "
                    f"canonical options {state.canonical_options!r}"
                )
                raise PremiseInvariantError(msg)
        return VerificationState(
            verification_key=state.verification_key,
            canonical_options=state.canonical_options,
            schedule=state.schedule,
            observations=(*state.observations, observation),
        )

    def decision(self, state: VerificationState) -> Retain | Insufficient | None:
        if len(state.observations) < len(state.schedule):
            return None
        live = state.verification_key.option
        for obs in state.observations:
            if obs.selected_option is None:
                return Insufficient()
            if obs.selected_option != live:
                return Insufficient()
            if obs.provenance_id is None or not str(obs.provenance_id).strip():
                return Insufficient()
        return Retain()


DEFAULT_VERIFICATION_POLICY = DefaultVerificationPolicy()
