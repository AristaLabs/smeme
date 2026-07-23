"""BFS layout linear order (checklist / canvas alignment)."""

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    QNRMetadata,
    QuestionData,
)
from smeme.qnr.viewer.layout import linear_node_ids_for_layout, ordered_nodes_for_checklist


def _branching_graph() -> DTGraph:
    """Same shape as multi_edge_graph in test_graph_operations."""
    return DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Pick one",
                    type="radio",
                    options=["A", "B", "C"],
                    required=True,
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(
                    text="Follow-up for A",
                    type="radio",
                    options=["Y", "N"],
                    required=True,
                ),
            ),
            GraphNode(
                id="conclusion_a",
                type="conclusion",
                data=ConclusionData(
                    title="Path A",
                    summary="You chose A",
                ),
            ),
            GraphNode(
                id="conclusion_b",
                type="conclusion",
                data=ConclusionData(
                    title="Path B",
                    summary="You chose B",
                ),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="A"),
            GraphEdge(source="q1", target="conclusion_b", condition="B"),
            GraphEdge(source="q2", target="conclusion_a", condition="Y"),
        ],
        metadata=QNRMetadata(title="Multi-Edge Test Graph"),
    )


def test_linear_node_ids_empty_graph():
    g = DTGraph(nodes=[], edges=[], metadata=QNRMetadata(title="Empty"))
    assert linear_node_ids_for_layout(g) == []
    assert ordered_nodes_for_checklist(g) == []


def test_linear_node_ids_bfs_layer_order():
    g = _branching_graph()
    order = linear_node_ids_for_layout(g)
    assert order[0] == "q1"
    assert set(order) == {n.id for n in g.nodes}
    # Same-layer siblings follow outgoing edge list order from q1
    assert order.index("q2") < order.index("conclusion_b")
    assert order.index("conclusion_a") > order.index("q2")


def test_ordered_nodes_matches_linear_ids():
    g = _branching_graph()
    ids = linear_node_ids_for_layout(g)
    nodes = ordered_nodes_for_checklist(g)
    assert [n.id for n in nodes] == ids
