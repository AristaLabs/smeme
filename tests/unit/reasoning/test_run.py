"""Runtime: IR → Z3 check → ReachabilityWitness."""

import pytest

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
from smeme.reasoning.ir.validate import IRValidationError
from smeme.reasoning.runtime.run import solve_reachability_witness

_Q = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _linear_chain_ir() -> IR:
    return IR(
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


def test_solve_reachability_witness_sat_lists_reachable_conclusion_and_nodes():
    ir = _linear_chain_ir()
    r = solve_reachability_witness(ir)
    assert r.z3_status == "sat"
    assert r.validation_report is not None
    assert r.validation_report.valid
    assert r.reachable_conclusion_ids == ("C1",)
    assert r.node_reachable is not None
    assert r.node_reachable["Q1"] is True
    assert r.node_reachable["Q2"] is True
    assert r.node_reachable["C1"] is True


def test_solve_reachability_witness_invalid_ir_raises():
    ir = IR(
        format_version=IR_FORMAT_VERSION - 1,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
        ),
        edges=(),
        guards=(),
    )
    with pytest.raises(IRValidationError) as exc:
        solve_reachability_witness(ir)
    assert not exc.value.report.valid
    assert exc.value.report.errors


def test_solve_reachability_witness_skip_validation_calls_z3():
    """Invalid IR can still be passed with validate=False (caller responsibility)."""
    ir = IR(
        format_version=IR_FORMAT_VERSION - 1,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
        ),
        edges=(),
        guards=(),
    )
    r = solve_reachability_witness(ir, validate=False)
    assert r.validation_report is None
    assert r.z3_status == "sat"


def test_reachability_witness_to_dict_contract():
    ir = _linear_chain_ir()
    r = solve_reachability_witness(ir)
    d = r.to_dict()
    assert d["sat"] is True
    assert d["z3_status"] == "sat"
    assert d["reachable_conclusions"] == ["C1"]
    assert set(d["reachable_nodes"]) == {"Q1", "Q2", "C1"}
    assert d["validation_valid"] is True
    assert d["validation_errors"] == []
