"""Residual resolvability and resolving-witness search (calculus §13.9.4)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from smeme.reasoning.ir.types import IR
from smeme.reasoning.runtime.inquire.space import (
    WorkingBase,
    resolved_conclusion,
    unanswered_questions,
)
from smeme.reasoning.runtime.inquire.types import InquiryBudget


def _raise_not_bool() -> None:
    raise TypeError(
        "WitnessResult is not truthy; check .status explicitly (vacuous-entailment hardening)."
    )


@dataclass(frozen=True, slots=True)
class WitnessResult:
    status: str
    question_id: str | None = None
    operational_status: str | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool()
        return False


def _options_for(ir: IR, question_id: str) -> tuple[str, ...]:
    for node in ir.nodes:
        if node.id == question_id and node.question is not None:
            return node.question.options
    return ()


def _residual_exhausted(base: WorkingBase, budget: InquiryBudget, residual_start: int) -> bool:
    if budget.max_residual_sat_calls is None:
        return False
    return (base.sat_calls[0] - residual_start) >= budget.max_residual_sat_calls


def search_resolving_witness(base: WorkingBase, budget: InquiryBudget) -> WitnessResult:
    """First resolving witness of width ≥ 2, or proved ``¬Resolvable``, or G7 miss.

    Immediate ``¬Resolvable`` when ``U = ∅``. Exhaustion of the width-increasing
    search also proves ``¬Resolvable``. A budget/timeout in this branch is G7.
    """
    remaining = unanswered_questions(base.ir, base.admitted)
    if not remaining:
        return WitnessResult(status="not_resolvable")

    residual_start = base.sat_calls[0]
    if budget.max_residual_sat_calls == 0:
        return WitnessResult(status="budget_miss", operational_status="budget")

    for width in range(2, len(remaining) + 1):
        for d_tuple in itertools.combinations(remaining, width):
            option_lists = [_options_for(base.ir, qid) for qid in d_tuple]
            for assignment in itertools.product(*option_lists):
                if _residual_exhausted(base, budget, residual_start):
                    return WitnessResult(status="budget_miss", operational_status="budget")
                alpha = dict(zip(d_tuple, assignment, strict=True))
                hypo = base.with_admitted({**base.admitted, **alpha})
                resolved = resolved_conclusion(hypo)
                if resolved.status in ("budget", "timeout", "unknown"):
                    return WitnessResult(
                        status="budget_miss",
                        operational_status=resolved.status,
                    )
                if resolved.status == "resolved":
                    return WitnessResult(status="acquire", question_id=min(d_tuple))
    return WitnessResult(status="not_resolvable")
