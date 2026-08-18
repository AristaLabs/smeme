"""Blind verification battery types. Outside the Inquire kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NewType

from smeme.reasoning.runtime.inquire.types import (
    CanonicalProvenanceId,
    VerificationKey,
)

EvaluationId = NewType("EvaluationId", str)

EvaluatorSlot = Literal["ISOLATED"]


@dataclass(frozen=True, slots=True)
class PresentationVariant:
    """How the question is shown. v1: option-order permutation only."""

    option_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    """One scheduled trial. ``evaluation_id`` is the experiment identity."""

    evaluation_id: EvaluationId
    presentation: PresentationVariant
    evaluator_slot: EvaluatorSlot


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """Normalized result of one scheduled trial. Canonical option labels only."""

    evaluation_id: EvaluationId
    question_id: str
    selected_option: str | None
    provenance_id: CanonicalProvenanceId | None
    presentation: PresentationVariant


@dataclass(frozen=True, slots=True)
class VerificationState:
    """Accumulated battery state. Schedule size is ``len(schedule)``."""

    verification_key: VerificationKey
    canonical_options: tuple[str, ...]
    schedule: tuple[EvaluationRequest, ...]
    observations: tuple[VerificationObservation, ...]
