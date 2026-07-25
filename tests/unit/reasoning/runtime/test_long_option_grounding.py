"""Regression: long option labels must ground and evaluate (not internal_error).

Confound from 2026-07-25 feedback: the only >120-char option in a fixture was also
on a parallel edge. These tests separate length from topology.
"""

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
from smeme.reasoning.runtime.canonical_facts import (
    SOURCE_SPAN_MAX_LEN,
    raw_answers_to_canonical_facts,
)
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.ingest_envelope import prepare_evaluate_ingest
from smeme.reasoning.runtime.input_validation import (
    MAX_RADIO_OR_OPTION_STR_LEN,
    ReasoningInputValidationError,
)
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name

# 130 chars — matches the pay-to-play fixture failure case.
_LONG_OPTION = (
    "Holds a qualifying state or local office while running for federal office, "
    "or is a federal incumbent seeking state or local office"
)
_SHORT_OPTION = "Short route"
_OTHER = "Other"


def _assert_long() -> None:
    assert len(_LONG_OPTION) > SOURCE_SPAN_MAX_LEN


def _ir_parallel_to_same_target() -> IR:
    """Two options route to the same next question (valid convergent factoring)."""
    _assert_long()
    q1 = IRQuestionShape(qtype="radio", options=(_SHORT_OPTION, _LONG_OPTION, _OTHER))
    q2 = IRQuestionShape(qtype="radio", options=("Yes", "No"))
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="q1", kind=IRNodeKind.QUESTION, question=q1),
            IRNode(id="q2", kind=IRNodeKind.QUESTION, question=q2),
            IRNode(id="c1", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="c2", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="q1", target="q2", guard_id="g_short"),
            IREdge(source="q1", target="q2", guard_id="g_long"),
            IREdge(source="q1", target="c2", guard_id="g_other"),
            IREdge(source="q2", target="c1", guard_id="g_yes"),
            IREdge(source="q2", target="c2", guard_id="g_no"),
        ),
        guards=(
            Guard(id="g_short", expr=_SHORT_OPTION),
            Guard(id="g_long", expr=_LONG_OPTION),
            Guard(id="g_other", expr=_OTHER),
            Guard(id="g_yes", expr="Yes"),
            Guard(id="g_no", expr="No"),
        ),
    )


def _ir_long_non_parallel() -> IR:
    """Long option is the sole edge to its target (isolates length from parallelism)."""
    _assert_long()
    q1 = IRQuestionShape(qtype="radio", options=(_SHORT_OPTION, _LONG_OPTION))
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="q1", kind=IRNodeKind.QUESTION, question=q1),
            IRNode(id="c_short", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="c_long", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="q1", target="c_short", guard_id="g_short"),
            IREdge(source="q1", target="c_long", guard_id="g_long"),
        ),
        guards=(
            Guard(id="g_short", expr=_SHORT_OPTION),
            Guard(id="g_long", expr=_LONG_OPTION),
        ),
    )


def test_canonical_facts_truncate_source_span_keep_full_label() -> None:
    ir = _ir_long_non_parallel()
    facts = raw_answers_to_canonical_facts(ir, {"q1": _LONG_OPTION})
    matched = [f for f in facts if f.value]
    assert len(matched) == 1
    rec = matched[0]
    assert rec.option_label == _LONG_OPTION
    assert len(rec.source_span) == SOURCE_SPAN_MAX_LEN
    assert rec.source_span == _LONG_OPTION.strip().lower()[:SOURCE_SPAN_MAX_LEN]


def test_evaluate_long_option_non_parallel() -> None:
    ir = _ir_long_non_parallel()
    assert validate_ir(ir).valid
    res, _ = evaluate_reasoning(ir, raw_answers={"q1": _LONG_OPTION})
    assert res.status == "SAT_UNIQUE"
    assert res.true_conclusion_id == "c_long"
    assert res.triggered_edges == [
        {"source": "q1", "target": "c_long", "guard_id": "g_long"},
    ]


def test_evaluate_long_option_parallel_convergent() -> None:
    ir = _ir_parallel_to_same_target()
    assert validate_ir(ir).valid
    for answer, guard_id in (
        (_SHORT_OPTION, "g_short"),
        (_LONG_OPTION, "g_long"),
    ):
        res, _ = evaluate_reasoning(
            ir,
            raw_answers={"q1": answer, "q2": "Yes"},
        )
        assert res.status == "SAT_UNIQUE", answer
        assert res.true_conclusion_id == "c1", answer
        q1_edges = [e for e in res.triggered_edges if e["source"] == "q1"]
        assert q1_edges == [
            {"source": "q1", "target": "q2", "guard_id": guard_id},
        ], answer


def test_phase1_ingest_grounds_long_option() -> None:
    ir = _ir_long_non_parallel()
    _answers, _env, warnings, harness_next = prepare_evaluate_ingest(
        ir,
        {
            "answers": {"q1": _LONG_OPTION},
            "evidence_items": [{"id": "e1", "excerpt": "cite"}],
            "evidence_refs": {"q1": ["e1"]},
        },
    )
    assert warnings == []
    assert harness_next == "phase_2_ok"


def test_long_similar_option_labels_do_not_collide() -> None:
    """Labels sharing a sanitized 120-char prefix must still evaluate distinctly."""
    prefix = "A" * 121
    opt_a = prefix + "X"
    opt_b = prefix + "Y"
    assert radio_option_symbol_name("q", opt_a) != radio_option_symbol_name("q", opt_b)
    q1 = IRQuestionShape(qtype="radio", options=(opt_a, opt_b))
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="q", kind=IRNodeKind.QUESTION, question=q1),
            IRNode(id="ca", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="cb", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="q", target="ca", guard_id="ga"),
            IREdge(source="q", target="cb", guard_id="gb"),
        ),
        guards=(
            Guard(id="ga", expr=opt_a),
            Guard(id="gb", expr=opt_b),
        ),
    )
    assert validate_ir(ir).valid
    res_a, _ = evaluate_reasoning(ir, raw_answers={"q": opt_a})
    res_b, _ = evaluate_reasoning(ir, raw_answers={"q": opt_b})
    assert res_a.status == "SAT_UNIQUE"
    assert res_a.true_conclusion_id == "ca"
    assert res_b.status == "SAT_UNIQUE"
    assert res_b.true_conclusion_id == "cb"


def test_grounding_error_names_question_and_field() -> None:
    oversized = "Z" * (MAX_RADIO_OR_OPTION_STR_LEN + 1)
    q1 = IRQuestionShape(qtype="radio", options=("Short", oversized))
    ir = IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="q_big", kind=IRNodeKind.QUESTION, question=q1),
            IRNode(id="c1", kind=IRNodeKind.CONCLUSION, question=None),
            IRNode(id="c2", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="q_big", target="c1", guard_id="g1"),
            IREdge(source="q_big", target="c2", guard_id="g2"),
        ),
        guards=(
            Guard(id="g1", expr="Short"),
            Guard(id="g2", expr=oversized),
        ),
    )
    with pytest.raises(ReasoningInputValidationError) as ei:
        evaluate_reasoning(ir, raw_answers={"q_big": "Short"})
    msg = str(ei.value)
    assert "q_big" in msg
    assert "option_label" in msg
    assert "string_too_long" in msg or "2048" in msg
