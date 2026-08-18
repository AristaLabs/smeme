"""In-process Inquire MCP e2e: ACQUIRE → VERIFY transcript → STOP."""

from __future__ import annotations

import json

from smeme.mcp.inquire import admit, analyze, get_task, verify
from smeme.mcp.inquire.codec import (
    encode_admitted,
    encode_verified,
    encode_worksheet_catalog,
)
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.orchestration.inquire import DEFAULT_PV_VERSION
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    compile_golden,
    fork_g2_graph,
)


def _catalog_json(fixture) -> str:
    return json.dumps(encode_worksheet_catalog(fixture.catalog))


def _ir_json(fixture) -> str:
    return json.dumps(ir_to_json(fixture.ir))


def test_green_loop_acquire_verify_stop() -> None:
    fixture = compile_golden(fork_g2_graph())
    catalog = _catalog_json(fixture)
    ir = _ir_json(fixture)
    admitted: list = []
    verified: list = []

    # ACQUIRE q1
    a1 = analyze(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json=json.dumps(admitted),
        verified_json=json.dumps(verified),
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert a1["directive"]["action"] == "ACQUIRE"
    q1 = a1["directive"]["question_id"]
    task1 = get_task(worksheet_catalog_json=catalog, question_id=q1)
    assert task1["question_id"] == q1
    adm1 = admit(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json=json.dumps(admitted),
        question_id=q1,
        selected_option="Yes",
        provenance_id="p-q1",
    )
    assert adm1["status"] == "applied"
    admitted = adm1["admitted"]

    # ACQUIRE q2
    a2 = analyze(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json=json.dumps(admitted),
        verified_json=json.dumps(verified),
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert a2["directive"]["action"] == "ACQUIRE"
    q2 = a2["directive"]["question_id"]
    adm2 = admit(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json=json.dumps(admitted),
        question_id=q2,
        selected_option="B",
        provenance_id="p-q2",
    )
    admitted = adm2["admitted"]

    # VERIFY first load-bearing assertion
    for _ in range(4):
        ax = analyze(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            verified_json=json.dumps(verified),
            artifact_identity=SENTINEL_ARTIFACT,
        )
        if ax["directive"]["action"] == "STOP":
            assert ax["directive"]["stop_reason"] == "verified_resolved_consequence"
            break
        assert ax["directive"]["action"] == "VERIFY"
        assert ax["pv_version"] == DEFAULT_PV_VERSION
        key = ax["directive"]["verification_key"]
        live_option = ax["directive"]["option"]
        observations = []
        for i, item in enumerate(ax["evaluations"]):
            observations.append(
                {
                    "evaluation_id": item["evaluation_id"],
                    "question_id": item["task"]["question_id"],
                    "selected_option": live_option,
                    "provenance_id": f"p-v-{key['question_id']}-{i}",
                }
            )
        vout = verify(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            verified_json=json.dumps(verified),
            artifact_identity=SENTINEL_ARTIFACT,
            verification_key_json=json.dumps(key),
            observations_json=json.dumps(observations),
        )
        assert vout["decision"]["kind"] == "retain"
        admitted = vout["admitted"]
        verified = vout["verified"]
    else:
        raise AssertionError("did not reach STOP")


def test_abstain_does_not_mutate() -> None:
    fixture = compile_golden(fork_g2_graph())
    catalog = _catalog_json(fixture)
    ir = _ir_json(fixture)
    a1 = analyze(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json="[]",
        verified_json="[]",
        artifact_identity=SENTINEL_ARTIFACT,
    )
    q = a1["directive"]["question_id"]
    out = admit(
        ir_json=ir,
        worksheet_catalog_json=catalog,
        admitted_json="[]",
        question_id=q,
        selected_option=None,
        provenance_id=None,
    )
    assert out["status"] == "abstained"
    assert out["admitted"] == []


def test_stop_has_no_evaluations() -> None:
    fixture = compile_golden(fork_g2_graph())
    catalog = _catalog_json(fixture)
    ir = _ir_json(fixture)
    # Drive to STOP via handler loop (reuse green path briefly).
    admitted: list = []
    verified: list = []
    # Acquire both
    for _ in range(2):
        ax = analyze(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            verified_json=json.dumps(verified),
            artifact_identity=SENTINEL_ARTIFACT,
        )
        assert ax["directive"]["action"] == "ACQUIRE"
        qid = ax["directive"]["question_id"]
        opt = "Yes" if qid == "q1" else "B"
        adm = admit(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            question_id=qid,
            selected_option=opt,
            provenance_id=f"p-{qid}",
        )
        admitted = adm["admitted"]

    for _ in range(4):
        ax = analyze(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            verified_json=json.dumps(verified),
            artifact_identity=SENTINEL_ARTIFACT,
        )
        if ax["directive"]["action"] == "STOP":
            assert "evaluations" not in ax
            return
        key = ax["directive"]["verification_key"]
        live_option = ax["directive"]["option"]
        observations = [
            {
                "evaluation_id": item["evaluation_id"],
                "question_id": item["task"]["question_id"],
                "selected_option": live_option,
                "provenance_id": f"p-{i}",
            }
            for i, item in enumerate(ax["evaluations"])
        ]
        vout = verify(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json=json.dumps(admitted),
            verified_json=json.dumps(verified),
            artifact_identity=SENTINEL_ARTIFACT,
            verification_key_json=json.dumps(key),
            observations_json=json.dumps(observations),
        )
        admitted = vout["admitted"]
        verified = vout["verified"]
    raise AssertionError("expected STOP")


def test_invalid_admission_fail_closed() -> None:
    import pytest

    from smeme.mcp.inquire.handlers import InquireHandlerError

    fixture = compile_golden(fork_g2_graph())
    catalog = _catalog_json(fixture)
    ir = _ir_json(fixture)
    with pytest.raises(InquireHandlerError) as exc:
        admit(
            ir_json=ir,
            worksheet_catalog_json=catalog,
            admitted_json="[]",
            question_id="q1",
            selected_option="NotAnOption",
            provenance_id="p",
        )
    assert exc.value.code == "admission_rejected"
