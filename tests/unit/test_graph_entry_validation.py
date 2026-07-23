"""Single-entry-node invariant for DecisionTree graphs."""

from smeme.decision_tree.helpers.validation import (
    bare_create_node_blocked_message,
    validate_graph,
    validate_graph_for_editing,
)
from smeme.decision_tree.models import GraphNode, DTGraph, DTGraphMetadata, QuestionData


def _two_entry_questions_graph() -> DTGraph:
    """Two questions, no edges: two indegree-zero nodes."""
    return DTGraph(
        nodes=[
            GraphNode(
                id="q_alpha",
                type="question",
                data=QuestionData(text="First?", type="radio", options=["Y", "N"], required=True),
            ),
            GraphNode(
                id="q_beta",
                type="question",
                data=QuestionData(text="Second?", type="radio", options=["Y", "N"], required=True),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="Two entries"),
    )


def test_validate_graph_rejects_multiple_entry_nodes():
    graph = _two_entry_questions_graph()
    ok, msg = validate_graph(graph)
    assert ok is False
    assert msg is not None
    assert "exactly one entry node" in msg.lower()
    assert "q_alpha" in msg
    assert "q_beta" in msg


def test_validate_graph_for_editing_blocks_multiple_entry_nodes():
    graph = _two_entry_questions_graph()
    result = validate_graph_for_editing(graph)
    assert result["is_valid"] is False
    assert any("exactly one entry node" in e.lower() for e in result["errors"])


def test_bare_create_node_allowed_empty_graph():
    graph = DTGraph(nodes=[], edges=[], metadata=DTGraphMetadata(title="Empty"))
    assert bare_create_node_blocked_message(graph) is None


def test_bare_create_node_blocked_nonempty_graph():
    graph = _two_entry_questions_graph()
    msg = bare_create_node_blocked_message(graph)
    assert msg is not None
    assert "second entry" in msg.lower() or "entry point" in msg.lower()
