"""Option-order presentation: schedule, render, normalize."""

from __future__ import annotations

import itertools
import math

from smeme.reasoning.orchestration.inquire.types import (
    AbstainedExtraction,
    AnsweredExtraction,
    ExtractionResult,
)
from smeme.reasoning.orchestration.inquire.verification.types import (
    EvaluationId,
    EvaluationRequest,
    PresentationVariant,
    VerificationObservation,
)
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire import build_extractor_issue
from smeme.reasoning.runtime.inquire.types import (
    EvidenceQuestion,
    ExtractionTask,
    WorksheetCatalog,
)

_MAX_SCHEDULE = 3


def schedule_size(canonical_options: tuple[str, ...]) -> int:
    """``N_q = min(3, |A_q|!)``."""
    n = len(canonical_options)
    if n < 1:
        msg = "canonical_options must be non-empty"
        raise PremiseInvariantError(msg)
    return min(_MAX_SCHEDULE, math.factorial(n))


def build_option_order_schedule(
    canonical_options: tuple[str, ...],
) -> tuple[EvaluationRequest, ...]:
    """Deterministic lexicographic permutations; first ``N_q``; ids ``eval-i``."""
    n = schedule_size(canonical_options)
    perms = itertools.permutations(canonical_options)
    requests: list[EvaluationRequest] = []
    for index, order in zip(range(n), perms, strict=False):
        requests.append(
            EvaluationRequest(
                evaluation_id=EvaluationId(f"eval-{index}"),
                presentation=PresentationVariant(option_order=order),
                evaluator_slot="ISOLATED",
            )
        )
    return tuple(requests)


def render_blind_task(
    worksheet_catalog: WorksheetCatalog,
    question_id: str,
    presentation: PresentationVariant,
) -> ExtractionTask:
    """Canonical stem; options permuted for display only."""
    base = build_extractor_issue(worksheet_catalog, question_id)
    canonical = base.question.options
    order = presentation.option_order
    if sorted(order) != sorted(canonical) or len(order) != len(canonical):
        msg = (
            f"presentation option_order {order!r} is not a permutation of "
            f"canonical options {canonical!r}"
        )
        raise PremiseInvariantError(msg)
    return ExtractionTask(
        question=EvidenceQuestion(
            question_id=base.question.question_id,
            stem=base.question.stem,
            options=order,
        )
    )


def observation_from_result(
    *,
    result: ExtractionResult,
    request: EvaluationRequest,
) -> VerificationObservation:
    """Map extractor output to a normalized observation for the scheduled trial."""
    if isinstance(result, AbstainedExtraction):
        return VerificationObservation(
            evaluation_id=request.evaluation_id,
            question_id=result.question_id,
            selected_option=None,
            provenance_id=None,
            presentation=request.presentation,
        )
    if isinstance(result, AnsweredExtraction):
        return VerificationObservation(
            evaluation_id=request.evaluation_id,
            question_id=result.question_id,
            selected_option=result.selected_option,
            provenance_id=result.provenance_id,
            presentation=request.presentation,
        )
    msg = f"unexpected extraction result type {type(result)!r}"
    raise PremiseInvariantError(msg)
