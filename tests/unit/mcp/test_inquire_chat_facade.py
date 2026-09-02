"""Chat Inquire facade helpers (no DB)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.mcp.inquire import chat_facade as facade
from smeme.mcp.inquire.chat_facade import (
    isolated_evaluations_required_payload,
    merge_chat_stop_onto_apply,
    strip_chat_active_response,
)


def test_chat_admit_idempotency_key_matches_request_hash_identity() -> None:
    from uuid import uuid4

    from smeme.mcp.inquire.chat_facade import chat_admit_idempotency_key
    from smeme.reasoning.orchestration.inquire.persist import canonical_request_hash

    sid = uuid4()
    digest = canonical_request_hash(
        {
            "operation": "admit",
            "inquiry_session_id": str(sid),
            "question_id": "q1",
            "selected_option": "Yes",
            "provenance_id": "p1",
        }
    )
    assert (
        chat_admit_idempotency_key(
            inquiry_session_id=sid,
            question_id="q1",
            selected_option="Yes",
            provenance_id="p1",
        )
        == f"chat-{digest}"
    )


def test_strip_chat_active_response_has_no_control_channel() -> None:
    out = strip_chat_active_response(
        inquiry_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        revision=2,
        status="ACTIVE",
        task={
            "question_id": "q1",
            "stem": "Is it?",
            "options": ["Yes", "No"],
        },
    )
    assert out["harness_next"] == "continue_evaluate"
    assert set(out["task"].keys()) == {"question_id", "stem", "options"}
    assert "directive" not in out
    assert "evaluations" not in out
    assert "pv_version" not in out
    assert "verification_key" not in out
    assert "C_poss" not in out


def test_isolated_evaluations_required_keeps_active_status() -> None:
    out = isolated_evaluations_required_payload(
        inquiry_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        revision=3,
        status="ACTIVE",
    )
    err = out["error"]
    assert err["code"] == "isolated_evaluations_required"
    assert err["status"] == "ACTIVE"
    assert "stop_reason" not in err


def test_merge_chat_stop_onto_apply_flags_operational_budget() -> None:
    merged = merge_chat_stop_onto_apply(
        {
            "report": {"result_kind": "concluded", "headline": "On"},
            "warnings": [],
        },
        inquiry_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        stop_reason="operational_budget",
    )
    assert merged["status"] == "STOPPED"
    assert merged["stop_reason"] == "operational_budget"
    assert merged["inquire_stop_reason"] == "operational_budget"
    assert merged["report"]["result_kind"] == "concluded"
    codes = [w["code"] for w in merged["warnings"]]
    assert "inquire_operational_stop" in codes


def test_merge_chat_stop_onto_apply_flags_resolving_support_incomplete() -> None:
    merged = merge_chat_stop_onto_apply(
        {
            "report": {"result_kind": "concluded", "headline": "On"},
            "warnings": [{"code": "preexisting", "message": "keep me"}],
        },
        inquiry_session_id="bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee",
        stop_reason="resolving_support_incomplete",
    )
    assert merged["status"] == "STOPPED"
    assert merged["stop_reason"] == "resolving_support_incomplete"
    assert merged["inquire_stop_reason"] == "resolving_support_incomplete"
    assert merged["report"]["result_kind"] == "concluded"
    assert merged["report"]["headline"] == "On"
    assert [w["code"] for w in merged["warnings"]] == [
        "preexisting",
        "inquire_operational_stop",
    ]
    assert merged["warnings"][0]["message"] == "keep me"
    warn = merged["warnings"][1]
    assert "resolving_support_incomplete" in warn["message"]
    assert "not an MCP" in warn["message"]
    assert "quota" in warn["message"]


def test_merge_chat_stop_onto_apply_verified_has_no_operational_warning() -> None:
    merged = merge_chat_stop_onto_apply(
        {"report": {"result_kind": "concluded"}, "warnings": []},
        inquiry_session_id="cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee",
        stop_reason="verified_resolved_consequence",
    )
    assert merged["stop_reason"] == "verified_resolved_consequence"
    assert merged["warnings"] == []


@pytest.mark.asyncio
async def test_active_task_or_terminal_verify_does_not_stop() -> None:
    user = MagicMock()
    db = AsyncMock()
    session_id = str(uuid4())
    out = await facade._active_task_or_terminal(
        db,
        user=user,
        wire={
            "inquiry_session_id": session_id,
            "revision": 4,
            "status": "ACTIVE",
            "directive": {"action": "VERIFY", "question_id": "q1"},
            "stop_reason": "should_not_surface",
        },
    )
    assert out["error"]["code"] == "isolated_evaluations_required"
    assert out["error"]["status"] == "ACTIVE"
    assert "stop_reason" not in out["error"]
    assert "report" not in out


@pytest.mark.asyncio
async def test_active_task_or_terminal_stop_marker() -> None:
    user = MagicMock()
    db = AsyncMock()
    session_id = str(uuid4())
    out = await facade._active_task_or_terminal(
        db,
        user=user,
        wire={
            "inquiry_session_id": session_id,
            "revision": 5,
            "status": "STOPPED",
            "directive": {"action": "STOP"},
            "stop_reason": "resolved",
            "admitted": [{"question_id": "q1", "option": "Yes"}],
        },
    )
    assert out["_chat_stop"] is True
    assert out["status"] == "STOPPED"
    assert out["stop_reason"] == "resolved"
    assert "evaluations" not in out


@pytest.mark.asyncio
async def test_active_task_or_terminal_acquire_strips_task() -> None:
    user = MagicMock()
    db = AsyncMock()
    session_id = str(uuid4())
    with patch.object(
        facade,
        "get_task_for_session",
        new=AsyncMock(
            return_value={
                "question_id": "q1",
                "stem": "Stem?",
                "options": ["A", "B"],
                "extra_leaked": True,
            }
        ),
    ):
        out = await facade._active_task_or_terminal(
            db,
            user=user,
            wire={
                "inquiry_session_id": session_id,
                "revision": 1,
                "status": "ACTIVE",
                "directive": {"action": "ACQUIRE", "question_id": "q1"},
                "evaluations": [{"should": "not leak"}],
                "pv_version": "pv-1",
            },
        )
    assert out["harness_next"] == "continue_evaluate"
    assert out["task"] == {
        "question_id": "q1",
        "stem": "Stem?",
        "options": ["A", "B"],
    }
    assert "evaluations" not in out
    assert "pv_version" not in out
