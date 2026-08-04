"""Vacuous-premise consistency gate — red→green fixtures (A-φ, A-E, A-attrib, Collapse, E, F)."""

from __future__ import annotations

import pytest
from z3 import Bool, Not, sat, unsat

from smeme.decision_tree.models import (
    ConclusionData,
    GraphEdge,
    GraphNode,
    DTGraph,
    DTGraphMetadata,
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
from smeme.reasoning.runtime.assumptions import assumptions_from_lists
from smeme.reasoning.runtime.canonical_facts import CanonicalFactRecord
from smeme.reasoning.runtime.consistency_gate import (
    ConsequenceQueryResult,
    PremiseGateResult,
    PremiseInvariantError,
    SatValidationRecord,
    TargetDomainError,
    assert_sat_t_established,
    assert_literal_subconjunction,
    check_premise_consistency,
    match_sat_validation_record,
)
from smeme.reasoning.runtime.counterfactual import (
    entails_target,
    find_repairs_for_target,
    possible_target,
)
from smeme.reasoning.runtime.ingest_envelope import ParsedIngestEnvelope
from smeme.reasoning.theory.z3_symbols import radio_option_symbol_name
from smeme.reasoning.runtime.evaluate import evaluate_with_canonical_facts
from smeme.reasoning.runtime.report_builder import build_evaluation_report
from smeme.reasoning.runtime.schemas import EvidenceConfidence
from smeme.reasoning.theory.compile_to_z3 import compile_ir_to_z3

_Q = IRQuestionShape(qtype="radio", options=("Yes", "No"))


def _pure_chain_ir() -> IR:
    """entry Q1 → ancestor Q2 → descendant C_desc (single incoming route)."""
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="Q2", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C_desc", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(
            IREdge(source="Q1", target="Q2", guard_id="g1"),
            IREdge(source="Q2", target="C_desc", guard_id="g2"),
        ),
        guards=(Guard(id="g1", expr="Yes"), Guard(id="g2", expr="Yes")),
    )


def _assert_no_alt_route(ir: IR, descendant: str, required_ancestor: str) -> None:
    incoming = [e for e in ir.edges if e.target == descendant]
    assert len(incoming) == 1, "descendant must have exactly one incoming edge"
    assert incoming[0].source == required_ancestor


def _entry_radio_ir() -> IR:
    return IR(
        format_version=IR_FORMAT_VERSION,
        nodes=(
            IRNode(id="Q1", kind=IRNodeKind.QUESTION, question=_Q),
            IRNode(id="C_yes", kind=IRNodeKind.CONCLUSION, question=None),
        ),
        edges=(IREdge(source="Q1", target="C_yes", guard_id="gy"),),
        guards=(Guard(id="gy", expr="Yes"),),
    )


def _dual_true_q1() -> list[CanonicalFactRecord]:
    return [
        CanonicalFactRecord(
            kind="radio",
            question_id="Q1",
            value=True,
            confidence=EvidenceConfidence.EXPLICIT,
            option_label="Yes",
        ),
        CanonicalFactRecord(
            kind="radio",
            question_id="Q1",
            value=True,
            confidence=EvidenceConfidence.EXPLICIT,
            option_label="No",
        ),
    ]


def _entry_graph() -> DTGraph:
    return DTGraph(
        nodes=[
            GraphNode(
                id="Q1",
                type="question",
                data=QuestionData(text="Q?", type="radio", options=["Yes", "No"]),
            ),
            GraphNode(
                id="C_yes",
                type="conclusion",
                data=ConclusionData(title="Yes", summary=""),
            ),
        ],
        edges=[GraphEdge(source="Q1", target="C_yes", condition="Yes")],
        metadata=DTGraphMetadata(title="entry"),
    )


