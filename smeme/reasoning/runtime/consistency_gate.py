"""Premise consistency gate over B_φ = T ∧ E ∧ φ (vacuous-entailment hardening).

Operational steps on *admitted* E and *admitted* φ (locked) — used to
**disambiguate** UNSAT query results and for Deploy / inheritance checks:

1. Establish SAT(T) — Deploy identity triple, or in-process hatch for unpublished IR only.
2. If E nonempty: SAT(T ∧ E); else reuse SAT(T).  → answers_inconsistent on UNSAT
3. If φ nonempty: SAT(T ∧ E ∧ φ) (or SAT(T ∧ φ) when E empty); else reuse.  → assumptions_inconsistent

``Cons(B)`` is a *semantic* condition on reporting a consequence. Consequence
helpers use **witness-first** evaluation: run the query first; call this gate
only when the query returns UNSAT (or when establishing Deploy / inheritance).
A satisfying witness for a formula containing the exact working base also proves
SAT(B). Witnesses do not transfer across different E, φ, theory versions, repair
candidates, or assertion stacks.

Status-code staging (not ladder branches):

- ``sources_conflict`` — BEFORE admitted E (blob path; reason == \"blob_conflict\")
- ``conflicting_assumptions`` — DURING φ validation, before φ is admitted
- ``answers_inconsistent`` / ``assumptions_inconsistent`` — ladder steps 2–3 only

The gate never emits ``sources_conflict`` or ``conflicting_assumptions``.

Never use bare ``assert`` for soundness invariants (``-O`` can disable them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from z3 import BoolRef, unknown, unsat

from smeme.reasoning.cevi.fact_projection import apply_canonical_facts_to_solver
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    ReasoningAssumptions,
    apply_assumptions_to_solver,
)
from smeme.reasoning.runtime.canonical_facts import (
    CanonicalFactRecord,
    raw_answers_to_canonical_facts,
)
from smeme.reasoning.runtime.schemas import EvidenceConfidence

PremiseStatus = Literal["consistent", "inconsistent", "budget", "timeout", "unknown"]
InconsistencyCause = Literal["answers_inconsistent", "assumptions_inconsistent"]
ConsequenceStatus = Literal[
    "entailed",
    "not_entailed",
    "possible",
    "impossible",
    "inconsistent",
    "budget",
    "timeout",
    "unknown",
]


class PremiseInvariantError(RuntimeError):
    """Always-on soundness invariant failure (never a bare ``assert``)."""


class TargetDomainError(ValueError):
    """Unknown, stale, or wrong-kind target — raised before any solver call."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class SatValidationRecord:
    """Deploy-time SAT(T) validation identity (not a proof certificate)."""

    artifact_hash: str
    ir_format_version: int
    compiler_version: str


@dataclass(frozen=True)
class PremiseGateResult:
    status: PremiseStatus
    cause: InconsistencyCause | None = None
    sat_calls_delta: int = 0

    def __bool__(self) -> bool:  # noqa: D105
        raise TypeError(
            "PremiseGateResult is not truthy; check .status explicitly "
            "(vacuous-entailment hardening)."
        )

    def require_cause(self) -> InconsistencyCause:
        if self.status != "inconsistent":
            raise PremiseInvariantError(
                f"require_cause only valid for inconsistent (got {self.status!r})"
            )
        if self.cause not in ("answers_inconsistent", "assumptions_inconsistent"):
            raise PremiseInvariantError(
                f"inconsistent PremiseGateResult missing/unrecognized cause: {self.cause!r}"
            )
        return self.cause


