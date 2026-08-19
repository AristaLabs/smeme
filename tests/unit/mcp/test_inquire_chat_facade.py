"""Chat Inquire facade helpers (no DB)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.mcp.inquire import chat_facade as facade
from smeme.mcp.inquire.chat_facade import (
    isolated_evaluations_required_payload,
    strip_chat_active_response,
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
