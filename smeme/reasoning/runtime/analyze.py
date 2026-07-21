"""Internal Phase 1 SAT queries over conclusions (not re-exported from ``smeme.reasoning``)."""

from __future__ import annotations

from dataclasses import dataclass

from z3 import And, sat, unknown, unsat

from smeme.reasoning.ir.types import IR, IRNodeKind, ValidationReport
from smeme.reasoning.ir.validate import IRValidationError, validate_ir
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3


@dataclass(frozen=True, slots=True)
class ConclusionSatQueryEnumeration:
    """Result of :func:`enumerate_conclusion_sat_queries` (existential SAT over ``T(IR)``; not user evaluation)."""

    is_theory_satisfiable: bool
    """``True`` iff base check ``SAT(T(IR))`` is ``sat`` (``False`` for ``unsat`` or ``unknown``)."""

    conclusion_reachable: dict[str, bool]
    """Per conclusion ``C``: ``SAT(T(IR) ∧ reach(C))`` when the base theory is satisfiable."""

    conclusion_pairs_co_reachable: dict[tuple[str, str], bool]
    """Undirected conclusion pairs ``(min, max)``: ``SAT(T(IR) ∧ reach(Ci) ∧ reach(Cj))``."""

    validation_report: ValidationReport | None
    """Populated when ``validate=True``; ``None`` when validation was skipped."""


def enumerate_conclusion_sat_queries(
    ir: IR, *, validate: bool = True
) -> ConclusionSatQueryEnumeration:
    """
    Enumerate SAT outcomes for the base theory, each conclusion’s reach predicate, and each
    unordered conclusion pair.

    Compiles once, then uses ``solver.push()`` / ``pop()`` so queries do not leak constraints
    between checks. Answers **existential** structural feasibility: “is there *some* assignment of
    free guard atoms under which … holds?” — not Phase 2 CEVI-grounded “what a real user sees.”

    Pairwise checks are **conclusion nodes only**, use sorted ``(Ci, Cj)`` keys (``i < j``), and cost
    **O(|C|²)** SAT calls in the number of conclusions ``|C|``.

    **Default (``validate=True``):** same validation contract as :func:`~smeme.reasoning.runtime.run.solve_reachability_witness`;
    invalid IR raises :exc:`~smeme.reasoning.ir.validate.IRValidationError`.

    Satisfiability outcomes (``sat`` / ``unsat`` / ``unknown``) for each query should be stable
    across runs; witness **models** are not required to be identical (Z3 may vary details).
    """
    report: ValidationReport | None = None
    if validate:
        report = validate_ir(ir)
        if not report.valid:
            raise IRValidationError(report)

    solver, sym = compile_ir_to_z3(ir)
    node_sym = sym["nodes"]
    conclusion_ids = sorted(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)

    chk0 = solver.check()
    if chk0 in (unsat, unknown):
        return ConclusionSatQueryEnumeration(
            is_theory_satisfiable=False,
            conclusion_reachable=dict.fromkeys(conclusion_ids, False),
            conclusion_pairs_co_reachable={},
            validation_report=report,
        )

    conc: dict[str, bool] = {}
    for cid in conclusion_ids:
        solver.push()
        solver.add(node_sym[cid])
        chk = solver.check()
        conc[cid] = chk == sat
        solver.pop()

    pairs: dict[tuple[str, str], bool] = {}
    n_c = len(conclusion_ids)
    for i in range(n_c):
        for j in range(i + 1, n_c):
            a, b = conclusion_ids[i], conclusion_ids[j]
            solver.push()
            solver.add(And(node_sym[a], node_sym[b]))
            chk = solver.check()
            pairs[(a, b)] = chk == sat
            solver.pop()

    return ConclusionSatQueryEnumeration(
        is_theory_satisfiable=True,
        conclusion_reachable=conc,
        conclusion_pairs_co_reachable=pairs,
        validation_report=report,
    )
