"""IR → Z3 structure encoding (Day 5)."""

import pytest
from z3 import Not, is_true, sat, unsat

from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
)
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

_Q = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _assert_model_nodes_true(ir: IR, node_ids: list[str]) -> None:
    assert validate_ir(ir).valid
    solver, sym = compile_ir_to_z3(ir)
    assert solver.check() == sat
    m = solver.model()
    for nid in node_ids:
        ref = sym["nodes"][nid]
        val = m.eval(ref, model_completion=True)
        assert is_true(val), f"expected {nid!r} true in model, got {val}"


def test_linear_chain_q1_q2_c1_all_reachable_with_default_guards():
    """Q1 → Q2 → C1 with default (TRUE) guards; all reach_* true in some model."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_000000"),
            IREdge(source="Q2", target="C1", guard_id="g_000001"),
        ),
        guards=(
            Guard(id="g_000000", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_000001", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    _assert_model_nodes_true(ir, ["Q1", "Q2", "C1"])


def test_branching_q1_to_q2_and_q3_both_can_be_true():
    """Q1 → Q2 and Q1 → Q3; not XOR — both successors can be true."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Q3", kind=IRNodeKind.QUESTION, question=_Q),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_000000"),
            IREdge(source="Q1", target="Q3", guard_id="g_000001"),
        ),
        guards=(
            Guard(id="g_000000", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_000001", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    assert validate_ir(ir).valid
    solver, sym = compile_ir_to_z3(ir)
    assert solver.check() == sat
    m = solver.model()
    for nid in ("Q1", "Q2", "Q3"):
        assert is_true(m.eval(sym["nodes"][nid], model_completion=True))


def test_reachability_cannot_float_true_without_path():
    """With recurrence encoding, cannot force an on-path node false while entry holds."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_000000"),
            IREdge(source="Q2", target="C1", guard_id="g_000001"),
        ),
        guards=(
            Guard(id="g_000000", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_000001", expr=DEFAULT_GUARD_EXPR),
        ),
    )
    assert validate_ir(ir).valid
    solver, sym = compile_ir_to_z3(ir)
    solver.push()
    solver.add(Not(sym["nodes"]["Q2"]))
    assert solver.check() == unsat
    solver.pop()


def test_radio_conditional_edges_at_most_one_conclusion():
    """Radio Yes/No to two conclusions: exactly one conclusion reachable (mutually exclusive options)."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C2", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="C1", guard_id="g_000000"),
            IREdge(source="Q1", target="C2", guard_id="g_000001"),
        ),
        guards=(
            Guard(id="g_000000", expr="Yes"),
            Guard(id="g_000001", expr="No"),
        ),
    )
    assert validate_ir(ir).valid
    solver, sym = compile_ir_to_z3(ir)
    assert solver.check() == sat
    m = solver.model()
    c1 = is_true(m.eval(sym["nodes"]["C1"], model_completion=True))
    c2 = is_true(m.eval(sym["nodes"]["C2"], model_completion=True))
    assert c1 != c2


def test_radio_unknown_guard_expr_rejected_by_validate_ir():
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="Maybe"),),
    )
    report = validate_ir(ir)
    assert not report.valid
    assert any("Radio guard expr not in question options" in e for e in report.errors)


def test_radio_unknown_guard_expr_compile_raises_without_valid_ir():
    """``compile_ir_to_z3`` assumes :func:`~smeme.reasoning.ir.validate.validate_ir`; invalid option
    strings are not repaired in theory (``KeyError`` from option lookup)."""
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C1", guard_id="g_000000"),),
        guards=(Guard(id="g_000000", expr="Maybe"),),
    )
    with pytest.raises(KeyError):
        compile_ir_to_z3(ir)
