"""Single-entry-node invariant for DecisionTree graphs.

Also covers algebra §4.1 focused source-validation rules (C4):
entry must be a QUESTION; conclusions are terminal; arcs into conclusions
are non-default.
"""

from smeme.decision_tree.helpers.validation import (
    bare_create_node_blocked_message,
    validate_graph,
    validate_graph_for_editing,
)
from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)


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


def test_validate_graph_rejects_conclusion_as_entry_node():
    """§4.1: sole zero-indegree node must be a QUESTION, not a CONCLUSION."""
    graph = DTGraph(
        nodes=[
            GraphNode(
                id="c_only",
                type="conclusion",
                data=ConclusionData(title="Alone", summary="Entry conclusion"),
            ),
        ],
        edges=[],
        metadata=DTGraphMetadata(title="Conclusion entry"),
    )
    ok, msg = validate_graph(graph)
    assert ok is False
    assert msg == "Conclusion node(s) cannot be entry points: c_only"


def test_validate_graph_rejects_arc_leaving_conclusion():
    """§4.1: conclusions are terminal — no outgoing arcs."""
    graph = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Proceed?", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(
                id="c_yes",
                type="conclusion",
                data=ConclusionData(title="Yes", summary="Yes path"),
            ),
            GraphNode(
                id="c_no",
                type="conclusion",
                data=ConclusionData(title="No", summary="No path"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c_yes", condition="Yes"),
            GraphEdge(source="q1", target="c_no", condition="No"),
            # Illegal: conclusion with outgoing edge
            GraphEdge(source="c_yes", target="c_no", condition="Yes"),
        ],
        metadata=DTGraphMetadata(title="Conclusion outbound"),
    )
    ok, msg = validate_graph(graph)
    assert ok is False
    assert msg == (
        "Conclusion node 'c_yes' cannot have outgoing edges. Remove edges to: c_no"
    )


def test_validate_graph_rejects_default_guard_into_conclusion():
    """§4.1: arcs into conclusions must be conditional (non-default)."""
    graph = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Proceed?", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(
                id="c_yes",
                type="conclusion",
                data=ConclusionData(title="Yes", summary="Yes path"),
            ),
            GraphNode(
                id="c_no",
                type="conclusion",
                data=ConclusionData(title="No", summary="No path"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c_yes", condition=None),
            GraphEdge(source="q1", target="c_no", condition="No"),
        ],
        metadata=DTGraphMetadata(title="Default into conclusion"),
    )
    ok, msg = validate_graph(graph)
    assert ok is False
    assert msg == (
        "Edge to conclusion 'c_yes' from 'q1' must be conditional, not default. "
        "Conclusions can only be reached by explicit answers, not fallbacks."
    )
