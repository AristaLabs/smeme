"""Inquire MCP codec round-trips and blind-task key invariants."""

from __future__ import annotations

import json

import pytest

from smeme.mcp.inquire.codec import (
    BLIND_TASK_KEYS,
    FORBIDDEN_TASK_KEYS,
    InquireCodecError,
    assert_blind_task_payload,
    decode_admitted,
    decode_budget,
    decode_ir,
    decode_verified,
    decode_wire_observations,
    decode_worksheet_catalog,
    encode_admitted,
    encode_blind_task,
    encode_directive,
    encode_ir,
    encode_verified,
    encode_worksheet_catalog,
)
from smeme.reasoning.ir.serialize import ir_to_json
from smeme.reasoning.orchestration.inquire import DEFAULT_PV_VERSION
from smeme.reasoning.runtime.inquire.types import (
    HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS,
    InquiryDiagnostics,
    InquiryDirective,
)
from tests.unit.reasoning.runtime.inquire_fixtures import (
    SENTINEL_ARTIFACT,
    compile_golden,
    fork_g2_graph,
    sentinel_assertion,
    sentinel_key,
)


def test_blind_task_keys_exclude_forbidden() -> None:
    assert BLIND_TASK_KEYS.isdisjoint(FORBIDDEN_TASK_KEYS)


def test_catalog_and_admitted_roundtrip() -> None:
    fixture = compile_golden(fork_g2_graph())
    catalog_json = json.dumps(encode_worksheet_catalog(fixture.catalog))
    catalog = decode_worksheet_catalog(catalog_json)
    assert catalog["q1"].options == ("Yes", "No")

    admitted = (sentinel_assertion("q1", "Yes"),)
    encoded = encode_admitted(admitted)
    assert decode_admitted(json.dumps(encoded)) == admitted


def test_verified_roundtrip() -> None:
    key = sentinel_key("q1", "Yes", pv_version=DEFAULT_PV_VERSION)
    encoded = encode_verified(frozenset({key}))
    assert decode_verified(json.dumps(encoded)) == frozenset({key})


def test_ir_roundtrip() -> None:
    fixture = compile_golden(fork_g2_graph())
    raw = json.dumps(ir_to_json(fixture.ir))
    ir = decode_ir(raw)
    assert encode_ir(ir) == ir_to_json(fixture.ir)


def test_assert_blind_task_rejects_extra_keys() -> None:
    with pytest.raises(InquireCodecError) as exc:
        assert_blind_task_payload(
            {
                "question_id": "q1",
                "stem": "x",
                "options": ["A"],
                "action": "VERIFY",
            }
        )
    assert exc.value.code == "inquire_invalid_payload"


def test_encode_blind_task_shape() -> None:
    from smeme.reasoning.runtime.inquire import build_extractor_issue

    fixture = compile_golden(fork_g2_graph())
    task = build_extractor_issue(fixture.catalog, "q2")
    payload = encode_blind_task(task)
    assert_blind_task_payload(payload)
    assert set(payload) == BLIND_TASK_KEYS
    blob = json.dumps(payload, sort_keys=True)
    for forbidden in ("VERIFY", "ACQUIRE", "verification_key", "evaluation_id"):
        assert f'"{forbidden}"' not in blob


def test_encode_directive_includes_verify_metadata() -> None:
    key = sentinel_key("q1", "Yes", pv_version=DEFAULT_PV_VERSION)
    directive = InquiryDirective(
        action="VERIFY",
        question_id="q1",
        option="Yes",
        verification_key=key,
    )
    encoded = encode_directive(directive)
    assert encoded["action"] == "VERIFY"
    assert encoded["verification_key"]["pv_version"] == DEFAULT_PV_VERSION
    assert encoded["verification_key"]["artifact_identity"] == SENTINEL_ARTIFACT


def test_budget_codec_accepts_dedicated_support_limits_and_enforces_ceiling() -> None:
    budget = decode_budget(
        json.dumps(
            {
                "max_resolving_support_sat_calls": 4321,
                "resolving_support_timeout_ms": 6789,
            }
        )
    )
    assert budget.max_resolving_support_sat_calls == 4321
    assert budget.resolving_support_timeout_ms == 6789

    with pytest.raises(InquireCodecError, match="max_resolving_support_sat_calls"):
        decode_budget(
            json.dumps(
                {"max_resolving_support_sat_calls": (HARD_MAX_RESOLVING_SUPPORT_SAT_CALLS + 1)}
            )
        )


def test_encode_operational_directive_includes_bounded_diagnostics() -> None:
    directive = InquiryDirective(
        action="STOP",
        stop_reason="resolving_support_incomplete",
        operational_status="budget",
        diagnostics=InquiryDiagnostics(
            phase="resolving_support",
            operational_status="budget",
            sat_calls=2015,
            general_sat_calls=15,
            resolving_support_sat_calls=2000,
            elapsed_ms=123.456,
            max_sat_calls=2000,
            timeout_ms=5000,
            max_resolving_support_sat_calls=2000,
            resolving_support_timeout_ms=5000,
        ),
    )

    encoded = encode_directive(directive)

    assert encoded["operational_status"] == "budget"
    assert encoded["diagnostics"] == {
        "phase": "resolving_support",
        "operational_status": "budget",
        "sat_calls": 2015,
        "general_sat_calls": 15,
        "resolving_support_sat_calls": 2000,
        "elapsed_ms": 123.456,
        "max_sat_calls": 2000,
        "timeout_ms": 5000,
        "max_resolving_support_sat_calls": 2000,
        "resolving_support_timeout_ms": 5000,
    }


def test_decode_wire_observations() -> None:
    raw = json.dumps(
        [
            {
                "evaluation_id": "eval-0",
                "question_id": "q1",
                "selected_option": "Yes",
                "provenance_id": "p1",
            },
            {
                "evaluation_id": "eval-1",
                "question_id": "q1",
                "selected_option": None,
                "provenance_id": None,
            },
        ]
    )
    obs = decode_wire_observations(raw)
    assert len(obs) == 2
    assert obs[0].selected_option == "Yes"
    assert obs[1].selected_option is None
    assert obs[0].presentation is None