def test_a_phi_inconsistent_not_vacuous_yes_or_false_impossible() -> None:
    """A-φ: force descendant + forbid required ancestor → inconsistent (both helpers)."""
    ir = _pure_chain_ir()
    assert validate_ir(ir).valid
    _assert_no_alt_route(ir, "C_desc", "Q2")
    phi = assumptions_from_lists(
        force_reachable_ids=["C_desc"],
        force_unreachable_ids=["Q2"],
    )
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    ent = entails_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_desc",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        assumptions=phi,
    )
    pos = possible_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_desc",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        assumptions=phi,
    )
    assert ent.status == "inconsistent"
    assert ent.cause == "assumptions_inconsistent"
    assert pos.status == "inconsistent"
    assert pos.cause == "assumptions_inconsistent"


def test_a_e_dual_true_radio_answers_inconsistent() -> None:
    """A-E: entry radio with both option atoms true → answers_inconsistent."""
    ir = _entry_radio_ir()
    assert validate_ir(ir).valid
    dual = _dual_true_q1()
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    ent = entails_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_yes",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        facts=dual,
    )
    pos = possible_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_yes",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        facts=dual,
    )
    assert ent.status == "inconsistent"
    assert ent.cause == "answers_inconsistent"
    assert pos.status == "inconsistent"
    assert pos.cause == "answers_inconsistent"


def test_a_attrib_phi_present_be_unsat_is_answers_inconsistent() -> None:
    """A-attrib (defect 3): nonempty φ + independently UNSAT B_E → answers_inconsistent.

    Wrong attribution would report assumptions_inconsistent.
    """
    ir = _entry_radio_ir()
    dual = _dual_true_q1()
    phi = assumptions_from_lists(force_reachable_ids=["Q1"])  # redundant; φ nonempty
    ev, _ = evaluate_with_canonical_facts(ir, dual, skip_ir_validation=True, assumptions=phi)
    assert ev.status == "UNSAT"
    assert ev.explanation.get("reason") == "z3_unsat"
    report = build_evaluation_report(
        graph=_entry_graph(),
        envelope=ParsedIngestEnvelope(answers={}, evidence_items=[], evidence_refs={}),
        eval_result=ev,
    )
    assert report["result_kind"] == "answers_inconsistent"


def test_e_inconsistent_not_impossible() -> None:
    """Test E: possibility on inconsistent base → inconsistent, never impossible."""
    ir = _pure_chain_ir()
    phi = assumptions_from_lists(
        force_reachable_ids=["C_desc"],
        force_unreachable_ids=["Q2"],
    )
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    pos = possible_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_desc",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        assumptions=phi,
    )
    assert pos.status == "inconsistent"
    assert pos.status != "impossible"


def test_possible_affirmative_one_solver_call() -> None:
    """CHANGE 1: possible on consistent base uses exactly one consistency-relevant call."""
    ir = _entry_radio_ir()
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    pos = possible_target(
        solver,
        sym["nodes"],
        ir,
        {"Q1": "Yes"},
        "C_yes",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
    )
    assert pos.status == "possible"
    assert sat_calls[0] == 1
    assert pos.sat_calls_delta == 1


def test_f_unknown_target_domain_error_both_helpers() -> None:
    ir = _entry_radio_ir()
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    with pytest.raises(TargetDomainError) as ent_exc:
        entails_target(
            solver,
            sym["nodes"],
            ir,
            {"Q1": "Yes"},
            "NOPE",
            sat_calls=sat_calls,
            max_sat_calls=100,
            timeout_ms=5000,
        )
    assert ent_exc.value.code == "invalid_target_id"
    assert sat_calls[0] == 0
    with pytest.raises(TargetDomainError) as pos_exc:
        possible_target(
            solver,
            sym["nodes"],
            ir,
            {"Q1": "Yes"},
            "NOPE",
            sat_calls=sat_calls,
            max_sat_calls=100,
            timeout_ms=5000,
        )
    assert pos_exc.value.code == "invalid_target_id"
    assert sat_calls[0] == 0


def test_j_bool_coercion_raises() -> None:
    r = PremiseGateResult(status="consistent")
    with pytest.raises(TypeError):
        bool(r)


def test_deploy_identity_mismatch_refuses() -> None:
    deployed = SatValidationRecord("a" * 64, 3, "1.0.0")
    current = SatValidationRecord("b" * 64, 3, "1.0.0")
    assert match_sat_validation_record(deployed=deployed, current=current) == "mismatch"
    with pytest.raises(PremiseInvariantError, match="identity mismatch"):
        assert_sat_t_established(
            deployed_record=deployed,
            current_identity=current,
            in_process_unpublished=False,
        )


