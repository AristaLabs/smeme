"""Unit tests for flat validation issue rows (Phase 4 jump-to-node)."""

from smeme.qnr.helpers.validation import (
    build_validation_issue_rows,
    extract_validation_node_id,
    node_ids_for_validation_message,
    validate_graph_for_editing,
)
from smeme.qnr.models import GraphEdge, GraphNode, QNRGraph, QNRMetadata, QuestionData


def test_extract_validation_node_id_from_question_message() -> None:
    assert extract_validation_node_id("Question 'q1' has duplicate options: Yes") == "q1"
    assert extract_validation_node_id("Question node 'q1' missing question text") == "q1"
    assert extract_validation_node_id("Conclusion node 'c1' missing title") == "c1"
    assert extract_validation_node_id("Radio question 'q1' must have options") == "q1"
    assert extract_validation_node_id("Condition 'Yes' from 'q1' must match an option label") == "q1"
    assert extract_validation_node_id("Edge to conclusion 'c1' from 'q1' must be conditional") == "q1"


def test_extract_validation_node_id_returns_none_for_structure() -> None:
    assert extract_validation_node_id("Graph must have exactly one entry node") is None
    assert extract_validation_node_id("⚠️ No entry point (all nodes have incoming edges)") is None


def test_node_ids_for_structure_warnings() -> None:
    assert node_ids_for_validation_message("⚠️ Cycle detected: q3 → q1 → q1") == ["q3"]
    assert node_ids_for_validation_message(
        "⚠️ Orphaned nodes: conclusion_1, q4, q6"
    ) == ["conclusion_1", "q4", "q6"]
    assert node_ids_for_validation_message(
        "⚠️ No entry point (all nodes have incoming edges)"
    ) == []


def test_build_validation_issue_rows_expands_orphaned_nodes() -> None:
    rows = build_validation_issue_rows(
        [],
        ["⚠️ Orphaned nodes: q1, q2"],
    )
    assert len(rows) == 2
    assert rows[0]["node_id"] == "q1"
    assert rows[1]["node_id"] == "q2"
    assert "Jump" not in rows[0]["message"]


def test_build_validation_issue_rows_cycle_warning_has_first_node() -> None:
    rows = build_validation_issue_rows([], ["⚠️ Cycle detected: q3 → q1 → q1"])
    assert len(rows) == 1
    assert rows[0]["node_id"] == "q3"


def test_build_validation_issue_rows_orders_errors_before_warnings() -> None:
    rows = build_validation_issue_rows(
        ["Question 'q1' has duplicate options: Yes"],
        ["⚠️ Question 'q2' has no outgoing edges."],
    )
    assert len(rows) == 2
    assert rows[0]["severity"] == "error"
    assert rows[0]["node_id"] == "q1"
    assert rows[1]["severity"] == "warning"
    assert rows[1]["node_id"] == "q2"


def test_build_validation_issue_rows_includes_suggestions() -> None:
    rows = build_validation_issue_rows(
        ["Question 'q1' has duplicate options: Yes"],
        [],
        suggestions={
            "Question 'q1' has duplicate options: Yes": "Rename duplicate choices.",
        },
    )
    assert rows[0]["suggestion"] == "Rename duplicate choices."


def test_build_validation_issue_rows_propagates_suggestion_to_split_orphans() -> None:
    rows = build_validation_issue_rows(
        [],
        ["⚠️ Orphaned nodes: q1, q2"],
        suggestions={
            "⚠️ Orphaned nodes: q1, q2": "Connect each orphaned node from the entry question.",
        },
    )
    assert len(rows) == 2
    assert rows[0]["suggestion"] == "Connect each orphaned node from the entry question."
    assert rows[1]["suggestion"] == "Connect each orphaned node from the entry question."


def test_validate_graph_for_editing_includes_suggestions_for_errors() -> None:
    graph = QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q1", type="radio", options=["Yes"], required=True),
            ),
        ],
        edges=[GraphEdge(source="q1", target="q1")],
        metadata=QNRMetadata(title="Self loop"),
    )
    result = validate_graph_for_editing(graph)
    loop_msg = next(msg for msg in result["errors"] if "Self-loop" in msg)
    assert result["suggestions"][loop_msg]
