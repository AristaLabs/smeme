"""Phase 2 transition identity, stale response, and fail-closed admission."""

from __future__ import annotations

import pytest

from smeme.reasoning.runtime.assumptions import EMPTY_ASSUMPTIONS
from smeme.reasoning.runtime.consistency_gate import PremiseInvariantError
from smeme.reasoning.runtime.inquire import analyze_inquiry, apply_verification_decision
from smeme.reasoning.runtime.inquire.transition import (
    Insufficient,
    Replace,
    Retain,
    admit_assertion,
)
from smeme.reasoning.runtime.inquire.types import InquiryBudget
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    SENTINEL_PV_VERSION,
    compile_golden,
    fork_g2_graph,
    sentinel_assertion,
    sentinel_key,
    sentinel_provenance,
)


def _g3_admitted(ir):
    admitted = admit_assertion(
        ir,
        (),
        question_id="q1",
        option="Yes",
        provenance_id=sentinel_provenance("p1"),
    )
    return admit_assertion(
        ir,
        admitted,
        question_id="q2",
        option="B",
        provenance_id=sentinel_provenance("p1"),
    )


def test_replace_invalid_option_is_admission_rejected() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    q2 = next(item for item in admitted if item.question_id == "q2")
    verified = frozenset({sentinel_key("q1", "Yes", provenance="p1")})
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=verified,
        assertion=q2,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Replace(
            option="not-an-option",
            provenance_id=sentinel_provenance("p-bad"),
        ),
    )
    assert transition.status == "admission_rejected"
    assert transition.base_changed is False
    assert transition.admitted == admitted
    assert transition.verified == verified


def test_stale_retain_after_rebase_is_assertion_mismatch() -> None:
    """Probe 4 at the epistemic layer: late RETAIN of (q2,B,p1) after REPLACE."""
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    q2_b = next(item for item in admitted if item.question_id == "q2")
    replaced = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q2_b,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Replace(option="A", provenance_id=sentinel_provenance("p2")),
    )
    assert replaced.status == "applied"
    stale = apply_verification_decision(
        ir=fixture.ir,
        admitted=replaced.admitted,
        verified=replaced.verified,
        assertion=q2_b,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    assert stale.status == "assertion_mismatch"
    assert stale.admitted == replaced.admitted
    assert stale.verified == replaced.verified
    live_q2 = next(item for item in stale.admitted if item.question_id == "q2")
    assert live_q2.option == "A"
    assert str(live_q2.provenance_id) == "p2"
    assert sentinel_key("q2", "B", provenance="p1") not in stale.verified
    assert sentinel_key("q2", "A", provenance="p2") not in stale.verified


def test_retain_wrong_provenance_is_assertion_mismatch() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    stale = sentinel_assertion("q2", "B", provenance="other-p")
    transition = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=stale,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    assert transition.status == "assertion_mismatch"
    assert transition.verified == frozenset()


def test_verification_keys_do_not_collide_across_identity() -> None:
    same_qa = sentinel_key("q2", "B", provenance="p1")
    different_answer = sentinel_key("q2", "A", provenance="p1")
    different_provenance = sentinel_key("q2", "B", provenance="p2")
    different_artifact = sentinel_key("q2", "B", provenance="p1", artifact="other-artifact")
    different_pv = sentinel_key("q2", "B", provenance="p1", pv_version="pv-other")
    assert (
        len({same_qa, different_answer, different_provenance, different_artifact, different_pv})
        == 5
    )


def test_pv_version_change_invalidates_prior_retain() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    q1 = next(item for item in admitted if item.question_id == "q1")
    retained = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q1,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Retain(),
    )
    directive = analyze_inquiry(
        fixture.ir,
        retained.admitted,
        EMPTY_ASSUMPTIONS,
        retained.verified,
        InquiryBudget(),
        fixture.catalog,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version="pv-other",
    )
    assert directive.action == "VERIFY"
    assert directive.question_id == "q1"


def test_empty_provenance_is_rejected() -> None:
    with pytest.raises(PremiseInvariantError, match="empty provenance_id"):
        sentinel_assertion("q1", "Yes", provenance="   ")


def test_admit_assertion_rejects_already_answered_question() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    with pytest.raises(PremiseInvariantError, match="already admitted"):
        admit_assertion(
            fixture.ir,
            admitted,
            question_id="q2",
            option="A",
            provenance_id=sentinel_provenance("p-new"),
        )


def test_stale_insufficient_is_assertion_mismatch() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = _g3_admitted(fixture.ir)
    q2_b = next(item for item in admitted if item.question_id == "q2")
    replaced = apply_verification_decision(
        ir=fixture.ir,
        admitted=admitted,
        verified=frozenset(),
        assertion=q2_b,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Replace(option="A", provenance_id=sentinel_provenance("p2")),
    )
    stale = apply_verification_decision(
        ir=fixture.ir,
        admitted=replaced.admitted,
        verified=replaced.verified,
        assertion=q2_b,
        artifact_identity=SENTINEL_ARTIFACT,
        pv_version=SENTINEL_PV_VERSION,
        decision=Insufficient(),
    )
    assert stale.status == "assertion_mismatch"
    assert stale.admitted == replaced.admitted
