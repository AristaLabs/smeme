"""Minimum-cardinality resolving worksheet support ``S_R`` (calculus §13.9.2).

Greedy Resolved-deletion is an upper bound only. Enumeration starts at cardinality 0.
Never treat ``decisive_support`` as ``S_R``. Budget miss is operational (not G7).

When exact enumeration hits the shared ANALYZE SAT budget after ``Resolved(B)``,
``analyze_inquiry`` STOPs with ``resolving_support_incomplete`` (not generic
``operational_budget``). Chat may still Apply admitted answers into a concluded report.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from smeme.reasoning.runtime.consistency_gate import (
    InconsistencyCause,
    assert_literal_subconjunction,
)
from smeme.reasoning.runtime.inquire.space import WorkingBase, resolved_conclusion
from smeme.reasoning.runtime.inquire.types import WorksheetPair


def _raise_not_bool() -> None:
    raise TypeError(
        "SupportResult is not truthy; check .status explicitly (vacuous-entailment hardening)."
    )


@dataclass(frozen=True, slots=True)
class SupportResult:
    status: str
    pairs: tuple[WorksheetPair, ...] = ()
    cause: InconsistencyCause | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool()
        return False


def _pairs_tuple(admitted: dict[str, str]) -> tuple[WorksheetPair, ...]:
    return tuple(WorksheetPair(question_id=qid, option=admitted[qid]) for qid in sorted(admitted))


def _as_dict(pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(pairs)


def _resolved_same_c(
    base: WorkingBase, admitted: dict[str, str], target_c: str
) -> SupportResult | None:
    """None = still searching; SupportResult = abort."""
    assert_literal_subconjunction(admitted, base.admitted)
    result = resolved_conclusion(base.with_admitted(admitted))
    if result.status in ("budget", "timeout", "unknown"):
        return SupportResult(status=result.status)
    if result.status == "inconsistent":
        return SupportResult(status="inconsistent", cause=result.cause)
    if result.status == "resolved" and result.conclusion_id == target_c:
        return SupportResult(status="ok", pairs=_pairs_tuple(admitted))
    return None


def _greedy_upper_bound(base: WorkingBase, target_c: str) -> SupportResult:
    current = dict(base.admitted)
    progress = True
    while progress:
        progress = False
        for qid in sorted(current):
            candidate = {k: v for k, v in current.items() if k != qid}
            hit = _resolved_same_c(base, candidate, target_c)
            if hit is not None and hit.status != "ok":
                return hit
            if hit is not None and hit.status == "ok":
                current = candidate
                progress = True
                break
    return SupportResult(status="ok", pairs=_pairs_tuple(current))


def resolving_support(base: WorkingBase, target_c: str) -> SupportResult:
    """Exact min-cardinality ``S_R`` for already-``Resolved`` ``B`` with unique ``c``."""
    greedy = _greedy_upper_bound(base, target_c)
    if greedy.status != "ok":
        return greedy
    upper = len(greedy.pairs)
    items = tuple((qid, base.admitted[qid]) for qid in sorted(base.admitted))
    for k in range(upper + 1):
        for combo in itertools.combinations(items, k):
            candidate = _as_dict(combo)
            hit = _resolved_same_c(base, candidate, target_c)
            if hit is not None:
                return hit
    return SupportResult(status="unknown")
