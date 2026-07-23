"""Unit tests for shared reachability assumptions (ALGEBRA §18)."""

from __future__ import annotations

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
    IR,
    IR_FORMAT_VERSION,
    Guard,
    IREdge,
    IRNode,
    IRNodeKind,
    IRQuestionShape,
)
from smeme.reasoning.ir.validate import validate_ir
from smeme.reasoning.runtime.assumptions import (
    AssumptionsError,
    assumptions_from_lists,
    validate_assumptions,
)
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_envelope import ParsedIngestEnvelope
from smeme.reasoning.runtime.report_builder import build_evaluation_report

_Q_RADIO = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _chain_ir() -> IR:
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C_yes", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C_no", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_q1y"),
            IREdge(source="Q1", target="C_no", guard_id="g_q1n"),
            IREdge(source="Q2", target="C_yes", guard_id="g_q2y"),
            IREdge(source="Q2", target="C_no", guard_id="g_q2n"),
        ),
        guards=(
            Guard(id="g_q1y", expr="Yes"),
            Guard(id="g_q1n", expr="No"),
            Guard(id="g_q2y", expr="Yes"),
            Guard(id="g_q2n", expr="No"),
        ),
    )


def _chain_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="Q1",
                type="question",
                data=QuestionData(text="Gate?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="Q2",
                type="question",
                data=QuestionData(text="Detail?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="C_yes",
                type="conclusion",
                data=ConclusionData(title="Eligible", summary="Yes"),
            ),
            GraphNode(
                id="C_no",
                type="conclusion",
                data=ConclusionData(title="Not eligible", summary="No"),
            ),
        ],
        edges=[
            GraphEdge(source="Q1", target="Q2", condition="Yes"),
            GraphEdge(source="Q1", target="C_no", condition="No"),
            GraphEdge(source="Q2", target="C_yes", condition="Yes"),
            GraphEdge(source="Q2", target="C_no", condition="No"),
        ],
        metadata=QNRMetadata(title="Chain"),
    )


def test_validate_unknown_assumption_node() -> None:
    ir = _chain_ir()
    phi = assumptions_from_lists(force_unreachable_ids=["NOPE"])
    with pytest.raises(AssumptionsError) as exc:
        validate_assumptions(ir, phi)
    assert exc.value.code == "invalid_assumption_node_id"


def test_validate_conflicting_assumptions() -> None:
    ir = _chain_ir()
    phi = assumptions_from_lists(
        force_reachable_ids=["Q2"],
        force_unreachable_ids=["Q2"],
    )
    with pytest.raises(AssumptionsError) as exc:
        validate_assumptions(ir, phi)
    assert exc.value.code == "conflicting_assumptions"


def test_force_unreachable_changes_outcome() -> None:
    ir = _chain_ir()
    assert validate_ir(ir).valid
    # Without assumptions: Q1=Yes, Q2=Yes → Eligible
    base, _ = evaluate_reasoning(ir, raw_answers={"Q1": "Yes", "Q2": "Yes"}, skip_ir_validation=True)
    assert base.status == "SAT_UNIQUE"
    assert base.true_conclusion_id == "C_yes"

    # Kill Q2 path → cannot conclude Eligible under same answers
    phi = assumptions_from_lists(force_unreachable_ids=["Q2"])
    blocked, _ = evaluate_reasoning(
        ir,
        raw_answers={"Q1": "Yes", "Q2": "Yes"},
        skip_ir_validation=True,
        assumptions=phi,
    )
    assert blocked.status == "UNSAT"
    assert blocked.explanation.get("reason") == "assumptions_unsat"

    graph = _chain_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "Yes", "Q2": "Yes"}, evidence_items=[], evidence_refs={})
    report = build_evaluation_report(graph=graph, envelope=env, eval_result=blocked)
    assert report["result_kind"] == "assumptions_inconsistent"
