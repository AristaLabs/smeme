"""DecisionTree → symbolic IR compilation."""

from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)
from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
    IR_FORMAT_VERSION,
    IREdge,
    IRNodeKind,
    IRQuestionShape,
)
from smeme.reasoning.dt_graph_bridge import compile_dt_graph_to_ir


def _radio_two_conclusions() -> DTGraph:
    return DTGraph(
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
        metadata=DTGraphMetadata(title="IR unit test"),
    )


def test_compile_dt_graph_to_ir_structure_and_determinism():
    g = _radio_two_conclusions()
    a = compile_dt_graph_to_ir(g)
    b = compile_dt_graph_to_ir(g)
    assert a == b
    assert a.format_version == IR_FORMAT_VERSION

    assert [n.id for n in a.nodes] == ["c1", "c2", "q1"]
    q1 = next(n for n in a.nodes if n.id == "q1")
    assert q1.question == IRQuestionShape(qtype="radio", options=("Yes", "No"))
    assert all(n.kind == IRNodeKind.CONCLUSION for n in a.nodes if n.id.startswith("c"))
    assert all(n.kind == IRNodeKind.QUESTION for n in a.nodes if n.id == "q1")

    assert len(a.edges) == 2
    assert len(a.guards) == 2
    assert a.edges[0].guard_id == "g_000000"
    assert a.guards[0].id == "g_000000"
    assert a.edges[1].guard_id == "g_000001"
    assert a.guards[1].id == "g_000001"
    assert a.guards[0].expr == "Yes"
    assert a.guards[1].expr == "No"
    assert a.edges[0] == IREdge(source="q1", target="c1", guard_id="g_000000")


def test_compile_default_edge_empty_guard_expr():
    g = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q", type="radio", options=["A", "B"], required=True),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="C", summary="s"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="D", summary="t"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="A"),
            GraphEdge(source="q1", target="c2", condition=None),
        ],
        metadata=DTGraphMetadata(title="default edge"),
    )
    ir = compile_dt_graph_to_ir(g)
    assert ir.guards[0].expr == "A"
    assert ir.guards[1].expr == DEFAULT_GUARD_EXPR
