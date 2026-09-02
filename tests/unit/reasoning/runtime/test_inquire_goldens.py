"""G1–G9 as ``analyze_inquiry`` entry points. Target goldens; not Appendix B."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS, assumptions_from_lists
from smeme.reasoning.runtime.evaluate import evaluate_reasoning
from smeme.reasoning.runtime.inquire import (
    admit_assertion,
    analyze_inquiry,
    apply_verification_decision,
    build_extractor_issue,
)
from smeme.reasoning.runtime.inquire.policy import (
    AlwaysInsufficientPolicy,
    AlwaysRetainPolicy,
    AlwaysRetractPolicy,
    ReplaceWith,
    VerificationRequest,
    VerificationResult,
)
from smeme.reasoning.runtime.inquire.support import SupportResult
from smeme.reasoning.runtime.inquire.types import (
    InquiryBudget,
    VerificationKey,
    verification_key_for,
)
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    SENTINEL_PV_VERSION,
    compile_golden,
    fork_g2_graph,
    fork_g8_graph,
    joint_g6_graph,
    sentinel_key,
    sentinel_provenance,
    xor_g1_graph,
)

_BUDGET = InquiryBudget()


def _request(assertion) -> VerificationRequest:
    return VerificationRequest(
        verification_key=verification_key_for(
            assertion,
            artifact_identity=SENTINEL_ARTIFACT,
            pv_version=SENTINEL_PV_VERSION,
        )
    )


def _admit(ir, raw: dict[str, str], *, provenance: str | None = None):
    admitted: tuple = ()
    for question_id, option in raw.items():
        admitted = admit_assertion(
            ir,
            admitted,
            question_id=question_id,
            option=option,
            provenance_id=sentinel_provenance(provenance or f"p-{question_id}"),
        )
    return admitted


def _analyze(
    graph,
    raw: dict[str, str],
    *,
    verified: frozenset[VerificationKey] | None = None,
    assumptions=EMPTY_ASSUMPTIONS,
    artifact_identity: str = SENTINEL_ARTIFACT,
    pv_version: str = SENTINEL_PV_VERSION,
    admitted=None,
):
    fixture = compile_golden(graph)
    live = admitted if admitted is not None else _admit(fixture.ir, raw)
    directive = analyze_inquiry(
        fixture.ir,
        live,
        assumptions,
        verified if verified is not None else frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=artifact_identity,
        pv_version=pv_version,
    )
    return fixture, live, directive


def test_g2_0_acquire_q2_not_verify() -> None:
    """Co-reachable extra conclusion: ACQUIRE q2, not VERIFY a support for c1."""
    _fixture, _admitted, directive = _analyze(fork_g2_graph(), {"q1": "Yes"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"
    assert directive.stop_reason is None
    assert directive.verification_key is None


def test_g2_0_apply_sat_unique_is_not_resolved() -> None:
    """Characterization: Apply may report SAT_UNIQUE while Inquire still ACQUIREs (G2 hole)."""
    fixture = compile_golden(fork_g2_graph())
    res, _audit = evaluate_reasoning(fixture.ir, raw_answers={"q1": "Yes"})
    admitted = _admit(fixture.ir, {"q1": "Yes"})
    directive = analyze_inquiry(
        fixture.ir,
        admitted,
        EMPTY_ASSUMPTIONS,
        frozenset(),
        _BUDGET,
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"
    if res.status == "SAT_UNIQUE":
        assert res.true_conclusion_id == "c1"


def test_g8_1_issued_question_is_q2() -> None:
    """G8 graph under G2.0 answers: ACQUIRE q2. Set membership ``q3 ∉ D_1`` is a helper test."""
    _fixture, _admitted, directive = _analyze(fork_g8_graph(), {"q1": "Yes"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2"


def test_g1_1_acquire_q2a() -> None:
    """After ADMIT {q1=0}, sequential demotion: ACQUIRE q2a."""
    _fixture, _admitted, directive = _analyze(xor_g1_graph(), {"q1": "0"})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q2a"


def test_g1_2_verify_walk_over_resolving_support() -> None:
    raw = {"q1": "0", "q2a": "0"}
    fixture, admitted, first = _analyze(xor_g1_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"
    assert first.option == "0"
    assert first.verification_key is not None
    assert first.verification_key == sentinel_key("q1", "0", provenance="p-q1")

    _fixture, _admitted, second = _analyze(
        xor_g1_graph(),
        raw,
        admitted=admitted,
        verified=frozenset({first.verification_key}),
    )
    assert second.action == "VERIFY"
    assert second.question_id == "q2a"
    assert second.option == "0"
    assert second.verification_key is not None
    assert second.verification_key == sentinel_key("q2a", "0", provenance="p-q2a")

    _fixture, _admitted, done = _analyze(
        xor_g1_graph(),
        raw,
        admitted=admitted,
        verified=frozenset({first.verification_key, second.verification_key}),
    )
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"
    assert done.question_id is None
    assert done.verification_key is None
    _ = fixture


@pytest.mark.parametrize("support_status", ["budget", "timeout", "unknown"])
def test_resolved_support_miss_is_resolving_support_incomplete(
    support_status: str,
) -> None:
    """Resolved(B) + S_R operational miss → resolving_support_incomplete (not operational_*)."""
    raw = {"q1": "0", "q2a": "0"}
    fixture = compile_golden(xor_g1_graph())
    live = _admit(fixture.ir, raw)
    with patch(
        "smeme.reasoning.runtime.inquire.analyze.resolving_support",
        return_value=SupportResult(status=support_status),
    ):
        directive = analyze_inquiry(
            fixture.ir,
            live,
            EMPTY_ASSUMPTIONS,
            frozenset(),
            _BUDGET,
            fixture.catalog,
            artifact_identity=SENTINEL_ARTIFACT,
            pv_version=SENTINEL_PV_VERSION,
        )
    assert directive.action == "STOP"
    assert directive.stop_reason == "resolving_support_incomplete"
    assert directive.operational_status == support_status
    assert directive.stop_reason != "operational_budget"
    assert directive.stop_reason != "operational_timeout"
    assert directive.stop_reason != "operational_unknown"


def test_g3_0_verify_not_entailment_support() -> None:
    """After verifying q1 alone, still VERIFY q2 — decisive_support is not S_R."""
    raw = {"q1": "Yes", "q2": "B"}
    _fixture, admitted, first = _analyze(fork_g2_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"
    assert first.option == "Yes"
    assert first.verification_key is not None

    _fixture, _admitted, second = _analyze(
        fork_g2_graph(),
        raw,
        admitted=admitted,
        verified=frozenset({first.verification_key}),
    )
    assert second.action == "VERIFY"
    assert second.question_id == "q2"
    assert second.option == "B"
    assert second.stop_reason is None


def test_g5_assumptions_retained_in_support() -> None:
    phi = assumptions_from_lists(force_unreachable_ids=["c2"])
    raw = {"q1": "Yes"}
    _fixture, admitted, first = _analyze(fork_g2_graph(), raw, assumptions=phi)
    assert first.action == "VERIFY"
    assert first.question_id == "q1"
    assert first.verification_key is not None

    _fixture, _admitted, done = _analyze(
        fork_g2_graph(),
        raw,
        assumptions=phi,
        admitted=admitted,
        verified=frozenset({first.verification_key}),
    )
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"

    _fixture, _admitted, without_phi = _analyze(fork_g2_graph(), raw)
    assert without_phi.action == "ACQUIRE"
    assert without_phi.question_id == "q2"


def test_g8_0_unreachable_q3_not_verified() -> None:
    """§7.2: inert admitted (q3,X) is not in S_R — never VERIFY q3."""
    raw = {"q1": "Yes", "q2": "B", "q3": "X"}
    fixture, admitted, first = _analyze(fork_g8_graph(), raw)
    assert first.action == "VERIFY"
    assert first.question_id != "q3"
    q1 = next(item for item in admitted if item.question_id == "q1")
    q2 = next(item for item in admitted if item.question_id == "q2")
    verified = frozenset(
        {
            sentinel_key(q1.question_id, q1.option, provenance=str(q1.provenance_id)),
            sentinel_key(q2.question_id, q2.option, provenance=str(q2.provenance_id)),
        }
    )
    _fixture, _admitted, done = _analyze(fork_g8_graph(), raw, admitted=admitted, verified=verified)
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"
    assert done.question_id != "q3"
    _ = fixture


def test_g1_0_acquire_one_member_of_witness() -> None:
    """E=∅: D_1 empty, still Resolvable; issue one member of D (earliest id ⇒ q1)."""
    _fixture, _admitted, directive = _analyze(xor_g1_graph(), {})
    assert directive.action == "ACQUIRE"
    assert directive.question_id == "q1"


def test_g6_semantic_exhaustion() -> None:
    _fixture, _admitted, directive = _analyze(joint_g6_graph(), {"q1": "Yes"})
    assert directive.action == "STOP"
    assert directive.stop_reason == "not_resolvable_by_remaining_evidence_vocabulary"
    assert directive.question_id is None


def test_g7_residual_budget_is_not_g6() -> None:
    fixture = compile_golden(xor_g1_graph())
    directive = analyze_inquiry(
        fixture.ir,
        (),
        EMPTY_ASSUMPTIONS,
        frozenset(),
        InquiryBudget(max_residual_sat_calls=0),
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
    )
    assert directive.action == "STOP"
    assert directive.stop_reason == "no_joint_discriminator_within_budget"
    assert directive.stop_reason != "not_resolvable_by_remaining_evidence_vocabulary"


def _g3_after_retain_q1():
    """G3 resolved base with q1 RETAINed so the next VERIFY is q2."""
    fixture, admitted, first = _analyze(fork_g2_graph(), {"q1": "Yes", "q2": "B"})
    assert first.action == "VERIFY"
    assert first.question_id == "q1"
    q1 = next(item for item in admitted if item.question_id == "q1")
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=AlwaysRetainPolicy().decide(_request(q1), VerificationResult()),
    )
    assert transition.status == "applied"
    _fixture, live, directive = _analyze(
        fork_g2_graph(),
        {},
        admitted=transition.admitted,
        verified=transition.verified,
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q2"
    q2 = next(item for item in live if item.question_id == "q2")
    return fixture, live, transition.verified, q2, directive


def test_g4_0_retract_rebases_to_g2() -> None:
    """RETRACT (q2,B) → new E as G2.0; fresh analyze_inquiry; do not STOP unsupported."""
    fixture, admitted, verified, q2, _directive = _g3_after_retain_q1()
    decision = AlwaysRetractPolicy().decide(_request(q2), VerificationResult())
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=verified,
        assertion=q2,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=decision,
    )
    assert transition.status == "applied"
    assert transition.base_changed is True
    assert {item.question_id: item.option for item in transition.admitted} == {"q1": "Yes"}
    assert all(key.question_id != "q2" for key in transition.verified)
    _fixture, _live, after = _analyze(
        fork_g2_graph(),
        {},
        admitted=transition.admitted,
        verified=transition.verified,
    )
    assert after.action == "ACQUIRE"
    assert after.question_id == "q2"
    assert after.stop_reason != "verified_resolved_consequence"


def test_g4_1_insufficient_keeps_verify() -> None:
    """INSUFFICIENT: E unchanged, still VERIFY the same assertion."""
    fixture, admitted, verified, q2, before = _g3_after_retain_q1()
    decision = AlwaysInsufficientPolicy().decide(_request(q2), VerificationResult())
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=verified,
        assertion=q2,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=decision,
    )
    assert transition.status == "applied"
    assert transition.base_changed is False
    assert transition.admitted == admitted
    assert transition.verified == verified
    _fixture, _live, after = _analyze(
        fork_g2_graph(),
        {},
        admitted=transition.admitted,
        verified=transition.verified,
    )
    assert after.action == "VERIFY"
    assert after.question_id == before.question_id == "q2"
    assert after.option == before.option == "B"
    assert after.verification_key == before.verification_key


def test_g4_2_replace_is_semantic_exhaustion() -> None:
    fixture, admitted, verified, q2, _before = _g3_after_retain_q1()
    new_p = sentinel_provenance("p-q2-replaced")
    decision = ReplaceWith(option="A", provenance_id=new_p).decide(
        _request(q2), VerificationResult()
    )
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=verified,
        assertion=q2,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=decision,
    )
    assert transition.status == "applied"
    assert transition.base_changed is True
    replacement = next(item for item in transition.admitted if item.question_id == "q2")
    assert replacement.option == "A"
    assert replacement.provenance_id == new_p
    assert all(key.question_id != "q2" for key in transition.verified)
    _fixture, _live, after = _analyze(
        fork_g2_graph(),
        {},
        admitted=transition.admitted,
        verified=transition.verified,
    )
    assert after.action == "STOP"
    assert after.stop_reason == "not_resolvable_by_remaining_evidence_vocabulary"


def test_p2_retain_walk_stops_when_sr_verified() -> None:
    fixture, admitted, first = _analyze(fork_g2_graph(), {"q1": "Yes", "q2": "B"})
    assert first.action == "VERIFY"
    q1 = next(item for item in admitted if item.question_id == "q1")
    retain_q1 = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=AlwaysRetainPolicy().decide(_request(q1), VerificationResult()),
    )
    _fixture, live, after_q1 = _analyze(
        fork_g2_graph(),
        {},
        admitted=retain_q1.admitted,
        verified=retain_q1.verified,
    )
    assert after_q1.action == "VERIFY"
    assert after_q1.question_id == "q2"
    q2 = next(item for item in live if item.question_id == "q2")
    retain_q2 = apply_verification_decision(
        ir=fixture.ir,
        admitted=live,
        verified=retain_q1.verified,
        assertion=q2,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=AlwaysRetainPolicy().decide(_request(q2), VerificationResult()),
    )
    _fixture, _live, done = _analyze(
        fork_g2_graph(),
        {},
        admitted=retain_q2.admitted,
        verified=retain_q2.verified,
    )
    assert done.action == "STOP"
    assert done.stop_reason == "verified_resolved_consequence"


def test_g9_extractor_issue_is_singleton_and_blind() -> None:
    fixture, _admitted, directive = _analyze(xor_g1_graph(), {})
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
    assert not hasattr(task, "verification_key")
    assert not hasattr(question, "verification_key")
