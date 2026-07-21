"""Unit tests for conclusions catalog wire builder."""

from __future__ import annotations

from uuid import UUID

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    QNRGraph,
    QNRMetadata,
    QuestionData,
)
from smeme.reasoning.qnr_bridge import compile_qnr_to_ir
from smeme.reasoning.runtime.analyze import enumerate_conclusion_sat_queries
from smeme.reasoning.runtime.conclusions_catalog import build_conclusions_catalog_wire

_QNR_ID = UUID("00000000-0000-4000-8000-000000000001")


def _exclusive_two_outcome_graph() -> QNRGraph:
    return QNRGraph(
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
                data=ConclusionData(title="Out A", summary="Summary A", severity="warning"),
            ),
            GraphNode(
                id="c2",
                type="conclusion",
                data=ConclusionData(title="Out B", summary="Summary B"),
            ),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=QNRMetadata(title="v"),
    )


def test_build_conclusions_catalog_wire_lists_titles_and_reachability() -> None:
    graph = _exclusive_two_outcome_graph()
    ir = compile_qnr_to_ir(graph)
    enumeration = enumerate_conclusion_sat_queries(ir, validate=False)

    wire = build_conclusions_catalog_wire(
        qnr_id=_QNR_ID,
        graph=graph,
        enumeration=enumeration,
    )

    assert wire["qnr_id"] == str(_QNR_ID).lower()
    assert wire["workflow_rules_consistent"] is True
    assert wire["count"] == 2
    assert wire["reachable_count"] == 2
    assert "hint" not in wire

    by_id = {row["conclusion_id"]: row for row in wire["conclusions"]}
    assert by_id["c1"]["conclusion_title"] == "Out A"
    assert by_id["c1"]["summary"] == "Summary A"
    assert by_id["c1"]["severity"] == "warning"
    assert by_id["c1"]["reachable"] is True
    assert by_id["c2"]["conclusion_title"] == "Out B"
    assert by_id["c2"]["reachable"] is True
