"""Evaluation report builder (product memo, no Z3 vocabulary)."""

from __future__ import annotations

from smeme.qnr.models import ConclusionData, GraphNode, DTGraph, QNRMetadata, QuestionData
from smeme.reasoning.runtime.evaluate import EvaluationResult
from smeme.reasoning.runtime.ingest_envelope import ParsedIngestEnvelope
from smeme.reasoning.runtime.report_builder import build_evaluation_report


def _graph() -> DTGraph:
    return DTGraph(
        metadata=QNRMetadata(title="Test QNR", description=""),
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Is the property a rental?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="c_yes",
                type="conclusion",
                data=ConclusionData(
                    title="Treat as rental income",
                    summary="Rental use triggers reporting obligations.",
                    recommendations=["File Schedule E"],
                ),
            ),
            GraphNode(
                id="c_no",
                type="conclusion",
                data=ConclusionData(title="Personal use", summary="No rental reporting required."),
            ),
        ],
        edges=[],
    )


def _branching_graph() -> DTGraph:
    return DTGraph(
        metadata=QNRMetadata(title="Branching QNR", description=""),
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(
                    text="Is the taxpayer a foreign national?",
                    type="radio",
                    options=["Yes", "No"],
                ),
            ),
            GraphNode(
                id="q2",
                type="question",
                data=QuestionData(
                    text="Is the property held for business use?",
                    type="radio",
                    options=["Business", "Personal"],
                ),
            ),
            GraphNode(
                id="q3",
                type="question",
                data=QuestionData(
                    text="Does the income constitute ECI?",
                    type="radio",
                    options=["Yes", "No"],
                ),
            ),
            GraphNode(
                id="q4",
                type="question",
                data=QuestionData(
                    text="Was the property rented more than 14 days?",
                    type="radio",
                    options=["Yes", "No"],
                ),
            ),
            GraphNode(
                id="c_personal",
                type="conclusion",
                data=ConclusionData(
                    title="Personal-use property (no ECI)",
                    summary="Treat as personal-use property without ECI on this path.",
                ),
            ),
            GraphNode(
                id="c_rental",
                type="conclusion",
                data=ConclusionData(
                    title="Rental reporting required",
                    summary="Rental activity may trigger reporting obligations.",
                ),
            ),
        ],
        edges=[],
    )


def test_report_concluded_with_reasoning_path_and_evidence() -> None:
    envelope = ParsedIngestEnvelope(
        answers={"q1": "Yes"},
        evidence_items=[
            {
                "id": "e1",
                "title": "Call transcript",
                "locator": "/data/04-call.txt",
                "locator_kind": "file",
                "excerpt": "used as rental",
            }
        ],
        evidence_refs={"q1": ["e1"]},
    )
    eval_result = EvaluationResult(
        status="SAT_UNIQUE",
        true_conclusion_id="c_yes",
        explanation={"true_conclusions": ["c_yes"], "triggered_edges": ["q1->c_yes"]},
        triggered_edges=["q1->c_yes"],
    )
    report = build_evaluation_report(graph=_graph(), envelope=envelope, eval_result=eval_result)
    assert report["result_kind"] == "concluded"
    assert report["headline"] == "Treat as rental income"
    assert "rental" in report["brief_memo"].lower()
    assert report["reasoning_path"][0]["kind"] == "answered"
    assert report["reasoning_path"][0]["supporting_evidence"][0]["locator"] == "/data/04-call.txt"
    assert report["candidates"][0]["status"] == "selected"
    assert "outcome" not in report
    assert "SAT" not in report["brief_memo"]
    assert "\n\n" in report["brief_memo"]
    assert 'answering Yes on "Is the property a rental?"' in report["brief_memo"]


def test_report_concluded_routing_bridge_and_skipped_downstream_question() -> None:
    envelope = ParsedIngestEnvelope(
        answers={"q1": "Yes", "q2": "Business", "q3": "No"},
        evidence_items=[
            {"id": "e1", "title": "Intake", "locator": "/intake", "locator_kind": "file", "excerpt": "FN"},
            {"id": "e2", "title": "Notes", "locator": "/notes", "locator_kind": "file", "excerpt": "biz"},
            {"id": "e3", "title": "Call", "locator": "/call", "locator_kind": "file", "excerpt": "no eci"},
        ],
        evidence_refs={"q1": ["e1"], "q2": ["e2"], "q3": ["e3"]},
    )
    eval_result = EvaluationResult(
        status="SAT_UNIQUE",
        true_conclusion_id="c_personal",
        explanation={
            "true_conclusions": ["c_personal"],
            "triggered_edges": ["q1->q2", "q2->q3", "q3->c_personal"],
        },
        triggered_edges=["q1->q2", "q2->q3", "q3->c_personal"],
    )
    report = build_evaluation_report(
        graph=_branching_graph(),
        envelope=envelope,
        eval_result=eval_result,
    )
    memo = report["brief_memo"]
    assert report["headline"] == "Personal-use property (no ECI)"
    assert memo.startswith("Personal-use property (no ECI)\n\n")
    assert "Treat as personal-use property without ECI on this path." in memo
    assert 'This outcome follows from answering No on "Does the income constitute ECI?"' in memo
    assert '"Was the property rented more than 14 days?" was not reached on this path.' in memo
    assert "q3" not in memo
    assert "q4" not in memo


def test_report_multiple_outcomes_includes_routing_bridge() -> None:
    envelope = ParsedIngestEnvelope(
        answers={"q1": "Yes", "q2": "Business"},
        evidence_items=[
            {"id": "e1", "title": "A", "locator": "/a", "locator_kind": "file", "excerpt": "a"},
            {"id": "e2", "title": "B", "locator": "/b", "locator_kind": "file", "excerpt": "b"},
        ],
        evidence_refs={"q1": ["e1"], "q2": ["e2"]},
    )
    eval_result = EvaluationResult(
        status="SAT_AMBIGUOUS",
        true_conclusion_id=None,
        explanation={
            "true_conclusions": ["c_personal", "c_rental"],
            "triggered_edges": ["q1->q2"],
        },
        triggered_edges=["q1->q2"],
    )
    report = build_evaluation_report(
        graph=_branching_graph(),
        envelope=envelope,
        eval_result=eval_result,
    )
    memo = report["brief_memo"]
    assert report["result_kind"] == "multiple_outcomes_possible"
    assert 'This path stops after answering Business on "Is the property held for business use?"' in memo
    assert "These questions were not reached on this path:" in memo
    assert '"Does the income constitute ECI?"' in memo
    assert '"Was the property rented more than 14 days?"' in memo
