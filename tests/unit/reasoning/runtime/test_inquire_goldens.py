"""G1–G9 as ``analyze_inquiry`` entry points. Target goldens; not Appendix B."""

from __future__ import annotations

from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS, assumptions_from_lists
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.input_validation import validate_raw_answers_for_ir
from smeme.reasoning.runtime.inquire import analyze_inquiry, build_extractor_issue
from smeme.reasoning.runtime.inquire.types import InquiryBudget, VerificationKey
from tests.unit.reasoning.runtime.inquire_fixtures import (
    compile_golden,
    fork_g2_graph,
    fork_g8_graph,
    joint_g6_graph,
    sentinel_key,
    xor_g1_graph,
)

_BUDGET = InquiryBudget()


def _admit(ir, raw: dict[str, str]) -> dict[str, str]:
    validate_raw_answers_for_ir(ir, raw)
    return dict(raw)


def _analyze(
    graph,
    raw: dict[str, str],
    *,
    verified: frozenset[VerificationKey] | None = None,
    assumptions=EMPTY_ASSUMPTIONS,
):
    fixture = compile_golden(graph)
    admitted = _admit(fixture.ir, raw) if raw else {}
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        assumptions,
        verified if verified is not None else frozenset(),
        _BUDGET,
        fixture.catalog,
    )
    return fixture, directive


