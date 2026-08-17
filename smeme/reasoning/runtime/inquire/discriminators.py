"""Myopic discriminators ``D_1`` (calculus §13.9.3)."""

from __future__ import annotations

from dataclasses import dataclass

from smeme.reasoning.ir.types import IR
from smeme.reasoning.runtime.consistency_gate import InconsistencyCause
from smeme.reasoning.runtime.inquire.space import (
    WorkingBase,
    possible_conclusions,
    unanswered_questions,
)


def _raise_not_bool() -> None:
    raise TypeError(
        "DiscriminatorResult is not truthy; check .status explicitly "
        "(vacuous-entailment hardening)."
    )


@dataclass(frozen=True, slots=True)
class DiscriminatorResult:
    status: str
    question_ids: tuple[str, ...] = ()
    cause: InconsistencyCause | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool()
        return False


def _options_for(ir: IR, question_id: str) -> tuple[str, ...]:
    for node in ir.nodes:
        if node.id == question_id and node.question is not None:
            return node.question.options
    return ()


def myopic_discriminators(base: WorkingBase) -> DiscriminatorResult:
    """``D_1(B)`` in stable worksheet-id order. Hypothetical pins are not admission."""
    d1: list[str] = []
    for qid in unanswered_questions(base.ir, base.admitted):
        options = _options_for(base.ir, qid)
        if len(options) < 2:
            continue
        sets: list[frozenset[str]] = []
        for opt in options:
            hypo = base.with_admitted({**base.admitted, qid: opt})
            poss = possible_conclusions(hypo)
            if poss.status in ("budget", "timeout", "unknown"):
                return DiscriminatorResult(status=poss.status)
            if poss.status == "inconsistent":
                sets.append(frozenset())
            else:
                sets.append(poss.conclusions)
        if any(s != sets[0] for s in sets[1:]):
            d1.append(qid)
    return DiscriminatorResult(status="ok", question_ids=tuple(d1))
