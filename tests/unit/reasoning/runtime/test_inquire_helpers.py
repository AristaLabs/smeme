"""Helper tests for Inquire conclusion space (Slice A). Not Appendix B."""

from __future__ import annotations

from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS
from smeme.reasoning.runtime.inquire.discriminators import myopic_discriminators
from smeme.reasoning.runtime.inquire.space import (
    check_cons,
    compile_working_base,
    entailed_conclusions,
    possible_conclusions,
    resolved_conclusion,
    unanswered_questions,
)
from smeme.reasoning.runtime.inquire.types import InquiryBudget
from tests.unit.reasoning.runtime.inquire_fixtures import (
    compile_golden,
    fork_g2_graph,
    fork_g8_graph,
    joint_g6_graph,
    xor_g1_graph,
)

_BUDGET = InquiryBudget()


def _base(graph, admitted: dict[str, str] | None = None):
    fixture = compile_golden(graph)
    return compile_working_base(
        fixture.ir,
        admitted or {},
        EMPTY_ASSUMPTIONS,
        _BUDGET,
    )


def test_fixtures_validate_and_compile() -> None:
    for builder in (xor_g1_graph, fork_g2_graph, joint_g6_graph, fork_g8_graph):
        compile_golden(builder())


def test_cons_empty_evidence_on_g2() -> None:
    base = _base(fork_g2_graph())
    cons = check_cons(base)
    assert cons.status == "consistent"


def test_g2_0_space_not_resolved() -> None:
    base = _base(fork_g2_graph(), {"q1": "Yes"})
    poss = possible_conclusions(base)
    ent = entailed_conclusions(base)
    resolved = resolved_conclusion(base)
    assert poss.status == "ok"
    assert poss.conclusions == frozenset({"c1", "c2"})
    assert ent.status == "ok"
    assert ent.conclusions == frozenset({"c1"})
    assert resolved.status == "unresolved"
    assert resolved.conclusion_id is None


def test_g6_joint_entailment_unresolved_empty_u() -> None:
    graph = joint_g6_graph()
    fixture = compile_golden(graph)
    admitted = {"q1": "Yes"}
    base = compile_working_base(fixture.ir, admitted, EMPTY_ASSUMPTIONS, _BUDGET)
    poss = possible_conclusions(base)
    ent = entailed_conclusions(base)
    resolved = resolved_conclusion(base)
    assert poss.status == "ok"
    assert poss.conclusions == frozenset({"c1", "c2"})
    assert ent.status == "ok"
    assert ent.conclusions == frozenset({"c1", "c2"})
    assert resolved.status == "unresolved"
    assert unanswered_questions(fixture.ir, admitted) == []


def test_g1_0_d1_empty() -> None:
    base = _base(xor_g1_graph())
    d1 = myopic_discriminators(base)
    assert d1.status == "ok"
    assert d1.question_ids == ()


def test_g8_1_q3_not_in_d1() -> None:
    """G8.1 obligation: unreachable q3 is absent from D_1, not merely outranked."""
    base = _base(fork_g8_graph(), {"q1": "Yes"})
    d1 = myopic_discriminators(base)
    assert d1.status == "ok"
    assert "q3" not in d1.question_ids
    assert d1.question_ids == ("q2",)


def test_g3_exact_sr_strictly_larger_than_decisive_support() -> None:
    from smeme.reasoning.runtime.decisive_support import find_minimal_decisive_supports
    from smeme.reasoning.runtime.inquire.support import resolving_support

    fixture = compile_golden(fork_g2_graph())
    admitted = {"q1": "Yes", "q2": "B"}
    base = compile_working_base(fixture.ir, admitted, EMPTY_ASSUMPTIONS, _BUDGET)
    resolved = resolved_conclusion(base)
    assert resolved.status == "resolved"
    assert resolved.conclusion_id == "c1"
    support = resolving_support(base, "c1")
    assert support.status == "ok"
    assert {(p.question_id, p.option) for p in support.pairs} == {("q1", "Yes"), ("q2", "B")}

    decisive = find_minimal_decisive_supports(
        fixture.ir,
        fixture.graph,
        base_norm=admitted,
        target_conclusion_id="c1",
    )
    entailment_sets = [frozenset(s.support_answers.items()) for s in decisive.supports]
    assert frozenset({("q1", "Yes")}) in entailment_sets
    assert frozenset({("q1", "Yes"), ("q2", "B")}) not in entailment_sets


def test_g5_exact_sr_keeps_phi() -> None:
    from smeme.reasoning.runtime.assumptions import assumptions_from_lists
    from smeme.reasoning.runtime.inquire.support import resolving_support

    fixture = compile_golden(fork_g2_graph())
    phi = assumptions_from_lists(force_unreachable_ids=["c2"])
    base = compile_working_base(fixture.ir, {"q1": "Yes"}, phi, _BUDGET)
    resolved = resolved_conclusion(base)
    assert resolved.status == "resolved"
    support = resolving_support(base, "c1")
    assert support.status == "ok"
    assert {(p.question_id, p.option) for p in support.pairs} == {("q1", "Yes")}


def test_g8_exact_sr_drops_inert_q3() -> None:
    from smeme.reasoning.runtime.inquire.support import resolving_support

    fixture = compile_golden(fork_g8_graph())
    admitted = {"q1": "Yes", "q2": "B", "q3": "X"}
    base = compile_working_base(fixture.ir, admitted, EMPTY_ASSUMPTIONS, _BUDGET)
    support = resolving_support(base, "c1")
    assert support.status == "ok"
    assert {(p.question_id, p.option) for p in support.pairs} == {("q1", "Yes"), ("q2", "B")}


def test_sr_budget_miss_is_operational_not_g7() -> None:
    from smeme.reasoning.runtime.inquire.support import resolving_support

    fixture = compile_golden(fork_g2_graph())
    admitted = {"q1": "Yes", "q2": "B"}
    budget = InquiryBudget(max_sat_calls=10)
    base = compile_working_base(fixture.ir, admitted, EMPTY_ASSUMPTIONS, budget)
    base.sat_calls[0] = budget.max_sat_calls
    support = resolving_support(base, "c1")
    assert support.status == "budget"


def test_empty_u_proves_not_resolvable_without_sat() -> None:
    from smeme.reasoning.runtime.inquire.resolvable import search_resolving_witness

    fixture = compile_golden(joint_g6_graph())
    base = compile_working_base(fixture.ir, {"q1": "Yes"}, EMPTY_ASSUMPTIONS, _BUDGET)
    start = base.sat_calls[0]
    witness = search_resolving_witness(base, _BUDGET)
    assert witness.status == "not_resolvable"
    assert base.sat_calls[0] == start


def test_inquire_public_exports_are_analyze_and_extractor_only() -> None:
    import smeme.reasoning.runtime.inquire as inquire

    assert inquire.__all__ == ["analyze_inquiry", "build_extractor_issue"]
