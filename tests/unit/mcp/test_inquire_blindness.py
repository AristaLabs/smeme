"""Serialized G9 blindness for Inquire MCP task payloads."""

from __future__ import annotations

import inspect
import json

from smeme.mcp.inquire import get_task
from smeme.mcp.inquire.codec import (
    FORBIDDEN_TASK_KEYS,
    assert_blind_task_payload,
    encode_worksheet_catalog,
)
from smeme.mcp.inquire.handlers import analyze
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.orchestration.inquire import DEFAULT_PV_VERSION
from smeme.mcp.inquire.codec import encode_admitted, encode_verified
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    compile_golden,
    fork_g2_graph,
    sentinel_assertion,
)


def _catalog_json(fixture) -> str:
    return json.dumps(encode_worksheet_catalog(fixture.catalog))


def test_get_task_signature_has_no_ir() -> None:
    params = inspect.signature(get_task).parameters
    assert "ir_json" not in params
    assert set(params) == {"worksheet_catalog_json", "question_id"}


def test_get_task_json_only_blind_fields() -> None:
    fixture = compile_golden(fork_g2_graph())
    payload = get_task(
        worksheet_catalog_json=_catalog_json(fixture),
        question_id="q2",
    )
    assert_blind_task_payload(payload)
    blob = json.dumps(payload, sort_keys=True)
    for key in FORBIDDEN_TASK_KEYS:
        assert f'"{key}"' not in blob


def test_eval0_task_equals_get_task_at_json_level() -> None:
    fixture = compile_golden(fork_g2_graph())
    # Admit resolving path until VERIFY for q1 (first in S_R after empty → ACQUIRE q1).
    admitted = (sentinel_assertion("q1", "Yes"), sentinel_assertion("q2", "B"))
    out = analyze(
        ir_json=json.dumps(ir_to_json(fixture.ir)),
        worksheet_catalog_json=_catalog_json(fixture),
        admitted_json=json.dumps(encode_admitted(admitted)),
        verified_json=json.dumps(encode_verified(frozenset())),
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert out["directive"]["action"] == "VERIFY"
    qid = out["directive"]["question_id"]
    evaluations = out["evaluations"]
    assert evaluations[0]["evaluation_id"] == "eval-0"
    task0 = evaluations[0]["task"]
    assert_blind_task_payload(task0)
    catalog_task = get_task(
        worksheet_catalog_json=_catalog_json(fixture),
        question_id=qid,
    )
    assert json.dumps(task0, sort_keys=True) == json.dumps(catalog_task, sort_keys=True)


def test_verify_battery_tasks_forbid_control_keys() -> None:
    fixture = compile_golden(fork_g2_graph())
    admitted = (sentinel_assertion("q1", "Yes"), sentinel_assertion("q2", "B"))
    out = analyze(
        ir_json=json.dumps(ir_to_json(fixture.ir)),
        worksheet_catalog_json=_catalog_json(fixture),
        admitted_json=json.dumps(encode_admitted(admitted)),
        verified_json=json.dumps(encode_verified(frozenset())),
        artifact_identity=SENTINEL_ARTIFACT,
    )
    assert out["directive"]["action"] == "VERIFY"
    assert out["pv_version"] == DEFAULT_PV_VERSION
    for item in out["evaluations"]:
        assert "evaluation_id" in item
        assert_blind_task_payload(item["task"])
        assert "evaluation_id" not in item["task"]
        blob = json.dumps(item["task"], sort_keys=True)
        for forbidden in ("VERIFY", "ACQUIRE", "verification_key", "pv_version"):
            assert f'"{forbidden}"' not in blob
