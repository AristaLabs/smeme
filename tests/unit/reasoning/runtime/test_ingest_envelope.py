"""M0 ingest envelope (provenance), warnings ordering, and hard rejects."""

from __future__ import annotations

import pytest

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
from smeme.reasoning.runtime.ingest_codes import (
    IngestErrorCode,
    IngestWarningCode,
    harness_next_for_ingest,
    sort_warnings,
)
from smeme.reasoning.runtime.ingest_envelope import (
    MAX_EVIDENCE_ITEMS,
    ReasoningIngestError,
    parse_ingest_envelope_dict,
    prepare_evaluate_ingest,
    validate_reasoning_ingest_envelope,
)

_Q = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _simple_ir() -> IR:
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
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


def test_legacy_flat_payload_is_answers_only() -> None:
    env = parse_ingest_envelope_dict({"Q1": "Yes"})
    assert env.answers == {"Q1": "Yes"}
    assert env.evidence_items == []
    assert env.evidence_refs == {}


def test_provenance_envelope_requires_answers_when_evidence_present() -> None:
    with pytest.raises(ReasoningIngestError) as ei:
        parse_ingest_envelope_dict({"evidence_items": [{"id": "a"}]})
    assert ei.value.code == IngestErrorCode.ingest_malformed


def test_dangling_evidence_ref_rejects() -> None:
    with pytest.raises(ReasoningIngestError) as ei:
        parse_ingest_envelope_dict(
            {
                "answers": {"Q1": "Yes"},
                "evidence_items": [{"id": "e1"}],
                "evidence_refs": {"Q1": ["e2"]},
            }
        )
    assert ei.value.code == IngestErrorCode.ingest_dangling_evidence_ref


def test_missing_evidence_ref_warning_sorted_question_ids() -> None:
    ir = _simple_ir()
    assert validate_ir(ir).valid
    env = parse_ingest_envelope_dict({"Q1": "Yes"})
    warnings, hn = validate_reasoning_ingest_envelope(ir, env)
    assert warnings == [
        {"code": str(IngestWarningCode.missing_evidence_ref), "question_ids": ["Q1"]}
    ]
    assert hn == "user_input_needed"


def test_warnings_sorted_by_code_then_question_ids() -> None:
    w = sort_warnings(
        [
            {"code": "z_last", "question_ids": ["b", "a"]},
            {"code": "a_first", "question_ids": ["m", "n"]},
        ]
    )
    assert [x["code"] for x in w] == ["a_first", "z_last"]
    assert w[0]["question_ids"] == ["m", "n"]
    assert w[1]["question_ids"] == ["a", "b"]


def test_harness_next_phase_1_continue_for_mixed_warning_codes() -> None:
    hn = harness_next_for_ingest(
        warnings=[
            {"code": "missing_evidence_ref", "question_ids": ["Q1"]},
            {"code": "future_warn", "question_ids": ["Q2"]},
        ]
    )
    assert hn == "phase_1_continue"


def test_invalid_answer_option_maps_to_ingest_code() -> None:
    from tests.unit.reasoning.runtime.test_evaluate_raw_answers_goldens import _exclusive_radio_ir

    ir = _exclusive_radio_ir()
    with pytest.raises(ReasoningIngestError) as ei:
        prepare_evaluate_ingest(ir, {"Q1": "maybe"})
    assert ei.value.code == IngestErrorCode.ingest_invalid_answer_option


def test_prepare_evaluate_ingest_with_evidence_refs_no_warning() -> None:
    ir = _simple_ir()
    flat, env, warnings, hn = prepare_evaluate_ingest(
        ir,
        {
            "answers": {"Q1": "Yes"},
            "evidence_items": [
                {
                    "id": "e1",
                    "retrieved_at": "2026-05-15T12:00:00Z",
                    "title": "Source A",
                    "locator": "/project/docs/a.txt",
                    "locator_kind": "workspace_path",
                }
            ],
            "evidence_refs": {"Q1": ["e1"]},
        },
    )
    assert flat == {"Q1": "Yes"}
    assert env.evidence_items[0]["title"] == "Source A"
    assert warnings == []
    assert hn == "phase_2_ok"


def test_unknown_question_in_evidence_refs() -> None:
    ir = _simple_ir()
    env = parse_ingest_envelope_dict(
        {
            "answers": {"Q1": "Yes"},
            "evidence_items": [{"id": "e1"}],
            "evidence_refs": {"NOPE": ["e1"]},
        }
    )
    with pytest.raises(ReasoningIngestError) as ei:
        validate_reasoning_ingest_envelope(ir, env)
    assert ei.value.code == IngestErrorCode.ingest_unknown_question_id


def test_evidence_items_cap() -> None:
    items = [{"id": f"id{i}"} for i in range(MAX_EVIDENCE_ITEMS + 1)]
    with pytest.raises(ReasoningIngestError) as ei:
        parse_ingest_envelope_dict({"answers": {"Q1": "Yes"}, "evidence_items": items})
    assert ei.value.code == IngestErrorCode.ingest_cap_exceeded
