"""Unit tests for inclusion-minimal decisive answer supports."""

from __future__ import annotations

import pytest

from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
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
from smeme.reasoning.runtime.assumptions import assumptions_from_lists
from smeme.reasoning.runtime.counterfactual import entails_target
from smeme.reasoning.runtime.decisive_support import (
    DecisiveSupportError,
    find_minimal_decisive_supports,
)
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

_Q_RADIO = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _exclusive_radio_ir() -> IR:
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
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


def _exclusive_radio_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="Q1",
                type="question",
                data=QuestionData(text="Proceed?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="C_yes",
                type="conclusion",
                data=ConclusionData(title="Eligible", summary="Yes path"),
            ),
            GraphNode(
                id="C_no",
                type="conclusion",
                data=ConclusionData(title="Not eligible", summary="No path"),
            ),
        ],
        edges=[
            GraphEdge(source="Q1", target="C_yes", condition="Yes"),
            GraphEdge(source="Q1", target="C_no", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Test"),
    )


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
        metadata=DTGraphMetadata(title="Chain"),
    )


def _assert_support_is_minimal(ir: IR, support: dict[str, str], target: str) -> None:
    solver, sym = compile_ir_to_z3(ir)
    reach = sym["nodes"]
    sat_calls = [0]
    full = entails_target(
        solver,
        reach,
        ir,
        support,
        target,
        sat_calls=sat_calls,
        max_sat_calls=200,
        timeout_ms=5000,
    )
    assert full == "yes"
    for qid in list(support):
        dropped = {k: v for k, v in support.items() if k != qid}
        gate = entails_target(
            solver,
            reach,
            ir,
            dropped,
            target,
            sat_calls=sat_calls,
            max_sat_calls=200,
            timeout_ms=5000,
        )
        assert gate == "no", f"dropping {qid} should break entailment"


def test_decisive_support_exclusive_radio() -> None:
    ir = _exclusive_radio_ir()
    assert validate_ir(ir).valid
    graph = _exclusive_radio_graph()
    result = find_minimal_decisive_supports(
        ir,
        graph,
        base_norm={"Q1": "Yes"},
        target_conclusion_id="C_yes",
        top_k=3,
    )
    assert result.target_conclusion_title == "Eligible"
    assert len(result.supports) == 1
    assert result.supports[0].support_answers == {"Q1": "Yes"}
    _assert_support_is_minimal(ir, result.supports[0].support_answers, "C_yes")
    wire = result.to_wire()
    assert wire["count"] == 1
    assert "assumptions" not in wire


def test_decisive_support_chain_needs_both_answers() -> None:
    ir = _chain_ir()
    assert validate_ir(ir).valid
    graph = _chain_graph()
    result = find_minimal_decisive_supports(
        ir,
        graph,
        base_norm={"Q1": "Yes", "Q2": "Yes"},
        target_conclusion_id="C_yes",
        top_k=1,
    )
    assert result.supports[0].support_answers == {"Q1": "Yes", "Q2": "Yes"}
    _assert_support_is_minimal(ir, result.supports[0].support_answers, "C_yes")


def test_decisive_support_target_not_entailed() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    with pytest.raises(DecisiveSupportError) as exc:
        find_minimal_decisive_supports(
            ir,
            graph,
            base_norm={"Q1": "No"},
            target_conclusion_id="C_yes",
        )
    assert exc.value.code == "target_not_entailed"


def test_decisive_support_invalid_target() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    with pytest.raises(DecisiveSupportError) as exc:
        find_minimal_decisive_supports(
            ir,
            graph,
            base_norm={"Q1": "Yes"},
            target_conclusion_id="NOPE",
        )
    assert exc.value.code == "invalid_target_conclusion_id"


def test_decisive_support_with_assumptions_echo() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    phi = assumptions_from_lists(force_reachable_ids=["C_yes"])
    # Q1=Yes already forces C_yes; φ is redundant but must echo.
    result = find_minimal_decisive_supports(
        ir,
        graph,
        base_norm={"Q1": "Yes"},
        target_conclusion_id="C_yes",
        assumptions=phi,
    )
    assert result.assumptions.force_reachable == frozenset({"C_yes"})
    assert result.to_wire()["assumptions"]["force_reachable_ids"] == ["C_yes"]
