"""Tests for create_node_wired composite graph operation."""

import pytest

from smeme.qnr.editor.operations import apply_operation
from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    QNRGraph,
    QNRMetadata,
    QuestionData,
)


@pytest.fixture
def empty_graph() -> QNRGraph:
    return QNRGraph(nodes=[], edges=[], metadata=QNRMetadata(title="Empty"))


@pytest.fixture
def multi_edge_graph() -> QNRGraph:
    return QNRGraph(
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
                data=ConclusionData(title="Path A", summary="You chose A"),
            ),
            GraphNode(
                id="conclusion_b",
                type="conclusion",
                data=ConclusionData(title="Path B", summary="You chose B"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="q2", condition="A"),
            GraphEdge(source="q1", target="conclusion_b", condition="B"),
            GraphEdge(source="q2", target="conclusion_a", condition="Y"),
        ],
        metadata=QNRMetadata(title="Multi-Edge Test Graph"),
    )


def test_create_node_wired_first_question_on_empty_graph(empty_graph: QNRGraph):
    data = {
        "kind": "question",
        "node_id": "q_first",
        "question_text": "Hello?",
        "question_type": "radio",
        "options": ["Yes", "No"],
        "help_text": None,
        "required": True,
        "question_wiring": "none",
        "predecessor_ids": [],
        "incoming_edge_condition": None,
    }
    g = apply_operation(empty_graph, "create_node_wired", data)
    assert len(g.nodes) == 1
    assert g.nodes[0].id == "q_first"
    assert g.edges == []


def test_create_node_wired_question_incoming(multi_edge_graph: QNRGraph):
    data = {
        "kind": "question",
        "node_id": "q_side",
        "question_text": "Branch detail",
        "question_type": "radio",
        "options": ["A", "B"],
        "help_text": None,
        "required": True,
        "question_wiring": "incoming",
        "predecessor_ids": ["q1"],
        "incoming_edge_condition": None,
    }
    g = apply_operation(multi_edge_graph, "create_node_wired", data)
    assert any(n.id == "q_side" for n in g.nodes)
    assert any(e.source == "q1" and e.target == "q_side" for e in g.edges)
    assert len(g.get_entry_nodes()) == 1


def test_create_node_wired_question_new_start(multi_edge_graph: QNRGraph):
    data = {
        "kind": "question",
        "node_id": "q_new_entry",
        "question_text": "New intake",
        "question_type": "radio",
        "options": ["Go", "Stop"],
        "help_text": None,
        "required": True,
        "question_wiring": "new_start",
        "predecessor_ids": [],
        "incoming_edge_condition": None,
    }
    g = apply_operation(multi_edge_graph, "create_node_wired", data)
    entries = g.get_entry_nodes()
    assert len(entries) == 1
    assert entries[0].id == "q_new_entry"
    assert any(e.source == "q_new_entry" and e.target == "q1" and e.condition is None for e in g.edges)


def test_create_node_wired_conclusion_conditional(multi_edge_graph: QNRGraph):
    data = {
        "kind": "conclusion",
        "node_id": "conclusion_c",
        "title": "Path C",
        "summary": "Chose C",
        "recommendations": [],
        "severity": "info",
        "conclusion_edges": [{"source": "q1", "condition": "C"}],
    }
    g = apply_operation(multi_edge_graph, "create_node_wired", data)
    assert any(n.id == "conclusion_c" for n in g.nodes)
    assert any(
        e.source == "q1" and e.target == "conclusion_c" and e.condition == "C" for e in g.edges
    )


def test_create_node_wired_rejects_conclusion_on_empty(empty_graph: QNRGraph):
    data = {
        "kind": "conclusion",
        "node_id": "c1",
        "title": "Lonely",
        "summary": "No questions",
        "recommendations": [],
        "severity": "info",
        "conclusion_edges": [],
    }
    with pytest.raises(ValueError, match="at least one question"):
        apply_operation(empty_graph, "create_node_wired", data)
