"""Orchestration-neutral Inquire execution DTOs. Not a shipped public surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from smeme.reasoning.runtime.inquire.types import (
    CanonicalProvenanceId,
    ExtractionTask,
)


@dataclass(frozen=True, slots=True)
class AnsweredExtraction:
    """Extractor proposed a worksheet option. Provenance identity is required."""

    question_id: str
    selected_option: str
    provenance_id: CanonicalProvenanceId
    provenance_ref: object | None = None


@dataclass(frozen=True, slots=True)
class AbstainedExtraction:
    """No proposition extracted. No admitted assertion, therefore no ``p``."""

    question_id: str
    provenance_ref: object | None = None


ExtractionResult = AnsweredExtraction | AbstainedExtraction


class Extractor(Protocol):
    """Stochastic seam. Receives a blind task; never receives VERIFY/ACQUIRE mode."""

    def extract(self, task: ExtractionTask) -> ExtractionResult: ...
