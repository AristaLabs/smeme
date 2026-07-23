"""IR validation: structure, DAG constraint, reference integrity, and typed guard well-formedness.

**Non-** :data:`~smeme.reasoning.ir.types.DEFAULT_GUARD_EXPR` **guards on question edges:**

- **Radio:** non-empty ``expr`` (after strip) and **exact** membership in ``IRQuestionShape.options``.
"""

from __future__ import annotations

from collections import defaultdict

from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    ValidationReport,
)


class IRValidationError(ValueError):
    """IR failed :func:`validate_ir` while the caller required a valid program.

    Raised by :func:`~smeme.reasoning.runtime.run.solve_reachability_witness` when ``validate=True`` (default)
    and ``validate_ir(ir).valid`` is false. Callers at HTTP/MCP boundaries should map this to a
    client error and must not call :func:`~smeme.reasoning.theory.compile_to_z3.compile_ir_to_z3`
    on the same IR without fixing it or using explicit ``validate=False`` (advanced / tests only).
    """

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        detail = "; ".join(report.errors) if report.errors else "IR validation failed"
        super().__init__(detail)


_UNSEEN = 0
_VISITING = 1
_DONE = 2


def _dag_structure_errors(edges: tuple[IREdge, ...], node_ids: set[str]) -> list[str]:
    """Detect self-loops and directed cycles. Only edges with both endpoints in ``node_ids``."""
    errors: list[str] = []
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.source not in node_ids or e.target not in node_ids:
            continue
        if e.source == e.target:
            errors.append(
                "Self-loop edge (source equals target): "
                + repr(e.source)
                + " (guard "
                + repr(e.guard_id)
                + ")"
            )
            continue
        adj[e.source].append(e.target)

    state: dict[str, int] = {}
    cycle_found = False

    def dfs(u: str) -> None:
        nonlocal cycle_found
        if cycle_found:
            return
        state[u] = _VISITING
        for v in adj[u]:
            sv = state.get(v, _UNSEEN)
            if sv == _UNSEEN:
                dfs(v)
            elif sv == _VISITING:
                cycle_found = True
                return
            if cycle_found:
                return
        state[u] = _DONE

    for nid in sorted(node_ids):
        if state.get(nid, _UNSEEN) == _UNSEEN:
            dfs(nid)
            if cycle_found:
                break

    if cycle_found:
        errors.append("Directed cycle in IR graph (Phase 1 requires a DAG).")

    return errors


def validate_ir(ir: IR) -> ValidationReport:
    """
    Structural validation: unique node ids, edge endpoints, guard ids resolved.

    ``expr == DEFAULT_GUARD_EXPR`` is valid and means default-edge semantics (see ``types.py``).

    **Question sources:** Every question node must carry ``qtype="radio"`` with a non-empty
    ``options`` tuple. Non-default ``expr`` must be non-empty when stripped, and must equal one of
    that question's option strings (exact match).

    Enforces **exactly one entry node** (no incoming edges), matching single-start decision tree/session
    semantics; multi-root IR would make pure reachability theory looser than interactive execution.

    Enforces a **DAG**: no self-loops and no directed cycles on edges whose endpoints resolve to
    nodes (invalid endpoint references are reported separately and may omit cycle detection on
    those edges).
    """
    errors: list[str] = []

    if ir.format_version != IR_FORMAT_VERSION:
        msg = (
            "IR format_version mismatch: got "
            + repr(ir.format_version)
            + ", expected "
            + repr(IR_FORMAT_VERSION)
            + " (recompile from DecisionTree or upgrade consumer)"
        )
        errors.append(msg)

    node_ids: set[str] = set()
    for n in ir.nodes:
        if n.id in node_ids:
            msg = "Duplicate node id: " + repr(n.id)
            errors.append(msg)
        else:
            node_ids.add(n.id)
        if n.kind == IRNodeKind.CONCLUSION:
            if n.question is not None:
                msg = "Conclusion node must not have question shape: " + repr(n.id)
                errors.append(msg)
        elif n.kind == IRNodeKind.QUESTION:
            if n.question is None:
                msg = "Question node missing IRQuestionShape: " + repr(n.id)
                errors.append(msg)
            else:
                qshape = n.question
                if qshape.qtype != "radio":
                    msg = (
                        "Question node must use qtype 'radio' (got "
                        + repr(qshape.qtype)
                        + "): "
                        + repr(n.id)
                    )
                    errors.append(msg)
                if not qshape.options:
                    msg = "Question node must have non-empty options: " + repr(n.id)
                    errors.append(msg)

    guard_ids: set[str] = set()
    for g in ir.guards:
        if g.id in guard_ids:
            msg = "Duplicate guard id: " + repr(g.id)
            errors.append(msg)
        guard_ids.add(g.id)

    referenced_guards: set[str] = set()
    for e in ir.edges:
        if e.source not in node_ids:
            msg = "Edge source not a node: " + repr(e.source)
            errors.append(msg)
        if e.target not in node_ids:
            msg = "Edge target not a node: " + repr(e.target)
            errors.append(msg)
        if e.guard_id not in guard_ids:
            msg = "Edge references unknown guard: " + repr(e.guard_id)
            errors.append(msg)
        else:
            referenced_guards.add(e.guard_id)

    for gid in guard_ids:
        if gid not in referenced_guards:
            msg = "Unused guard (no edge references it): " + repr(gid)
            errors.append(msg)

    guards_by_id: dict[str, Guard] = {g.id: g for g in ir.guards}
    nodes_by_id: dict[str, IRNode] = {n.id: n for n in ir.nodes}

    for e in ir.edges:
        src_node = nodes_by_id.get(e.source)
        if src_node is None:
            continue
        guard = guards_by_id.get(e.guard_id)
        if guard is None:
            continue
        expr = guard.expr
        if expr == DEFAULT_GUARD_EXPR:
            continue
        if src_node.kind != IRNodeKind.QUESTION:
            continue
        qshape = src_node.question
        if qshape is None:
            continue

        options_set = set(qshape.options)
        if not expr.strip():
            msg = (
                "Radio guard expr is empty or whitespace-only: guard "
                + repr(e.guard_id)
                + " on edge "
                + repr(e.source)
                + " -> "
                + repr(e.target)
            )
            errors.append(msg)
            continue
        if expr not in options_set:
            msg = (
                "Radio guard expr not in question options: "
                + repr(expr)
                + " (guard "
                + repr(e.guard_id)
                + ", source "
                + repr(e.source)
                + ")"
            )
            errors.append(msg)

    errors.extend(_dag_structure_errors(ir.edges, node_ids))

    incoming_targets_only = {e.target for e in ir.edges}
    entry_ids = sorted(n.id for n in ir.nodes if n.id not in incoming_targets_only)
    if len(entry_ids) != 1:
        msg = (
            "Expected exactly one entry node (no incoming edges), found "
            + str(len(entry_ids))
            + (": " + ", ".join(entry_ids) if entry_ids else " (none)")
        )
        errors.append(msg)

    valid = not errors
    return ValidationReport(valid=valid, errors=tuple(errors))
