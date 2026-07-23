"""Unit tests for counterfactual reasoning kernel (what_if + how_to_reach)."""

from __future__ import annotations

import pytest

from smeme.qnr.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    QNRMetadata,
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
from smeme.reasoning.runtime.assumptions import AssumptionsError, assumptions_from_lists
from smeme.reasoning.runtime.counterfactual import (
    CounterfactualError,
    build_what_if_delta,
    find_repairs_for_target,
    how_to_reach_to_wire,
    merge_normalized_answers,
    normalized_from_answers,
    run_what_if,
)
from smeme.reasoning.runtime.ingest_envelope import ParsedIngestEnvelope

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
        metadata=QNRMetadata(title="Test"),
    )


def test_merge_normalized_override_wins() -> None:
    base = {"Q1": "Yes"}
    override = {"Q1": "No", "Q2": "Maybe"}
    merged = merge_normalized_answers(base, override)
    assert merged == {"Q1": "No", "Q2": "Maybe"}


def test_build_what_if_delta_outcome_changed_excludes_headline_only() -> None:
    before = {
        "result_kind": "concluded",
        "headline": "Headline A",
        "candidates": [{"title": "Eligible", "status": "selected"}],
        "reasoning_path": [{"step": 1}],
    }
    after = {
        "result_kind": "concluded",
        "headline": "Headline B",
        "candidates": [{"title": "Eligible", "status": "selected"}],
        "reasoning_path": [{"step": 1}],
    }
    delta = build_what_if_delta(
        base_norm={"Q1": "Yes"},
        merged_norm={"Q1": "Yes"},
        before_report=before,
        after_report=after,
    )
    assert delta["headline_changed"] is True
    assert delta["outcome_changed"] is False


def test_run_what_if_changes_outcome() -> None:
    ir = _exclusive_radio_ir()
    assert validate_ir(ir).valid
    graph = _exclusive_radio_graph()
    result = run_what_if(
        ir,
        graph,
        base_payload={"Q1": "No"},
        override_payload={"Q1": "Yes"},
    )
    assert result.before_report["result_kind"] == "concluded"
    assert result.after_report["result_kind"] == "concluded"
    assert result.delta["changed_answers"] == [
        {"question_id": "Q1", "before": "No", "after": "Yes"}
    ]
    assert result.delta["outcome_changed"] is True
    assert result.assumptions.is_empty()


def test_run_what_if_shared_assumptions_apply_to_both_passes() -> None:
    ir = _exclusive_radio_ir()
    assert validate_ir(ir).valid
    graph = _exclusive_radio_graph()
    # Force the Yes conclusion reachable while answering No → inconsistent on both worlds.
    phi = assumptions_from_lists(force_reachable_ids=["C_yes"])
    result = run_what_if(
        ir,
        graph,
        base_payload={"Q1": "No"},
        override_payload={"Q1": "No"},
        assumptions=phi,
    )
    assert result.before_report["result_kind"] == "assumptions_inconsistent"
    assert result.after_report["result_kind"] == "assumptions_inconsistent"
    assert result.assumptions.force_reachable == frozenset({"C_yes"})
    assert result.delta["outcome_changed"] is False


def test_run_what_if_invalid_assumption_node() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    phi = assumptions_from_lists(force_unreachable_ids=["NOPE"])
    with pytest.raises(AssumptionsError) as exc_info:
        run_what_if(
            ir,
            graph,
            base_payload={"Q1": "Yes"},
            override_payload={"Q1": "No"},
            assumptions=phi,
        )
    assert exc_info.value.code == "invalid_assumption_node_id"


def test_find_repairs_already_reachable() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "Yes"}, evidence_items=[], evidence_refs={})
    base = normalized_from_answers({"Q1": "Yes"})
    result = find_repairs_for_target(
        ir,
        graph,
        base_norm=base,
        base_envelope=env,
        target_conclusion_id="C_yes",
    )
    assert result.already_reachable is True
    assert result.satisfiable is True
    assert result.minimal_change_count == 0
    assert result.plans == []


def test_find_repairs_single_edit_to_target() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    base = normalized_from_answers({"Q1": "No"})
    result = find_repairs_for_target(
        ir,
        graph,
        base_norm=base,
        base_envelope=env,
        target_conclusion_id="C_yes",
        max_changes=1,
        top_k=1,
    )
    assert result.satisfiable is True
    assert result.already_reachable is False
    assert len(result.plans) == 1
    assert result.plans[0].changed_answers == {"Q1": "Yes"}
    assert result.plans[0].preview_target_reached is True