def test_g2_0_acquire_q2_not_verify() -> None:
    """Co-reachable extra conclusion: ACQUIRE q2, not VERIFY a support for c1."""
    _fixture, directive = _analyze(fork_g2_graph(), {"q1": "Yes"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"
    assert directive.stop_reason is None


def test_g2_0_apply_sat_unique_is_not_resolved() -> None:
    """Characterization: Apply may report SAT_UNIQUE while Inquire still ACQUIREs (G2 hole)."""
    fixture = compile_golden(fork_g2_graph())
    res, _audit = evaluate_reasoning(fixture.ir, raw_answers={"q1": "Yes"})
    directive = analyze_inquiry(
        fixture.ir,
        _admit(fixture.ir, {"q1": "Yes"}),
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
    )
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"
    if res.status == "SAT_UNIQUE":
        assert res.true_conclusion_id == "c1"


def test_g8_1_issued_question_is_q2() -> None:
    """G8 graph under G2.0 answers: ACQUIRE q2. Set membership ``q3 ∉ D_1`` is a helper test."""
    _fixture, directive = _analyze(fork_g8_graph(), {"q1": "Yes"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"


def test_g1_1_acquire_q2a() -> None:
    """After ADMIT {q1=0}, sequential demotion: ACQUIRE q2a."""
    _fixture, directive = _analyze(xor_g1_graph(), {"q1": "0"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2a"


def test_g1_2_verify_walk_over_resolving_support() -> None:
    raw = {"q1": "0", "q2a": "0"}
    _fixture, first = _analyze(xor_g1_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"

    _fixture, second = _analyze(xor_g1_graph(), raw, verified=frozenset({sentinel_key("q1", "0")}))
    assert second.action == "VERIFY"
    assert second.question_id == "q2a"

    _fixture, done = _analyze(
        xor_g1_graph(),
        raw,
        verified=frozenset({sentinel_key("q1", "0"), sentinel_key("q2a", "0")}),
    )
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"
    assert done.question_id is None


def test_g3_0_verify_not_entailment_support() -> None:
    """After verifying q1 alone, still VERIFY q2 — decisive_support is not S_R."""
    raw = {"q1": "Yes", "q2": "B"}
    _fixture, first = _analyze(fork_g2_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"

    _fixture, second = _analyze(
        fork_g2_graph(),
        raw,
        verified=frozenset({sentinel_key("q1", "Yes")}),
    )
    assert second.action == "VERIFY"
    assert second.question_id == "q2"
    assert second.stop_reason is None


def test_g5_assumptions_retained_in_support() -> None:
    phi = assumptions_from_lists(force_unreachable_ids=["c2"])
    raw = {"q1": "Yes"}
    _fixture, first = _analyze(fork_g2_graph(), raw, assumptions=phi)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"

    _fixture, done = _analyze(
        fork_g2_graph(),
        raw,
        assumptions=phi,
        verified=frozenset({sentinel_key("q1", "Yes")}),
    )
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"

    _fixture, without_phi = _analyze(fork_g2_graph(), raw)
    assert without_phi.action == "ACQUIRE"
    assert without_phi.question_id == "q2"


def test_g8_0_unreachable_q3_not_verified() -> None:
    """§7.2: inert admitted (q3,X) is not in S_R — never VERIFY q3."""
    raw = {"q1": "Yes", "q2": "B", "q3": "X"}
    verified = frozenset({sentinel_key("q1", "Yes"), sentinel_key("q2", "B")})
    _fixture, done = _analyze(fork_g8_graph(), raw, verified=verified)
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"
    assert done.question_id != "q3"

    _fixture, first = _analyze(fork_g8_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id != "q3"


def test_g1_0_acquire_one_member_of_witness() -> None:
    """E=∅: D_1 empty, still Resolvable; issue one member of D (earliest id ⇒ q1)."""
    _fixture, directive = _analyze(xor_g1_graph(), {})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q1"


def test_g6_semantic_exhaustion() -> None:
    _fixture, directive = _analyze(joint_g6_graph(), {"q1": "Yes"})
    assert directive.action == "STOP"
    assert directive.stop_reason == "not_resolvable_by_remaining_evidence_vocabulary"
    assert directive.question_id is None


def test_g7_residual_budget_is_not_g6() -> None:
    fixture = compile_golden(xor_g1_graph())
    directive = analyze_inquiry(
        fixture.ir,
        {},
        EMPTY_ASSUMPTIONS,
        frozenset(),
        InquiryBudget(max_residual_sat_calls=0),
        fixture.catalog,
    )
    assert directive.action == "STOP"
    assert directive.stop_reason == "no_joint_discriminator_within_budget"
    assert directive.stop_reason != "not_resolvable_by_remaining_evidence_vocabulary"


def test_g4_0_retract_rebases_to_g2() -> None:
    """RETRACT (q2,B) → new E as G2.0; fresh analyze_inquiry; do not STOP unsupported."""
    _fixture, directive = _analyze(fork_g2_graph(), {"q1": "Yes"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"
    assert directive.stop_reason != "verified_resolved_consequence"


def test_g4_1_insufficient_keeps_verify() -> None:
    """INSUFFICIENT: E unchanged, still VERIFY the same S_R."""
    raw = {"q1": "Yes", "q2": "B"}
    _fixture, first = _analyze(fork_g2_graph(), raw)
    _fixture, again = _analyze(fork_g2_graph(), raw)
    assert first.action == "VERIFY"
    assert again.action == "VERIFY"
    assert first.question_id == again.question_id == "q1"


def test_g4_2_replace_is_semantic_exhaustion() -> None:
    _fixture, directive = _analyze(fork_g2_graph(), {"q1": "Yes", "q2": "A"})
    assert directive.action == "STOP"
    assert directive.stop_reason == "not_resolvable_by_remaining_evidence_vocabulary"


def test_g9_extractor_issue_is_singleton_and_blind() -> None:
    fixture, directive = _analyze(xor_g1_graph(), {})
    assert directive.action == "ACQUIRE"
    assert directive.question_id is not None
    task = build_extractor_issue(fixture.catalog, directive.question_id)
    question = task.question
    assert question.question_id == directive.question_id
    assert question.stem
    assert question.options
    blob = " ".join(
        [
            question.question_id,
            question.stem,
            *question.options,
            str(task),
        ]
    )
    forbidden = (
        "OA",
        "OB",
        "Resolved",
        "S_R",
        "VERIFY",
        "ACQUIRE",
        "result_kind",
        "C_poss",
        "D_1",
    )
    for token in forbidden:
        assert token not in blob
    assert not hasattr(task, "action")
    assert not hasattr(question, "action")
