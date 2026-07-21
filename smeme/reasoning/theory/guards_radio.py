"""Radio question guard semantics: option atoms + exactly-one + edge guard wiring."""

from __future__ import annotations

from z3 import Bool, BoolRef, Implies, Not, PbEq, Solver

from smeme.reasoning.ir.types import DEFAULT_GUARD_EXPR, IR, IRNodeKind
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name


def apply_radio_guard_semantics(
    solver: Solver,
    ir: IR,
    reach: dict[str, BoolRef],
    guard_bools: dict[str, BoolRef],
) -> None:
    """
    For each **radio** question node: introduce one Bool per listed option; when the node is
    reachable, assert **exactly one** option (PbEq). Wire each non-:data:`DEFAULT_GUARD_EXPR` guard
    on an outgoing edge to ``guard == option_atom[expr]`` when ``expr`` matches an option;     otherwise ``guard == False``.
    """
    nodes_by_id = {n.id: n for n in ir.nodes}
    guard_source: dict[str, str] = {}
    for e in ir.edges:
        guard_source[e.guard_id] = e.source

    radio_option_atom: dict[str, dict[str, BoolRef]] = {}
    for n in ir.nodes:
        if n.kind != IRNodeKind.QUESTION or n.question is None:
            continue
        if n.question.qtype != "radio":
            continue
        opts = n.question.options
        if not opts:
            continue
        atoms: dict[str, BoolRef] = {}
        for opt in opts:
            sym = radio_option_symbol_name(n.id, opt)
            atoms[opt] = Bool(sym, ctx=solver.ctx)
        radio_option_atom[n.id] = atoms

    for qid, atoms in radio_option_atom.items():
        r = reach[qid]
        bs = list(atoms.values())
        if len(bs) == 1:
            solver.add(Implies(r, bs[0]))
        else:
            solver.add(Implies(r, PbEq([(b, 1) for b in bs], 1)))

    for g in ir.guards:
        if g.expr == DEFAULT_GUARD_EXPR:
            continue
        src = guard_source.get(g.id)
        if src is None:
            continue
        node = nodes_by_id.get(src)
        if node is None or node.kind != IRNodeKind.QUESTION or node.question is None:
            continue
        if node.question.qtype != "radio":
            continue
        atoms = radio_option_atom.get(src)
        ref = guard_bools[g.id]
        if atoms is None or not node.question.options:
            # Empty options or missing atom table (hand-built IR / ``validate_ir`` skipped).
            solver.add(Not(ref))
            continue
        # Validated IR: ``expr`` is always a key in ``atoms`` (exact option label).
        solver.add(ref == atoms[g.expr])