def test_i_guarded_exactly_one_only_applies_when_question_reachable() -> None:
    """Test I: radio PbEq is guarded by reach(Q2), not globally asserted."""
    ir = _pure_chain_ir()
    solver, sym = compile_ir_to_z3(ir)
    yes = Bool(radio_option_symbol_name("Q2", "Yes"), ctx=solver.ctx)
    no = Bool(radio_option_symbol_name("Q2", "No"), ctx=solver.ctx)

    solver.push()
    solver.add(Not(sym["nodes"]["Q2"]), yes, no)
    assert solver.check() == sat
    solver.pop()

    solver.push()
    solver.add(sym["nodes"]["Q2"], yes, no)
    assert solver.check() == unsat
    solver.pop()


def test_l_budget_precedes_any_solver_call() -> None:
    """Test L: exhausted budget is reported before a consistency check."""
    solver, sym = compile_ir_to_z3(_entry_radio_ir())
    sat_calls = [0]
    result = check_premise_consistency(
        solver,
        sym["nodes"],
        _entry_radio_ir(),
        sat_calls=sat_calls,
        max_sat_calls=0,
        timeout_ms=5000,
    )
    assert result.status == "budget"
    assert result.sat_calls_delta == 0
    assert sat_calls == [0]


def test_decisive_support_lit_invariant_fails_loudly() -> None:
    """The Lit(S)⊆Lit(E) invariant must not disappear under -O."""
    with pytest.raises(PremiseInvariantError, match="Lit\\(S\\)"):
        assert_literal_subconjunction({"Q2": "Yes"}, {"Q1": "Yes"})


def test_entailment_repair_force_kills_inconsistent_candidate(monkeypatch) -> None:
    """An inconsistent entailing candidate is discarded, never added to plans[]."""
    import smeme.reasoning.runtime.counterfactual as counterfactual_runtime

    ir = _entry_radio_ir()
    env = ParsedIngestEnvelope(answers={"Q1": "No"}, evidence_items=[], evidence_refs={})
    calls = [0]

    def fake_entails(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return ConsequenceQueryResult(status="not_entailed")
        return ConsequenceQueryResult(
            status="inconsistent", cause="answers_inconsistent"
        )

    monkeypatch.setattr(counterfactual_runtime, "entails_target", fake_entails)
    result = find_repairs_for_target(
        ir,
        _entry_graph(),
        base_norm={"Q1": "No"},
        base_envelope=env,
        target_conclusion_id="C_yes",
        max_changes=1,
        top_k=1,
    )
    assert calls[0] >= 2
    assert result.plans == []


def test_collapse_phi_empty_reuses_without_extra_phi_check() -> None:
    """Collapse-φ: empty φ → no assumptions path; consistent answers entail."""
    ir = _entry_radio_ir()
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    ent = entails_target(
        solver,
        sym["nodes"],
        ir,
        {"Q1": "Yes"},
        "C_yes",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        assumptions=assumptions_from_lists(),
    )
    assert ent.status == "entailed"
    # Gate: sat_t_established + SAT(T∧E) + query = 2 calls when E nonempty, φ empty.
    assert sat_calls[0] == 2


def test_collapse_e_empty_nonempty_phi() -> None:
    """Collapse-E: empty E + nonempty φ → SAT(T∧φ); cause assumptions when UNSAT."""
    ir = _pure_chain_ir()
    phi = assumptions_from_lists(
        force_reachable_ids=["C_desc"],
        force_unreachable_ids=["Q2"],
    )
    solver, sym = compile_ir_to_z3(ir)
    sat_calls = [0]
    ent = entails_target(
        solver,
        sym["nodes"],
        ir,
        {},
        "C_desc",
        sat_calls=sat_calls,
        max_sat_calls=100,
        timeout_ms=5000,
        assumptions=phi,
    )
    assert ent.status == "inconsistent"
    assert ent.cause == "assumptions_inconsistent"