@dataclass(frozen=True)
class ConsequenceQueryResult:
    status: ConsequenceStatus
    cause: InconsistencyCause | None = None
    sat_calls_delta: int = 0

    def __bool__(self) -> bool:  # noqa: D105
        raise TypeError(
            "ConsequenceQueryResult is not truthy; check .status explicitly "
            "(vacuous-entailment hardening)."
        )

    def require_cause(self) -> InconsistencyCause:
        if self.status != "inconsistent":
            raise PremiseInvariantError(
                f"require_cause only valid for inconsistent (got {self.status!r})"
            )
        if self.cause not in ("answers_inconsistent", "assumptions_inconsistent"):
            raise PremiseInvariantError(
                f"inconsistent ConsequenceQueryResult missing/unrecognized cause: "
                f"{self.cause!r}"
            )
        return self.cause


def validate_reach_target(ir: IR, reach: dict[str, BoolRef], target_id: str) -> None:
    """Reject unknown targets before any solver call (Test F)."""
    node_ids = {n.id for n in ir.nodes}
    if target_id not in node_ids:
        raise TargetDomainError(
            "invalid_target_id",
            f'target_id "{target_id}" is not a node on this workflow.',
            target_id=target_id,
        )
    if target_id not in reach:
        raise TargetDomainError(
            "invalid_target_id",
            f'target_id "{target_id}" has no reach atom (stale or wrong IR).',
            target_id=target_id,
        )


def validate_conclusion_target(ir: IR, reach: dict[str, BoolRef], target_id: str) -> None:
    """Reject unknown / wrong-kind conclusion targets before any solver call."""
    validate_reach_target(ir, reach, target_id)
    kinds = {n.id: n.kind for n in ir.nodes}
    if kinds[target_id] != IRNodeKind.CONCLUSION:
        raise TargetDomainError(
            "invalid_target_conclusion_id",
            f'target_id "{target_id}" is not a conclusion on this workflow.',
            target_id=target_id,
        )


def match_sat_validation_record(
    *,
    deployed: SatValidationRecord | None,
    current: SatValidationRecord | None,
) -> Literal["hit", "miss", "mismatch"]:
    """Compare Deploy identity triple. Mismatch → integrity refuse (always-on)."""
    if deployed is None or current is None:
        return "miss"
    if (
        deployed.artifact_hash != current.artifact_hash
        or deployed.ir_format_version != current.ir_format_version
        or deployed.compiler_version != current.compiler_version
    ):
        return "mismatch"
    if not deployed.artifact_hash:
        return "miss"
    return "hit"


def assert_sat_t_established(
    *,
    deployed_record: SatValidationRecord | None,
    current_identity: SatValidationRecord | None,
    in_process_unpublished: bool,
) -> Literal["use_record", "recompute"]:
    """Step 1 policy. In-process hatch is unpublished IR only; never for deployed artifacts."""
    if deployed_record is not None or current_identity is not None:
        kind = match_sat_validation_record(deployed=deployed_record, current=current_identity)
        if kind == "hit":
            return "use_record"
        if kind == "mismatch":
            raise PremiseInvariantError(
                "SAT(T) validation-record identity mismatch: refusing stale sat trust "
                f"(deployed={deployed_record!r}, current={current_identity!r})"
            )
        return "recompute"
    if in_process_unpublished:
        return "recompute"
    raise PremiseInvariantError(
        "SAT(T) not established: no Deploy validation record and not unpublished in-process IR"
    )


def resolve_facts(
    ir: IR,
    *,
    answers: dict[str, str] | None = None,
    facts: list[CanonicalFactRecord] | None = None,
) -> list[CanonicalFactRecord]:
    if facts is not None:
        return facts
    raw: dict[str, str | None] = dict(answers or {})
    return raw_answers_to_canonical_facts(ir, raw)


def evidence_nonempty(facts: list[CanonicalFactRecord], answers: dict[str, str] | None) -> bool:
    if answers is not None:
        return bool(answers)
    return any(f.confidence != EvidenceConfidence.ABSENT for f in facts)


