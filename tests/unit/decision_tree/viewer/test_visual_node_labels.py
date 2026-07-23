"""Unit tests for graph node display labels."""

from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
    QuestionData,
)
from smeme.decision_tree.viewer.layout import (
    VISUAL_LABEL_MAX_LEN,
    calculate_layout,
    truncate_visual_label,
    visual_node_label_text,
    visual_node_tooltip,
)


def test_visual_node_label_prefers_question_text() -> None:
    node = GraphNode(
        id="q1",
        type="question",
        data=QuestionData(text="Are you a US resident?", type="radio", options=["Yes", "No"]),
    )
    assert visual_node_label_text(node) == "Are you a US resident?"


def test_visual_node_label_prefers_conclusion_title() -> None:
    node = GraphNode(
        id="c_outcome",
        type="conclusion",
        data=ConclusionData(title="Recommend LLC", summary="Entity structure"),
    )
    assert visual_node_label_text(node) == "Recommend LLC"


def test_visual_node_label_falls_back_to_id() -> None:
    node = GraphNode(
        id="q_empty",
        type="question",
        data=QuestionData(text="", type="radio", options=["A"]),
    )
    assert visual_node_label_text(node) == "q_empty"


def test_truncate_visual_label_adds_ellipsis() -> None:
    long_text = "A" * (VISUAL_LABEL_MAX_LEN + 10)
    truncated = truncate_visual_label(long_text)
    assert len(truncated) == VISUAL_LABEL_MAX_LEN
    assert truncated.endswith("…")


def test_visual_node_tooltip_includes_id_when_display_differs() -> None:
    node = GraphNode(
        id="q1",
        type="question",
        data=QuestionData(text="Short question", type="radio", options=["Yes"]),
    )
    assert visual_node_tooltip(node, "Short question") == "Short question (q1)"


def test_calculate_layout_uses_question_text_label() -> None:
    graph = DTGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="What is your filing status?",
                    type="radio",
                    options=["Single", "Married"],
                    required=True,
                ),
            ),
            GraphNode(
                id="c1",
                type="conclusion",
                data=ConclusionData(title="Done", summary="Complete"),
            ),
        ],
        edges=[GraphEdge(source="q1", target="c1", condition="Single")],
        metadata=DTGraphMetadata(title="Label test"),
    )

    viz = calculate_layout(graph)
    by_id = {n.id: n for n in viz.nodes}
    assert by_id["q1"].label == "What is your filing status?"
    assert by_id["c1"].label == "Done"
    assert by_id["q1"].tooltip == "What is your filing status? (q1)"
