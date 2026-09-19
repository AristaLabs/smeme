"""Minimum-cardinality resolving worksheet support ``S_R`` (calculus §13.9.2).

Greedy Resolved-deletion is an upper bound only. Enumeration starts at cardinality 0.
Never treat ``decisive_support`` as ``S_R``. Budget miss is operational (not G7).

When exact enumeration hits its dedicated SAT budget after ``Resolved(B)``,
``analyze_inquiry`` STOPs with ``resolving_support_incomplete`` (not generic
``operational_budget``). Chat may still Apply admitted answers into a concluded report.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from time import perf_counter

from z3 import Not, Or, sat, unknown  # type: ignore[import-untyped]

from smeme.reasoning.cevi.fact_projection import apply_canonical_facts_to_solver
from smeme.reasoning.ir.types import IRNodeKind
from smeme.reasoning.runtime.assumptions import apply_assumptions_to_solver
from smeme.reasoning.runtime.consistency_gate import (
    InconsistencyCause,
    assert_literal_subconjunction,
    resolve_facts,
)
from smeme.reasoning.runtime.inquire.space import WorkingBase
from smeme.reasoning.runtime.inquire.types import (
    DEFAULT_RESOLVING_SUPPORT_MAX_SAT_CALLS,
    DEFAULT_RESOLVING_SUPPORT_TIMEOUT_MS,
    HARD_MAX_INQUIRE_TIMEOUT_MS,
    HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS,
    WorksheetPair,
)


def _raise_not_bool() -> None:
    raise TypeError(
        "SupportResult is not truthy; check .status explicitly (vacuous-entailment hardening)."
    )


@dataclass(frozen=True, slots=True)
class SupportResult:
    status: str
    pairs: tuple[WorksheetPair, ...] = ()
    cause: InconsistencyCause | None = None
    sat_calls: int = 0
    elapsed_ms: float = 0.0

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
    """One-call test for ``Resolved(candidate)`` with the same conclusion.

    ``candidate`` is a literal subconjunction of the already-consistent resolved
    base. Removing admitted literals preserves consistency. Therefore one UNSAT
    query over ``¬target ∨ any_other_conclusion`` proves both target entailment
    and exclusion of every other conclusion without repeating generic
    consistency/possibility checks.
    """
    assert_literal_subconjunction(admitted, base.admitted)
    if base.sat_calls[0] >= base.max_sat_calls:
        return SupportResult(status="budget")
    facts = resolve_facts(base.ir, answers=admitted)
    alternatives = [
        base.reach[node.id]
        for node in base.ir.nodes
        if node.kind == IRNodeKind.CONCLUSION and node.id != target_c
    ]
    base.solver.set(timeout=base.timeout_ms)
    base.solver.push()
    try:
        apply_canonical_facts_to_solver(base.solver, base.ir, facts, z3_ctx=base.solver.ctx)
        if not base.assumptions.is_empty():
            apply_assumptions_to_solver(base.solver, base.reach, base.assumptions)
        base.solver.add(Or(Not(base.reach[target_c]), *alternatives))
        check = base.solver.check()
        base.sat_calls[0] += 1
    finally:
        base.solver.pop()
    if check == unknown:
        return SupportResult(status="timeout")
    if check != sat:
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


def resolving_support(
    base: WorkingBase,
    target_c: str,
    *,
    max_sat_calls: int = DEFAULT_RESOLVING_SUPPORT_MAX_SAT_CALLS,
    timeout_ms: int = DEFAULT_RESOLVING_SUPPORT_TIMEOUT_MS,
) -> SupportResult:
    """Exact min-cardinality ``S_R`` for already-``Resolved`` ``B`` with unique ``c``."""
    if not 1 <= max_sat_calls <= HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS:
        message = f"max_sat_calls must be between 1 and {HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS}"
        raise ValueError(message)
    if not 1 <= timeout_ms <= HARD_MAX_INQUIRE_TIMEOUT_MS:
        message = f"timeout_ms must be between 1 and {HARD_MAX_INQUIRE_TIMEOUT_MS}"
        raise ValueError(message)
    started = perf_counter()
    support_base = dataclass_replace(
        base,
        sat_calls=[0],
        max_sat_calls=max_sat_calls,
        timeout_ms=timeout_ms,
    )

    def finish(result: SupportResult) -> SupportResult:
        return dataclass_replace(
            result,
            sat_calls=support_base.sat_calls[0],
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )

    greedy = _greedy_upper_bound(support_base, target_c)
    if greedy.status != "ok":
        return finish(greedy)
    upper = len(greedy.pairs)
    items = tuple((qid, support_base.admitted[qid]) for qid in sorted(support_base.admitted))
    for k in range(upper + 1):
        for combo in itertools.combinations(items, k):
            candidate = _as_dict(combo)
            hit = _resolved_same_c(support_base, candidate, target_c)
            if hit is not None:
                return finish(hit)
    return finish(SupportResult(status="unknown"))
