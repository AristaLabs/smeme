"""E0: golden / characterization for ``raw_answers`` → evidence items, facts, assertion plan (CEVI A.1)."""

from __future__ import annotations

import pytest

from smeme.reasoning.cevi.fact_projection import (
    UnmappableFactAtomError,
    apply_canonical_facts_to_solver,
    solver_symbol_for_canonical_fact,
)
from smeme.reasoning.ir.types import (
    DEFAULT_GUARD_EXPR,
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
    CanonicalFactRecord,
    raw_answers_to_canonical_facts,
    validate_fact_atom_id,
)
from smeme.reasoning.runtime.evaluate import _apply_user_facts, evaluate_reasoning
from smeme.reasoning.runtime.input_validation import (
    ReasoningInputValidationError,
    validate_raw_answers_for_ir,
)
from smeme.reasoning.runtime.schemas import EvidenceConfidence
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name

_Q_RADIO = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _exclusive_radio_ir() -> IR:
    """Single radio question → two conclusions (matches ``test_analyze._exclusive_conclusions_ir``)."""
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


def _two_radio_chain_ir() -> IR:
    """Two radio questions in ``ir.nodes`` order (default guards)."""
    q2 = IRQuestionShape(qtype="radio", options=("X", "Y"))
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q_radio", kind=IRNodeKind.QUESTION, question=_Q_RADIO),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=q2),
            IRNode(id="C1", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q_radio", target="Q2", guard_id="g0"),
            IREdge(source="Q2", target="C1", guard_id="g1"),
        ),
        guards=(
            Guard(id="g0", expr=DEFAULT_GUARD_EXPR),
            Guard(id="g1", expr=DEFAULT_GUARD_EXPR),
        ),
    )


def _collect_plan(
    ir: IR, raw: dict[str, str | list[str] | None]
) -> tuple[list[dict], list[dict], list[tuple[str, bool]]]:
    assert validate_ir(ir).valid
    solver, _ = compile_ir_to_z3(ir)
    items, facts = _apply_user_facts(solver, ir, raw, z3_ctx=solver.ctx)
    return (
        [i.model_dump(mode="json") for i in items],
        [f.model_dump(mode="json") for f in facts],
        [(f.atom, f.value) for f in facts],
    )


def test_radio_match_golden():
    ir = _exclusive_radio_ir()
    sym_yes = radio_option_symbol_name("Q1", "Yes")
    sym_no = radio_option_symbol_name("Q1", "No")
    ev, fs, plan = _collect_plan(ir, {"Q1": "Yes"})
    assert plan == [(sym_yes, True), (sym_no, False)]
    assert [e["confidence"] for e in ev] == ["explicit", "explicit"]
    assert ev[0]["source_span"] == "yes"


def test_radio_no_match_rejected_at_ingest():
    ir = _exclusive_radio_ir()
    with pytest.raises(ReasoningInputValidationError, match="does not match any option"):
        validate_raw_answers_for_ir(ir, {"Q1": "maybe"})


def test_radio_none_absent_golden():
    ir = _exclusive_radio_ir()
    ev, _, plan = _collect_plan(ir, {"Q1": None})
    assert plan == []
    assert [e["confidence"] for e in ev] == ["absent", "absent"]


def test_partial_session_unanswered_question_not_asserted():
    ir = _two_radio_chain_ir()
    sym_yes = radio_option_symbol_name("Q_radio", "Yes")
    sym_no = radio_option_symbol_name("Q_radio", "No")
    _, _, plan = _collect_plan(ir, {"Q_radio": "Yes"})
    assert plan == [(sym_yes, True), (sym_no, False)]


def test_partial_session_evaluate_sat():
    ir = _two_radio_chain_ir()
    res, _ = evaluate_reasoning(ir, raw_answers={"Q_radio": "Yes"})
    assert res.status != "UNSAT"


def test_multi_question_ordering_matches_ir_nodes_walk():
    ir = _two_radio_chain_ir()
    assert validate_ir(ir).valid
    r_yes = radio_option_symbol_name("Q_radio", "Yes")
    r_no = radio_option_symbol_name("Q_radio", "No")
    x_sym = radio_option_symbol_name("Q2", "X")
    y_sym = radio_option_symbol_name("Q2", "Y")
    raw = {"Q_radio": "Yes", "Q2": "X"}
    _, _, plan = _collect_plan(ir, raw)
    assert plan == [
        (r_yes, True),
        (r_no, False),
        (x_sym, True),
        (y_sym, False),
    ]


def test_evaluate_reasoning_end_to_end_unchanged_shape():
    ir = _exclusive_radio_ir()
    res, audit = evaluate_reasoning(ir, raw_answers={"Q1": "Yes"})
    assert res.status in ("SAT_UNIQUE", "SAT_AMBIGUOUS", "UNSAT", "UNDER_DETERMINED")
    assert isinstance(audit.evidence_items, list)
    assert isinstance(audit.final_facts, list)


def test_stage_a_fact_atom_ids_validate():
    ir = _exclusive_radio_ir()
    facts = raw_answers_to_canonical_facts(ir, {"Q1": "Yes"})
    for rec in facts:
        validate_fact_atom_id(rec.fact_atom_id())


def test_radio_fact_atom_id_shape():
    rec = CanonicalFactRecord(
        kind="radio",
        question_id="Q1",
        value=True,
        confidence=EvidenceConfidence.EXPLICIT,
        source_span="yes",
        option_label="Yes",
    )
    assert rec.fact_atom_id() == "fact:radio:Q1:Yes"
    assert solver_symbol_for_canonical_fact(_exclusive_radio_ir(), rec) == radio_option_symbol_name(
        "Q1", "Yes"
    )


def test_projection_rejects_unknown_radio_option():
    ir = _exclusive_radio_ir()
    bad = CanonicalFactRecord(
        kind="radio",
        question_id="Q1",
        value=True,
        confidence=EvidenceConfidence.EXPLICIT,
        option_label="Maybe",
        source_span="",
    )
    with pytest.raises(UnmappableFactAtomError):
        solver_symbol_for_canonical_fact(ir, bad)


def test_apply_canonical_facts_matches_apply_user_facts():
    ir = _two_radio_chain_ir()
    raw = {"Q_radio": "No", "Q2": "Y"}
    canonical = raw_answers_to_canonical_facts(ir, raw)
    s1, _ = compile_ir_to_z3(ir)
    items_a, facts_a = _apply_user_facts(s1, ir, raw, z3_ctx=s1.ctx)
    s2, _ = compile_ir_to_z3(ir)
    items_b, facts_b = apply_canonical_facts_to_solver(s2, ir, canonical, z3_ctx=s2.ctx)
    assert [i.model_dump(mode="json") for i in items_a] == [
        i.model_dump(mode="json") for i in items_b
    ]
    assert [f.model_dump(mode="json") for f in facts_a] == [
        f.model_dump(mode="json") for f in facts_b
    ]
