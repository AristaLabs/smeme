"""Evaluate user answers against a persisted IR theory (compile_ir_to_z3 + unit facts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from z3 import BoolRef, Not, is_true, sat

from smeme.reasoning.cevi.fact_projection import apply_canonical_facts_to_solver
from smeme.reasoning.ir.types import IR, IRNodeKind
from smeme.reasoning.runtime.assumptions import (
    EMPTY_ASSUMPTIONS,
    ReasoningAssumptions,
    apply_assumptions_to_solver,
    validate_assumptions,
)
from smeme.reasoning.runtime.canonical_facts import (
    CanonicalFactRecord,
    raw_answers_to_canonical_facts,
)
from smeme.reasoning.runtime.input_validation import (
    ReasoningInputValidationError,
    validate_raw_answers_for_ir,
)
from smeme.reasoning.runtime.schemas import BlobEvidenceItem, Fact
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

OutcomeLiteral = Literal["SAT_UNIQUE", "SAT_AMBIGUOUS", "UNSAT", "UNDER_DETERMINED"]

TriggeredEdge = dict[str, str]


@dataclass
class EvaluationResult:
    status: OutcomeLiteral
    true_conclusion_id: str | None = None
    model_atoms: dict[str, bool] | None = None
    explanation: dict[str, Any] = field(default_factory=dict)
    triggered_edges: list[TriggeredEdge] = field(default_factory=list)
    minimal_repairs: list[Any] | None = None


@dataclass
class BlobAuditRecord:
    evidence_items: list[dict[str, Any]]
    conflict_report: dict[str, Any] | None
    user_resolutions: dict[str, Any] | None
    final_facts: list[dict[str, Any]]
    permissive_mode: bool


def _model_bool_assignments(
    model: Any, refs: dict[str, BoolRef], names: list[str]
) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for n in names:
        if n not in refs:
            continue
        v = model.eval(refs[n], model_completion=True)
        out[n] = bool(is_true(v))
    return out


def _triggered_edges_ir(
    ir: IR, model: Any, reach: dict[str, BoolRef], guards: dict[str, BoolRef]
) -> list[TriggeredEdge]:
    """Return fired edges with ``guard_id`` so parallel (source, target) pairs stay distinct."""
    fired: list[TriggeredEdge] = []
    for e in ir.edges:
        gr = guards.get(e.guard_id)
        if gr is None or e.source not in reach or e.target not in reach:
            continue
        rs = model.eval(reach[e.source], model_completion=True)
        rt = model.eval(reach[e.target], model_completion=True)
        rg = model.eval(gr, model_completion=True)
        if is_true(rs) and is_true(rg) and is_true(rt):
            fired.append(
                {
                    "source": e.source,
                    "target": e.target,
                    "guard_id": e.guard_id,
                }
            )
    fired.sort(key=lambda row: (row["source"], row["target"], row["guard_id"]))
    return fired


def _apply_user_facts(
    solver: Any,
    ir: IR,
    raw_answers: dict[str, str | list[str] | None],
    *,
    z3_ctx: Any,
) -> tuple[list[BlobEvidenceItem], list[Fact]]:
    """Stage A (``fact:*`` records) → Stage B (``ir_*`` unit assertions on ``solver``)."""
    canonical = raw_answers_to_canonical_facts(ir, raw_answers)
    return apply_canonical_facts_to_solver(solver, ir, canonical, z3_ctx=z3_ctx)


def evaluate_with_canonical_facts(
    ir: IR,
    canonical_facts: list[CanonicalFactRecord],
    *,
    permissive_unresolved: bool = False,
    skip_ir_validation: bool = False,
    assumptions: ReasoningAssumptions | None = None,
) -> tuple[EvaluationResult, BlobAuditRecord]:
    """
    Shared Z3 tail: compile IR, assert canonical facts, run ``check`` + model + outcome.

    Caller must supply IR already validated when ``skip_ir_validation`` is True.
    Optional ``assumptions`` assert force/forbid ``reach`` (ALGEBRA §18).

    Cause ladder on admitted E / admitted φ (not pre-admission stage codes):
    ``answers_inconsistent`` when UNSAT(T∧E); ``assumptions_inconsistent`` when
    SAT(T∧E) but UNSAT(T∧E∧φ). ``sources_conflict`` / ``conflicting_assumptions``
    are earlier pipeline stages and are not emitted here.
    """
    from smeme.reasoning.ir.validate import IRValidationError
    from smeme.reasoning.ir.validate import validate_ir as run_validate_ir
    from z3 import unknown, unsat

    phi = assumptions if assumptions is not None else EMPTY_ASSUMPTIONS
    validate_assumptions(ir, phi)

    if not skip_ir_validation:
        rep = run_validate_ir(ir)
        if not rep.valid:
            raise IRValidationError(rep)

    solver, sym = compile_ir_to_z3(ir)
    reach = sym["nodes"]
    guards_map = sym["guards"]

    items, facts = apply_canonical_facts_to_solver(solver, ir, canonical_facts, z3_ctx=solver.ctx)

    empty_audit = BlobAuditRecord(
        evidence_items=[i.model_dump(mode="json") for i in items],
        conflict_report=None,
        user_resolutions=None,
        final_facts=[f.model_dump(mode="json") for f in facts],
        permissive_mode=permissive_unresolved,
    )

    # Ladder step 2: admitted E (φ not yet applied).
    chk_e = solver.check()
    if chk_e == unknown:
        return (
            EvaluationResult(status="UNSAT", explanation={"reason": "solver_unknown"}),
            empty_audit,
        )
    if chk_e == unsat:
        return (
            EvaluationResult(status="UNSAT", explanation={"reason": "z3_unsat"}),
            empty_audit,
        )

    # Ladder step 3: admitted φ.
    if not phi.is_empty():
        apply_assumptions_to_solver(solver, reach, phi)
        chk_phi = solver.check()
        if chk_phi == unknown:
            return (
                EvaluationResult(status="UNSAT", explanation={"reason": "solver_unknown"}),
                empty_audit,
            )
        if chk_phi == unsat:
            return (
                EvaluationResult(status="UNSAT", explanation={"reason": "assumptions_unsat"}),
                empty_audit,
            )

    model = solver.model()
    triggered = _triggered_edges_ir(ir, model, reach, guards_map)

    conclusion_ids = sorted(n.id for n in ir.nodes if n.kind == IRNodeKind.CONCLUSION)
    c_true: list[str] = []
    for cid in conclusion_ids:
        if cid in reach and is_true(model.eval(reach[cid], model_completion=True)):
            c_true.append(cid)

    pub_names = sorted(set(reach.keys()) | set(guards_map.keys()))
    assignments = _model_bool_assignments(model, {**reach, **guards_map}, pub_names)

    if not c_true:
        return (
            EvaluationResult(
                status="UNDER_DETERMINED",
                model_atoms=assignments,
                explanation={"true_conclusions": [], "triggered_edges": triggered},
                triggered_edges=triggered,
            ),
            empty_audit,
        )

    if len(c_true) > 1:
        return (
            EvaluationResult(
                status="SAT_AMBIGUOUS",
                model_atoms=assignments,
                explanation={"true_conclusions": c_true, "triggered_edges": triggered},
                triggered_edges=triggered,
            ),
            empty_audit,
        )

    only = c_true[0]
    solver.push()
    solver.add(Not(reach[only]))
    alt = solver.check()
    solver.pop()

    if alt == sat:
        return (
            EvaluationResult(
                status="SAT_AMBIGUOUS",
                true_conclusion_id=only,
                model_atoms=assignments,
                explanation={
                    "true_conclusions": c_true,
                    "alternate_model_exists": True,
                    "triggered_edges": triggered,
                },
                triggered_edges=triggered,
            ),
            empty_audit,
        )

    return (
        EvaluationResult(
            status="SAT_UNIQUE",
            true_conclusion_id=only,
            model_atoms=assignments,
            explanation={"true_conclusions": c_true, "triggered_edges": triggered},
            triggered_edges=triggered,
        ),
        empty_audit,
    )


def evaluate_reasoning(
    ir: IR,
    *,
    raw_answers: dict[str, str | list[str] | None],
    permissive_unresolved: bool = False,
    skip_ir_validation: bool = False,
    assumptions: ReasoningAssumptions | None = None,
) -> tuple[EvaluationResult, BlobAuditRecord]:
    """
    Run IR theory + user facts; return outcome + audit record.

    When ``skip_ir_validation`` is False (default), runs :func:`~smeme.reasoning.ir.validate.validate_ir`
    and raises :class:`~smeme.reasoning.ir.validate.IRValidationError` if invalid.
    """
    from smeme.reasoning.ir.validate import IRValidationError
    from smeme.reasoning.ir.validate import validate_ir as run_validate_ir

    if not skip_ir_validation:
        rep = run_validate_ir(ir)
        if not rep.valid:
            raise IRValidationError(rep)

    validate_raw_answers_for_ir(ir, raw_answers)
    # Stage A raises ReasoningInputValidationError with question/field/constraint —
    # MCP maps that to invalid_answers (never internal_error).
    canonical = raw_answers_to_canonical_facts(ir, raw_answers)
    return evaluate_with_canonical_facts(
        ir,
        canonical,
        permissive_unresolved=permissive_unresolved,
        skip_ir_validation=True,
        assumptions=assumptions,
    )


__all__ = [
    "BlobAuditRecord",
    "EvaluationResult",
    "OutcomeLiteral",
    "ReasoningAssumptions",
    "ReasoningInputValidationError",
    "TriggeredEdge",
    "evaluate_reasoning",
    "evaluate_with_canonical_facts",
]
