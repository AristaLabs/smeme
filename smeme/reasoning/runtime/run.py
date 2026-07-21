"""Solve guarded reachability theory on IR and summarize one witness model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from z3 import is_true, sat, unsat

from smeme.reasoning.ir.types import IR, IRNodeKind, ValidationReport
from smeme.reasoning.ir.validate import IRValidationError, validate_ir
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

Z3CheckStatus = Literal["sat", "unsat", "unknown"]


@dataclass(frozen=True, slots=True)
class ReachabilityWitness:
    """Outcome of :func:`solve_reachability_witness` — **Phase 1 structural** SAT over validated IR."""

    z3_status: Z3CheckStatus
    """``sat`` / ``unsat`` / ``unknown`` from Z3. Invalid IR raises :exc:`~smeme.reasoning.ir.validate.IRValidationError` before a result is built (default ``validate=True``)."""

    reachable_conclusion_ids: tuple[str, ...]
    """When ``z3_status == \"sat\"``: conclusions whose ``reach`` is true in **one** satisfying model (witness for debugging / sanity checks)."""

    node_reachable: dict[str, bool] | None
    """Per-node ``reach`` values from that model when ``z3_status == \"sat\"``; else ``None``. Not Phase 2 user-facing evaluation."""

    validation_report: ValidationReport | None
    """Populated when ``validate=True``; ``None`` when validation was skipped."""

    def to_dict(self) -> dict[str, object]:
        """Stable JSON-friendly summary for logging, MCP, and audit trails."""
        reachable_nodes: list[str] | None = None
        if self.node_reachable is not None:
            reachable_nodes = sorted(n for n, v in self.node_reachable.items() if v)
        out: dict[str, object] = {
            "sat": self.z3_status == "sat",
            "z3_status": self.z3_status,
            "reachable_nodes": reachable_nodes,
            "reachable_conclusions": list(self.reachable_conclusion_ids),
        }
        if self.node_reachable is not None:
            out["node_reachable"] = dict(self.node_reachable)
        if self.validation_report is not None:
            out["validation_valid"] = self.validation_report.valid
            out["validation_errors"] = list(self.validation_report.errors)
        return out


# -----------------------------------------------------------------------------
# FUTURE HARDER BOUNDARY (when MCP / REST wire this pipeline)
#
# validate=True (default) is the safe path: invalid IR raises IRValidationError before Z3.
# validate=False skips validation and is only for tests or callers who already proved validity;
# combined with compile_ir_to_z3 that is a footgun the type system does not rule out. When exposing
# this stack over MCP or REST, consider a ValidIR type (or similar) so the compiler cannot be
# invoked on raw IR by accident. See theory/compile_to_z3.py for the paired banner + Sphinx note.
# -----------------------------------------------------------------------------


def solve_reachability_witness(ir: IR, *, validate: bool = True) -> ReachabilityWitness:
    """
    Compile IR to guarded reachability theory ``T(IR)``, run ``solver.check()``, and read **one**
    witness model when ``sat``.

    **Phase 1 semantics:** existential structural analysis — “is ``T(IR)`` satisfiable, and in **some**
    model which conclusions have ``reach`` true?” — **not** “what happens for real user inputs /
    grounded evidence” (Phase 2 CEVI + ``T(IR) ∧ E``).

    **Default (``validate=True``):** runs :func:`~smeme.reasoning.ir.validate.validate_ir` and
    raises :exc:`~smeme.reasoning.ir.validate.IRValidationError` if it fails—production paths
    (REST, MCP, jobs) must not skip this or call :func:`~smeme.reasoning.theory.compile_to_z3.compile_ir_to_z3`
    on unvalidated IR.

    ``validate=False`` is for tests or callers who already proved ``validate_ir(ir).valid``; invalid
    IR may then raise :exc:`KeyError` during compilation.

    Default-edge guards are asserted TRUE in compilation; other guards are set by typed semantics
    for radio options or remain abstract propositions where applicable.
    """
    report: ValidationReport | None = None
    if validate:
        report = validate_ir(ir)
        if not report.valid:
            raise IRValidationError(report)

    solver, sym = compile_ir_to_z3(ir)
    chk = solver.check()
    if chk == sat:
        status: Z3CheckStatus = "sat"
        m = solver.model()
        node_reachable: dict[str, bool] = {}
        for nid, ref in sym["nodes"].items():
            v = m.eval(ref, model_completion=True)
            node_reachable[nid] = bool(is_true(v))
        conclusion_ids = [
            n.id
            for n in ir.nodes
            if n.kind == IRNodeKind.CONCLUSION and node_reachable.get(n.id, False)
        ]
        conclusion_ids.sort()
        return ReachabilityWitness(
            z3_status=status,
            reachable_conclusion_ids=tuple(conclusion_ids),
            node_reachable=node_reachable,
            validation_report=report,
        )
    if chk == unsat:
        return ReachabilityWitness(
            z3_status="unsat",
            reachable_conclusion_ids=(),
            node_reachable=None,
            validation_report=report,
        )
    return ReachabilityWitness(
        z3_status="unknown",
        reachable_conclusion_ids=(),
        node_reachable=None,
        validation_report=report,
    )
