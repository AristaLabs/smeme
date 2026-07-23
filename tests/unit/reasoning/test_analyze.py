"""Internal conclusion SAT enumeration (runtime/analyze.py)."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    QNRMetadata,
    QuestionData,
)
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
from smeme.reasoning.ir.validate import IRValidationError, validate_ir
from smeme.reasoning.qnr_bridge import compile_qnr_to_ir
from smeme.reasoning.runtime.analyze import (
    ConclusionSatQueryEnumeration,
    enumerate_conclusion_sat_queries,
)
from smeme.reasoning.runtime.run import solve_reachability_witness

_Q = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _diamond_merge_ir() -> IR:
    """Q0 → Qa | Qb → C1 (single conclusion); merge diamond."""
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q0", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Qa", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Qb", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q0", target="Qa", guard_id="g_0"),
            IREdge(source="Q0", target="Qb", guard_id="g_1"),
            IREdge(source="Qa", target="C1", guard_id="g_2"),
            IREdge(source="Qb", target="C1", guard_id="g_3"),
        ),
        guards=(
            Guard(id="g_0", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_1", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_2", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g_3", expr=DEFAULT_GUARD_EXPR),
        ),
    )


def _exclusive_conclusions_ir() -> IR:
    """One radio question branches to two conclusions (mutually incompatible guards)."""
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C_yes", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C_no", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="C_yes", guard_id="g_y"),
            IREdge(source="Q1", target="C_no", guard_id="g_n"),
        ),
        guards=(
            Guard(id="g_y", expr="Yes"),
            Guard(id="g_n", expr="No"),
        ),
    )


def test_enumerate_conclusion_sat_queries_base_and_per_conclusion():
    ir = _diamond_merge_ir()
    r = enumerate_conclusion_sat_queries(ir)
    assert isinstance(r, ConclusionSatQueryEnumeration)
    assert r.validation_report is not None
    assert r.validation_report.valid
    assert r.is_theory_satisfiable is True
    assert r.conclusion_reachable["C1"] is True


def test_enumerate_conclusion_sat_queries_pairwise_exclusive_conclusions():
    ir = _exclusive_conclusions_ir()
    r = enumerate_conclusion_sat_queries(ir)
    assert r.is_theory_satisfiable is True
    assert r.conclusion_reachable["C_yes"] is True
    assert r.conclusion_reachable["C_no"] is True
    assert r.conclusion_pairs_co_reachable[("C_no", "C_yes")] is False


def test_enumerate_conclusion_sat_queries_diamond_merge_single_conclusion_no_pairs():
    ir = _diamond_merge_ir()
    r = enumerate_conclusion_sat_queries(ir)
    assert r.conclusion_pairs_co_reachable == {}


def test_enumerate_conclusion_sat_queries_outcomes_stable_across_runs():
    ir = _exclusive_conclusions_ir()
    a = enumerate_conclusion_sat_queries(ir)
    b = enumerate_conclusion_sat_queries(ir)
    assert a.is_theory_satisfiable == b.is_theory_satisfiable
    assert a.conclusion_reachable == b.conclusion_reachable
    assert a.conclusion_pairs_co_reachable == b.conclusion_pairs_co_reachable


def test_enumerate_conclusion_sat_queries_parallel_calls_do_not_crash():
    ir = _exclusive_conclusions_ir()
    expected = enumerate_conclusion_sat_queries(ir)

    def _run_once(_: int) -> tuple[bool, dict[str, bool], dict[tuple[str, str], bool]]:
        r = enumerate_conclusion_sat_queries(ir)
        return (
            r.is_theory_satisfiable,
            r.conclusion_reachable,
            r.conclusion_pairs_co_reachable,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_run_once, range(64)))

    for is_sat, reachable, pairs in results:
        assert is_sat == expected.is_theory_satisfiable
        assert reachable == expected.conclusion_reachable
        assert pairs == expected.conclusion_pairs_co_reachable


def test_enumerate_conclusion_sat_queries_from_compiled_dt_graph():
    """End-to-end: DTGraph → IR → validate → enumeration + witness."""
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick",
                    type="radio",
                    options=["Yes", "No"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Out A", summary="a"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="Out B", summary="b"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=QNRMetadata(title="v"),
    )
    ir = compile_qnr_to_ir(g)
    assert validate_ir(ir).valid

    r = enumerate_conclusion_sat_queries(ir)
    assert r.validation_report is not None
    assert r.is_theory_satisfiable is True
    assert r.conclusion_reachable["c1"] is True
    assert r.conclusion_reachable["c2"] is True
    assert r.conclusion_pairs_co_reachable[("c1", "c2")] is False

    run = solve_reachability_witness(ir)
    assert run.z3_status == "sat"
    assert run.validation_report is not None
    assert set(run.reachable_conclusion_ids) <= {"c1", "c2"}
    assert len(run.reachable_conclusion_ids) == 1


def test_enumerate_conclusion_sat_queries_invalid_ir_raises():
    ir = IR(
        format_version=IR_FORMAT_VERSION - 1,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
        ),
        edges=(),
        guards=(),
    )
    with pytest.raises(IRValidationError) as exc:
        enumerate_conclusion_sat_queries(ir)
    assert not exc.value.report.valid