def check_premise_consistency(
    solver: Any,
    reach: dict[str, BoolRef],
    ir: IR,
    *,
    answers: dict[str, str] | None = None,
    facts: list[CanonicalFactRecord] | None = None,
    assumptions: ReasoningAssumptions | None = None,
    sat_calls: list[int],
    max_sat_calls: int,
    timeout_ms: int,
    sat_t_established: bool = True,
) -> PremiseGateResult:
    """Run operational gate steps 1–3; leave solver stack unchanged (push/pop).

    ``sat_t_established``: True when Deploy identity hit OR this request already
    recomputed SAT(T) for unpublished IR (typical for analysis oracles that compile
    T in-process). When False, recompute SAT(T) once here.
    """
    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    resolved = resolve_facts(ir, answers=answers, facts=facts)
    e_nonempty = evidence_nonempty(resolved, answers if facts is None else None)
    phi_nonempty = not phi.is_empty()
    delta = 0

    def _budget() -> PremiseGateResult | None:
        if sat_calls[0] >= max_sat_calls:
            return PremiseGateResult(status="budget", sat_calls_delta=delta)
        return None

    early = _budget()
    if early is not None:
        return early

    solver.set(timeout=timeout_ms)

    if not sat_t_established:
        chk = solver.check()
        sat_calls[0] += 1
        delta += 1
        if chk == unknown:
            return PremiseGateResult(status="timeout", sat_calls_delta=delta)
        if chk == unsat:
            raise PremiseInvariantError("SAT(T) failed for in-process / recomputed theory")
        early = _budget()
        if early is not None:
            return PremiseGateResult(status="budget", sat_calls_delta=delta)

    e_pushed = False
    if e_nonempty:
        early = _budget()
        if early is not None:
            return early
        solver.push()
        apply_canonical_facts_to_solver(solver, ir, resolved, z3_ctx=solver.ctx)
        chk = solver.check()
        sat_calls[0] += 1
        delta += 1
        if chk == unknown:
            solver.pop()
            return PremiseGateResult(status="timeout", sat_calls_delta=delta)
        if chk == unsat:
            solver.pop()
            return PremiseGateResult(
                status="inconsistent",
                cause="answers_inconsistent",
                sat_calls_delta=delta,
            )
        e_pushed = True

    if phi_nonempty:
        early = _budget()
        if early is not None:
            if e_pushed:
                solver.pop()
            return early
        solver.push()
        apply_assumptions_to_solver(solver, reach, phi)
        chk = solver.check()
        sat_calls[0] += 1
        delta += 1
        if chk == unknown:
            solver.pop()
            if e_pushed:
                solver.pop()
            return PremiseGateResult(status="timeout", sat_calls_delta=delta)
        if chk == unsat:
            solver.pop()
            if e_pushed:
                solver.pop()
            return PremiseGateResult(
                status="inconsistent",
                cause="assumptions_inconsistent",
                sat_calls_delta=delta,
            )
        solver.pop()

    if e_pushed:
        solver.pop()

    return PremiseGateResult(status="consistent", sat_calls_delta=delta)


def assert_literal_subconjunction(
    candidate: dict[str, str],
    admitted: dict[str, str],
) -> None:
    """Always-on Lit(S) ⊆ Lit(E) for decisive-support once-gate (no bare assert)."""
    for qid, opt in candidate.items():
        if qid not in admitted:
            raise PremiseInvariantError(
                f"decisive-support shrink broke Lit(S)⊆Lit(E): question {qid!r} not in E"
            )
        if admitted[qid] != opt:
            raise PremiseInvariantError(
                f"decisive-support shrink broke Lit(S)⊆Lit(E): {qid!r} option "
                f"{opt!r} != admitted {admitted[qid]!r}"
            )


__all__ = [
    "ConsequenceQueryResult",
    "ConsequenceStatus",
    "InconsistencyCause",
    "PremiseGateResult",
    "PremiseInvariantError",
    "PremiseStatus",
    "SatValidationRecord",
    "TargetDomainError",
    "assert_literal_subconjunction",
    "assert_sat_t_established",
    "check_premise_consistency",
    "evidence_nonempty",
    "match_sat_validation_record",
    "resolve_facts",
    "validate_conclusion_target",
    "validate_reach_target",
]
