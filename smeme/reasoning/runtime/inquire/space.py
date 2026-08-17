"""Cons, C_poss, C_ent, Resolved over a fully composed Inquire base.

Does not call ``evaluate_reasoning``. Operational aborts are generic (not G7).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from z3 import BoolRef

from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS, ReasoningAssumptions
from smeme.reasoning.runtime.consistency_gate import (
    InconsistencyCause,
    check_premise_consistency,
)
from smeme.reasoning.runtime.counterfactual import entails_target, possible_target
from smeme.reasoning.runtime.inquire.types import InquiryBudget
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

ConsStatus = Literal["consistent", "inconsistent", "budget", "timeout", "unknown"]
SpaceQueryStatus = Literal["ok", "inconsistent", "budget", "timeout", "unknown"]
ResolvedStatus = Literal[
    "resolved",
    "unresolved",
    "inconsistent",
    "budget",
    "timeout",
    "unknown",
]


def _raise_not_bool(name: str) -> None:
    msg = f"{name} is not truthy; check .status explicitly (vacuous-entailment hardening)."
    raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ConsResult:
    status: ConsStatus
    cause: InconsistencyCause | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool("ConsResult")
        return False


@dataclass(frozen=True, slots=True)
class ConclusionSetResult:
    status: SpaceQueryStatus
    conclusions: frozenset[str] = frozenset()
    cause: InconsistencyCause | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool("ConclusionSetResult")
        return False


@dataclass(frozen=True, slots=True)
class ResolvedResult:
    status: ResolvedStatus
    conclusion_id: str | None = None
    cause: InconsistencyCause | None = None

    def __bool__(self) -> bool:  # noqa: D105
        _raise_not_bool("ResolvedResult")
        return False


@dataclass
class WorkingBase:
    """Compiled ``T`` plus current ``E`` / ``φ`` / SAT accounting. Not session state."""

    ir: IR
    solver: Any
    reach: dict[str, BoolRef]
    admitted: dict[str, str]
    assumptions: ReasoningAssumptions
    sat_calls: list[int]
    max_sat_calls: int
    timeout_ms: int
    sat_t_established: bool = True

    def with_admitted(self, admitted: dict[str, str]) -> WorkingBase:
        return replace(self, admitted=dict(admitted))


def compile_working_base(
    ir: IR,
    admitted: dict[str, str],
    assumptions: ReasoningAssumptions | None,
    budget: InquiryBudget,
    *,
    sat_calls: list[int] | None = None,
) -> WorkingBase:
    """Compile ``T`` once. Callers reuse the solver via ``possible_target`` push/pop."""
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    solver, sym = compile_ir_to_z3(ir)
    return WorkingBase(
        ir=ir,
        solver=solver,
        reach=sym["nodes"],
        admitted=dict(admitted),
        assumptions=phi,
        sat_calls=sat_calls if sat_calls is not None else [0],
        max_sat_calls=budget.max_sat_calls,
        timeout_ms=budget.timeout_ms,
        sat_t_established=True,
    )


def conclusion_ids(ir: IR) -> list[str]:
    return sorted(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)


def question_ids(ir: IR) -> list[str]:
    return sorted(n.id for n in ir.nodes if n.kind == IRNodeKind.QUESTION)


def unanswered_questions(ir: IR, admitted: dict[str, str]) -> list[str]:
    """``U``: worksheet questions of the loaded artifact with no admitted pair."""
    return [qid for qid in question_ids(ir) if qid not in admitted]


def check_cons(base: WorkingBase) -> ConsResult:
    gate = check_premise_consistency(
        base.solver,
        base.reach,
        base.ir,
        answers=base.admitted,
        assumptions=base.assumptions,
        sat_calls=base.sat_calls,
        max_sat_calls=base.max_sat_calls,
        timeout_ms=base.timeout_ms,
        sat_t_established=base.sat_t_established,
    )
    if gate.status == "consistent":
        return ConsResult(status="consistent")
    if gate.status == "inconsistent":
        return ConsResult(status="inconsistent", cause=gate.require_cause())
    return ConsResult(status=gate.status)


def _abort_set(status: str, cause: InconsistencyCause | None = None) -> ConclusionSetResult:
    if status == "inconsistent":
        return ConclusionSetResult(status="inconsistent", cause=cause)
    if status in ("budget", "timeout", "unknown"):
        return ConclusionSetResult(status=status)  # type: ignore[arg-type]
    return ConclusionSetResult(status="unknown")


def possible_conclusions(base: WorkingBase) -> ConclusionSetResult:
    """Full ``C_poss(B)``. Does not abort at the second possible conclusion."""
    cons = check_cons(base)
    if cons.status != "consistent":
        return _abort_set(cons.status, cons.cause)
    found: set[str] = set()
    for cid in conclusion_ids(base.ir):
        result = possible_target(
            base.solver,
            base.reach,
            base.ir,
            base.admitted,
            cid,
            sat_calls=base.sat_calls,
            max_sat_calls=base.max_sat_calls,
            timeout_ms=base.timeout_ms,
            assumptions=base.assumptions,
            sat_t_established=base.sat_t_established,
        )
        if result.status == "possible":
            found.add(cid)
            continue
        if result.status == "impossible":
            continue
        if result.status == "inconsistent":
            return _abort_set("inconsistent", result.require_cause())
        return _abort_set(result.status)
    return ConclusionSetResult(status="ok", conclusions=frozenset(found))


def entailed_conclusions(base: WorkingBase) -> ConclusionSetResult:
    """Full ``C_ent(B)``."""
    cons = check_cons(base)
    if cons.status != "consistent":
        return _abort_set(cons.status, cons.cause)
    found: set[str] = set()
    for cid in conclusion_ids(base.ir):
        result = entails_target(
            base.solver,
            base.reach,
            base.ir,
            base.admitted,
            cid,
            sat_calls=base.sat_calls,
            max_sat_calls=base.max_sat_calls,
            timeout_ms=base.timeout_ms,
            assumptions=base.assumptions,
            sat_t_established=base.sat_t_established,
        )
        if result.status == "entailed":
            found.add(cid)
            continue
        if result.status == "not_entailed":
            continue
        if result.status == "inconsistent":
            return _abort_set("inconsistent", result.require_cause())
        return _abort_set(result.status)
    return ConclusionSetResult(status="ok", conclusions=frozenset(found))


def resolved_conclusion(base: WorkingBase) -> ResolvedResult:
    """``Resolved(B)``: Cons, abort-at-second possible, entail only the unique remainder."""
    cons = check_cons(base)
    if cons.status == "inconsistent":
        return ResolvedResult(status="inconsistent", cause=cons.cause)
    if cons.status != "consistent":
        return ResolvedResult(status=cons.status)  # type: ignore[arg-type]

    found: list[str] = []
    for cid in conclusion_ids(base.ir):
        result = possible_target(
            base.solver,
            base.reach,
            base.ir,
            base.admitted,
            cid,
            sat_calls=base.sat_calls,
            max_sat_calls=base.max_sat_calls,
            timeout_ms=base.timeout_ms,
            assumptions=base.assumptions,
            sat_t_established=base.sat_t_established,
        )
        if result.status == "possible":
            found.append(cid)
            if len(found) >= 2:
                return ResolvedResult(status="unresolved")
            continue
        if result.status == "impossible":
            continue
        if result.status == "inconsistent":
            return ResolvedResult(status="inconsistent", cause=result.require_cause())
        return ResolvedResult(status=result.status)  # type: ignore[arg-type]

    if len(found) != 1:
        return ResolvedResult(status="unresolved")

    only = found[0]
    ent = entails_target(
        base.solver,
        base.reach,
        base.ir,
        base.admitted,
        only,
        sat_calls=base.sat_calls,
        max_sat_calls=base.max_sat_calls,
        timeout_ms=base.timeout_ms,
        assumptions=base.assumptions,
        sat_t_established=base.sat_t_established,
    )
    if ent.status == "entailed":
        return ResolvedResult(status="resolved", conclusion_id=only)
    if ent.status == "not_entailed":
        return ResolvedResult(status="unresolved")
    if ent.status == "inconsistent":
        return ResolvedResult(status="inconsistent", cause=ent.require_cause())
    return ResolvedResult(status=ent.status)  # type: ignore[arg-type]
