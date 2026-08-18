"""Core owns P_v: client cannot mint Retain; VERIFY binds to current directive."""

from __future__ import annotations

import json

import pytest

from smeme.mcp.inquire import analyze, get_task, verify
from smeme.mcp.inquire.codec import (
    encode_admitted,
    encode_verification_key,
    encode_verified,
    encode_worksheet_catalog,
)
from smeme.mcp.inquire.handlers import InquireHandlerError
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.orchestration.inquire import DEFAULT_PV_VERSION
from smeme.reasoning.runtime.inquire.types import VerificationKey
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    compile_golden,
    fork_g2_graph,
    sentinel_assertion,
)


def _fixture():
    return compile_golden(fork_g2_graph())


def _resolved_admitted():
    return (sentinel_assertion("q1", "Yes"), sentinel_assertion("q2", "B"))


def _state_jsons(fixture, admitted, verified=frozenset()):
    return {
        "ir_json": json.dumps(ir_to_json(fixture.ir)),
        "worksheet_catalog_json": json.dumps(encode_worksheet_catalog(fixture.catalog)),
        "admitted_json": json.dumps(encode_admitted(admitted)),
        "verified_json": json.dumps(encode_verified(verified)),
        "artifact_identity": SENTINEL_ARTIFACT,
    }


def _matching_observations(evaluations, *, option: str, tag: str = "p-v"):
    rows = []
    for i, item in enumerate(evaluations):
        rows.append(
            {
                "evaluation_id": item["evaluation_id"],
                "question_id": item["task"]["question_id"],
                "selected_option": option,
                "provenance_id": f"{tag}-{i}",
            }
        )
    return json.dumps(rows)


def test_identical_analyze_reproduces_evaluations() -> None:
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    a = analyze(**kwargs)
    b = analyze(**kwargs)
    assert a["directive"] == b["directive"]
    assert json.dumps(a["evaluations"], sort_keys=True) == json.dumps(
        b["evaluations"], sort_keys=True
    )


def test_valid_transcript_yields_core_retain() -> None:
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    analyzed = analyze(**kwargs)
    assert analyzed["directive"]["action"] == "VERIFY"
    qid = analyzed["directive"]["question_id"]
    live = next(a for a in admitted if a.question_id == qid)
    out = verify(
        **kwargs,
        verification_key_json=json.dumps(analyzed["directive"]["verification_key"]),
        observations_json=_matching_observations(
            analyzed["evaluations"], option=live.option
        ),
    )
    assert out["decision"] == {"kind": "retain"}
    assert out["status"] == "applied"
    assert any(k["question_id"] == qid for k in out["verified"])


def test_disagreement_yields_insufficient_not_protocol_error() -> None:
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    analyzed = analyze(**kwargs)
    qid = analyzed["directive"]["question_id"]
    live = next(a for a in admitted if a.question_id == qid)
    other = next(o for o in fixture.catalog[qid].options if o != live.option)
    out = verify(
        **kwargs,
        verification_key_json=json.dumps(analyzed["directive"]["verification_key"]),
        observations_json=_matching_observations(
            analyzed["evaluations"], option=other
        ),
    )
    assert out["decision"] == {"kind": "insufficient"}
    assert out["verified"] == []


def test_incomplete_transcript_is_protocol_error() -> None:
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    analyzed = analyze(**kwargs)
    one = analyzed["evaluations"][0]
    with pytest.raises(InquireHandlerError) as exc:
        verify(
            **kwargs,
            verification_key_json=json.dumps(analyzed["directive"]["verification_key"]),
            observations_json=json.dumps(
                [
                    {
                        "evaluation_id": one["evaluation_id"],
                        "question_id": one["task"]["question_id"],
                        "selected_option": "Yes",
                        "provenance_id": "p",
                    }
                ]
            ),
        )
    assert exc.value.code == "inquire_verification_protocol"


def test_echoed_pv_foo_fails_closed() -> None:
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    analyzed = analyze(**kwargs)
    key = dict(analyzed["directive"]["verification_key"])
    key["pv_version"] = "pv-foo"
    with pytest.raises(InquireHandlerError) as exc:
        verify(
            **kwargs,
            verification_key_json=json.dumps(key),
            observations_json=_matching_observations(
                analyzed["evaluations"],
                option=analyzed["directive"]["option"],
            ),
        )
    assert exc.value.code in {
        "inquire_verify_target_mismatch",
        "inquire_verification_protocol",
    }


def test_wrong_current_verify_target_fails() -> None:
    """Live q2 must not be pre-verified while ANALYZE demands VERIFY q1 (or vice versa)."""
    fixture = _fixture()
    admitted = _resolved_admitted()
    kwargs = _state_jsons(fixture, admitted)
    analyzed = analyze(**kwargs)
    assert analyzed["directive"]["action"] == "VERIFY"
    current_q = analyzed["directive"]["question_id"]
    other_q = "q2" if current_q == "q1" else "q1"
    other = next(a for a in admitted if a.question_id == other_q)
    forged = VerificationKey(
        artifact_identity=SENTINEL_ARTIFACT,
        question_id=other.question_id,
        option=other.option,
        provenance_identity=str(other.provenance_id),
        pv_version=DEFAULT_PV_VERSION,
    )
    # Build a battery as if we were verifying the other question.
    forged_analyze_key = {
        **kwargs,
        # Same state still demands current_q; submitting forged key must fail the gate.
    }
    with pytest.raises(InquireHandlerError) as exc:
        verify(
            **forged_analyze_key,
            verification_key_json=json.dumps(encode_verification_key(forged)),
            observations_json=_matching_observations(
                analyzed["evaluations"],
                option=other.option,
            ),
        )
    assert exc.value.code == "inquire_verify_target_mismatch"


def test_get_task_unknown_question() -> None:
    fixture = _fixture()
    with pytest.raises(InquireHandlerError) as exc:
        get_task(
            worksheet_catalog_json=json.dumps(encode_worksheet_catalog(fixture.catalog)),
            question_id="q-missing",
        )
    assert exc.value.code == "inquire_unknown_question"