def test_invalid_target_conclusion_id() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    with pytest.raises(CounterfactualError) as exc_info:
        find_repairs_for_target(
            ir,
            graph,
            base_norm={"Q1": "No"},
            base_envelope=env,
            target_conclusion_id="Q1",
        )
    assert exc_info.value.code == "invalid_target_conclusion_id"


def test_invalid_locked_question_id() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    with pytest.raises(CounterfactualError) as exc_info:
        find_repairs_for_target(
            ir,
            graph,
            base_norm={"Q1": "No"},
            base_envelope=env,
            target_conclusion_id="C_yes",
            locked_question_ids=["UNKNOWN"],
        )
    assert exc_info.value.code == "invalid_locked_question_id"


def test_invalid_reach_mode() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    with pytest.raises(CounterfactualError) as exc_info:
        find_repairs_for_target(
            ir,
            graph,
            base_norm={"Q1": "No"},
            base_envelope=env,
            target_conclusion_id="C_yes",
            reach_mode="maybe",
        )
    assert exc_info.value.code == "invalid_reach_mode"


def _partial_chain_ir() -> IR:
    """Q1→Q2→C_yes / Q1→C_no / Q2→C_alt — partial Q1=Yes leaves C_yes possible but not forced."""
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="C_yes", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C_no", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="C_alt", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g_q1y"),
            IREdge(source="Q1", target="C_no", guard_id="g_q1n"),
            IREdge(source="Q2", target="C_yes", guard_id="g_q2y"),
            IREdge(source="Q2", target="C_alt", guard_id="g_q2n"),
        ),
        guards=(
            Guard(id="g_q1y", expr="Yes"),
            Guard(id="g_q1n", expr="No"),
            Guard(id="g_q2y", expr="Yes"),
            Guard(id="g_q2n", expr="No"),
        ),
    )


def _partial_chain_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="Q1",
                type="question",
                data=QuestionData(text="Gate?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="Q2",
                type="question",
                data=QuestionData(text="Detail?", type="radio", options=["Yes", "No"]),
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
            GraphNode(
                id="C_alt",
                type="conclusion",
                data=ConclusionData(title="Alternate", summary="Alt path"),
            ),
        ],
        edges=[
            GraphEdge(source="Q1", target="Q2", condition="Yes"),
            GraphEdge(source="Q1", target="C_no", condition="No"),
            GraphEdge(source="Q2", target="C_yes", condition="Yes"),
            GraphEdge(source="Q2", target="C_alt", condition="No"),
        ],
        metadata=QNRMetadata(title="Partial"),
    )


def test_possible_vs_entailed_already_reachable_partial_answers() -> None:
    ir = _partial_chain_ir()
    assert validate_ir(ir).valid
    graph = _partial_chain_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "Yes"}, evidence_items=[], evidence_refs={})
    base = normalized_from_answers({"Q1": "Yes"})

    entailed = find_repairs_for_target(
        ir,
        graph,
        base_norm=base,
        base_envelope=env,
        target_conclusion_id="C_yes",
        reach_mode="entailed",
        max_changes=2,
    )
    assert entailed.already_reachable is False
    assert entailed.reach_mode == "entailed"

    possible = find_repairs_for_target(
        ir,
        graph,
        base_norm=base,
        base_envelope=env,
        target_conclusion_id="C_yes",
        reach_mode="possible",
        max_changes=2,
    )
    assert possible.already_reachable is True
    assert possible.satisfiable is True
    assert possible.minimal_change_count == 0
    assert possible.plans == []
    assert possible.reach_mode == "possible"


def test_how_to_reach_wire_includes_reach_mode() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "Yes"}, evidence_items=[], evidence_refs={})
    result = find_repairs_for_target(
        ir,
        graph,
        base_norm={"Q1": "Yes"},
        base_envelope=env,
        target_conclusion_id="C_yes",
    )
    wire = how_to_reach_to_wire(result)
    assert wire["reach_mode"] == "entailed"
    assert wire["already_reachable"] is True


def test_target_not_reachable_under_locks_preflight() -> None:
    ir = _exclusive_radio_ir()
    graph = _exclusive_radio_graph()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    with pytest.raises(CounterfactualError) as exc_info:
        find_repairs_for_target(
            ir,
            graph,
            base_norm={"Q1": "No"},
            base_envelope=env,
            target_conclusion_id="C_yes",
            locked_question_ids=["Q1"],
            max_changes=3,
        )
    assert exc_info.value.code == "target_not_reachable_under_locks"
