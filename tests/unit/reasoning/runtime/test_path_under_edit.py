"""Unit tests for path entailment under a hypothetical answer edit."""

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
from smeme.reasoning.runtime.path_under_edit import (
    PathUnderEditError,
    run_edit_affects_path,
)

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
                data=QuestionData(text="First?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="Q2",
                type="question",
                data=QuestionData(text="Second?", type="radio", options=["Yes", "No"]),
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
            GraphEdge(source="Q1", target="Q2", condition="Yes"),
            GraphEdge(source="Q1", target="C_no", condition="No"),
            GraphEdge(source="Q2", target="C_yes", condition="Yes"),
            GraphEdge(source="Q2", target="C_no", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Chain"),
    )


def _shape_c(answers: dict[str, str]) -> dict:
    return {"answers": answers, "evidence_items": [], "evidence_refs": {}}


@pytest.fixture(autouse=True)
def _validate_fixtures() -> None:
    validate_ir(_exclusive_radio_ir())
    validate_ir(_chain_ir())


def test_identity_override_path_still_entailed() -> None:
    result = run_edit_affects_path(
        _exclusive_radio_ir(),
        _exclusive_radio_graph(),
        base_payload=_shape_c({"Q1": "Yes"}),
        override_payload=_shape_c({}),
    )
    assert result.path_still_entailed is True
    wire = result.to_wire()
    assert wire["path_still_entailed"] is True
    assert wire["edit_affects_path"] is False
    assert wire["path_nodes_lost"] == []
    assert any(c["conclusion_id"] == "C_yes" for c in wire["conclusions_still_entailed"])
    assert wire["conclusions_newly_entailed"] == []
    assert wire["changed_answers"] == []


def test_on_path_flip_breaks_path_and_new_conclusion() -> None:
    result = run_edit_affects_path(
        _exclusive_radio_ir(),
        _exclusive_radio_graph(),
        base_payload=_shape_c({"Q1": "Yes"}),
        override_payload=_shape_c({"Q1": "No"}),
    )
    wire = result.to_wire()
    assert wire["path_still_entailed"] is False
    assert wire["edit_affects_path"] is True
    assert wire["path_nodes_lost"]
    newly_ids = {c["conclusion_id"] for c in wire["conclusions_newly_entailed"]}
    lost_ids = {c["conclusion_id"] for c in wire["conclusions_no_longer_entailed"]}
    assert "C_no" in newly_ids
    assert "C_yes" in lost_ids
    assert wire["changed_answers"] == [
        {"question_id": "Q1", "before": "Yes", "after": "No"},
    ]


def test_off_path_answer_keeps_path_entailed() -> None:
    """Baseline ends at C_no via Q1=No; answering unreachable Q2 should not break that path."""
    result = run_edit_affects_path(
        _chain_ir(),
        _chain_graph(),
        base_payload=_shape_c({"Q1": "No"}),
        override_payload=_shape_c({"Q2": "Yes"}),
    )
    wire = result.to_wire()
    assert wire["path_still_entailed"] is True
    assert wire["edit_affects_path"] is False
    assert any(c["conclusion_id"] == "C_no" for c in wire["conclusions_still_entailed"])


def test_incomplete_baseline_raises() -> None:
    with pytest.raises(PathUnderEditError) as exc_info:
        run_edit_affects_path(
            _chain_ir(),
            _chain_graph(),
            base_payload=_shape_c({"Q1": "Yes"}),
            override_payload=_shape_c({"Q2": "Yes"}),
        )
    assert exc_info.value.code == "path_not_entailed_at_baseline"
