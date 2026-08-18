"""Provenance-bearing ACQUIRE admission over a blind extraction result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from smeme.reasoning.ir.types import IR
from smeme.reasoning.orchestration.inquire.types import AnsweredExtraction
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire.transition import admit_assertion
from smeme.reasoning.runtime.inquire.types import AdmittedAssertion, ExtractionTask

AdmissionStatus = Literal["applied"]


@dataclass(frozen=True, slots=True)
class AdmissionStep:
    admitted: tuple[AdmittedAssertion, ...]
    status: AdmissionStatus


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


def admit_extraction(
    ir: IR,
    admitted: tuple[AdmittedAssertion, ...],
    *,
    task: ExtractionTask,
    result: AnsweredExtraction,
) -> AdmissionStep:
    """Admit ``(q, a, p)`` through the kernel. Cannot admit an abstention."""
    _require_result_matches_task(task, question_id=result.question_id)
    if result.selected_option not in task.question.options:
        msg = (
            f"selected_option {result.selected_option!r} is not among "
            f"task options {task.question.options!r}"
        )
        raise PremiseInvariantError(msg)
    next_admitted = admit_assertion(
        ir,
        admitted,
        question_id=result.question_id,
        option=result.selected_option,
        provenance_id=result.provenance_id,
    )
    return AdmissionStep(admitted=next_admitted, status="applied")
