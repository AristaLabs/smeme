"""IR → Z3: sound reachability recurrence, structure-first.

.. important::

    **Validated IR contract.** :func:`compile_ir_to_z3` **requires**
    ``validate_ir(ir).valid is True``. It does not call :func:`~smeme.reasoning.ir.validate.validate_ir`
    itself. Unvalidated IR can raise :exc:`KeyError` during typed guard wiring or encode unsound
    reachability. Production callers must run ``validate_ir`` first (or use
    :func:`~smeme.reasoning.runtime.run.solve_reachability_witness`, which enforces this by default).

.. note::

    **Types do not prove validity yet.** :class:`~smeme.reasoning.ir.types.IR` carries no static
    proof that :func:`~smeme.reasoning.ir.validate.validate_ir` succeeded. ``validate=False`` on
    :func:`~smeme.reasoning.runtime.run.solve_reachability_witness` and calling :func:`compile_ir_to_z3`
    directly are intentional escape hatches (unit tests, trusted internals). That is acceptable
    **until first-party MCP, REST, or other public entrypoints** call this pipeline under real
    traffic: at that milestone, plan a **harder boundary** (for example a ``ValidIR`` wrapper or
    ``typing.NewType`` produced only from validation, and ``compile_ir_to_z3(ir: ValidIR)``) so bad
    graphs cannot reach Z3 by typo or copy-paste. No need to block shipping before integration; this
    note exists so the next design pass does not rediscover the footgun from scratch.

Each IR node maps to a **reach** boolean ``ir_reach_<id>``. Non-entry nodes satisfy:

``reach[n] == Or_i ( reach[parent_i] ∧ G_guard_i )``

Entry nodes (no incoming edges) are asserted TRUE. **``validate_ir``** requires exactly **one**
entry, so theory matches **single-start** decision tree/session execution; multi-root IR is rejected before
this layer. Default guards (``DEFAULT_GUARD_EXPR``) are asserted TRUE.

**Radio:** :mod:`~smeme.reasoning.theory.guards_radio` (option label guards).

This prevents “floating” reachability without a supporting path from an entry.

**Phase 1:** Valid IR is a **DAG** (see :func:`~smeme.reasoning.ir.validate.validate_ir`). Runtime checks are **existential** ``SAT(T(IR) ∧ φ)`` queries over abstract atoms—not Phase 2 evidence-grounded evaluation.

**Proof theory vs models:** Each ``solver.add(φ)`` is one conjunct of the compiled theory (not a rule with hypotheses). For Booleans, ``guard == option_atom`` is **material equivalence** (iff). See :mod:`~smeme.reasoning.theory.guards_radio` and ``smeme/reasoning/evaluate_semantics.md`` (theory vs evidence).
"""

from __future__ import annotations

from typing import TypedDict

from z3 import And, Bool, BoolRef, Context, Not, Or, Solver

from smeme.reasoning.ir.types import DEFAULT_GUARD_EXPR, IR, IREdge
from smeme.reasoning.theory.guards_radio import apply_radio_guard_semantics
from smeme.reasoning.theory.z3_symbols import z3_sym_fragment


class IRSymbolTable(TypedDict):
    """Maps IR node ids and guard ids to Z3 boolean variables (reach predicates + guards)."""

    nodes: dict[str, BoolRef]
    guards: dict[str, BoolRef]


# -----------------------------------------------------------------------------
# FUTURE HARDER BOUNDARY (when MCP / REST wire this pipeline)
#
# Validity is a documented + runtime contract: use validate_ir, or solve_reachability_witness(validate=True).
# IR plus validate=False plus compile_ir_to_z3(ir) is a deliberate footgun the type checker cannot
# catch. When first-party HTTP/MCP surfaces ship, consider ValidIR (wrapper or NewType) so compile
# only accepts proof-carrying IR. See module docstring ".. note::" for the same intent in prose.
# -----------------------------------------------------------------------------


def compile_ir_to_z3(ir: IR) -> tuple[Solver, IRSymbolTable]:
    """
    Build a solver with guarded reachability equalities for **validated** IR.

    Valid IR in Phase 1 includes a **DAG** (no self-loops / directed cycles); that keeps the explicit
    recurrence aligned with structural SAT checks over ``T(IR)``.

    **Contract:** ``assert validate_ir(ir).valid`` (or equivalent) before calling. This function
    assumes **valid IR**—it does **not** invoke :func:`~smeme.reasoning.ir.validate.validate_ir`.
    If that assumption is violated, behavior is undefined; typical failure is :exc:`KeyError`
    during guard wiring (no silent repair of malformed typed guards).

    Returns:
        (solver, {"nodes": {node_id: reach BoolRef}, "guards": {guard_id: BoolRef}})
    """
    # Create an isolated context per compile so concurrent readiness/eval requests
    # don't share Z3 global state across worker threads.
    ctx = Context()
    solver = Solver(ctx=ctx)

    reach: dict[str, BoolRef] = {}
    for n in ir.nodes:
        sym = "ir_reach_" + z3_sym_fragment(n.id)
        reach[n.id] = Bool(sym, ctx=ctx)

    guard_bools: dict[str, BoolRef] = {}
    for g in ir.guards:
        sym = "ir_g_" + z3_sym_fragment(g.id)
        ref = Bool(sym, ctx=ctx)
        guard_bools[g.id] = ref
        # Default-edge guards only: always TRUE. Non-default guards are never asserted here—they
        # are fixed by guards_radio.
        if g.expr == DEFAULT_GUARD_EXPR:
            solver.add(ref)

    apply_radio_guard_semantics(solver, ir, reach, guard_bools)

    incoming_targets = {e.target for e in ir.edges}
    incoming_by_target: dict[str, list[IREdge]] = {}
    for e in ir.edges:
        incoming_by_target.setdefault(e.target, []).append(e)

    entry_ids = {n.id for n in ir.nodes if n.id not in incoming_targets}

    for nid in sorted(reach.keys()):
        if nid in entry_ids:
            solver.add(reach[nid])
            continue
        inc = incoming_by_target.get(nid, [])
        if not inc:
            solver.add(Not(reach[nid]))
            continue
        terms = [And(reach[e.source], guard_bools[e.guard_id]) for e in inc]
        rhs: BoolRef = terms[0] if len(terms) == 1 else Or(*terms)
        solver.add(reach[nid] == rhs)

    symbol_table: IRSymbolTable = {"nodes": reach, "guards": guard_bools}
    return solver, symbol_table
