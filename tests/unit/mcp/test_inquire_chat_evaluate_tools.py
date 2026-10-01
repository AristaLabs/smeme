"""MCP evaluate / continue wrappers persist the chat report and honor replay.

The persist-layer settle test drives the facade helpers directly. These tests
call the FastMCP tools in ``reasoning_fastmcp.py`` so a regression in
``persist=`` / ``record_chat_report_issued`` wiring cannot pass silently.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from smeme.core.models import (
    InquiryAdmittedAssertion,
    InquirySession,
    InquirySessionEvent,
    ReasoningEvaluationRun,
)
from smeme.mcp.inquire.chat_facade import CHAT_ISOLATED_VERIFICATION_NOT_RUN
from smeme.mcp.reasoning_fastmcp import get_or_create_fastmcp, reset_mcp_runtime_for_tests
from smeme.reasoning.orchestration.inquire.persist import EVENT_CHAT_REPORT_ISSUED
from tests.unit.reasoning.orchestration.test_inquire_persist import (
    _choice_for,
    _seed_deployed_inquire_tree,
)


def _parse_tool_json(raw: str) -> dict:
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_mcp_evaluate_continue_persists_one_unverified_report_on_replay(
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory,
) -> None:
    try:
        async with test_session_factory() as db:
            await db.execute(text("SELECT 1 FROM inquiry_sessions LIMIT 0"))
    except Exception as exc:  # noqa: BLE001 — skip when persist tables are absent
        pytest.skip(f"Inquire persist DB unavailable: {exc}")

    user, tree, _artifact, _fixture = await _seed_deployed_inquire_tree(test_session_factory)
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp._mcp_auth_user_only",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp._mcp_reserve_quota_and_bind",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "smeme.mcp.reasoning_fastmcp.AsyncSessionLocal",
        test_session_factory,
    )

    reset_mcp_runtime_for_tests()
    try:
        fm = get_or_create_fastmcp()
        tools = fm._tool_manager._tools
        evaluate_fn = tools["smeme_reasoning_evaluate"].fn
        continue_fn = tools["smeme_reasoning_evaluate_continue"].fn
        ctx = MagicMock()

        with patch(
            "smeme.mcp.reasoning_fastmcp.request_from_mcp_context",
            return_value=MagicMock(),
        ):
            started = _parse_tool_json(await evaluate_fn(str(tree.id), ctx))
            assert "error" not in started, started
            assert started.get("harness_next") == "continue_evaluate"
            session_id = UUID(started["inquiry_session_id"])

            last = started
            last_question = started["task"]["question_id"]
            last_option = ""
            last_provenance = ""
            settled = None
            for step in range(8):
                last_question = last["task"]["question_id"]
                async with test_session_factory() as db:
                    row = await db.get(InquirySession, session_id)
                    assert row is not None
                    last_option = _choice_for(row.worksheet_catalog, last_question)
                last_provenance = f"p-mcp-{step}"
                last = _parse_tool_json(
                    await continue_fn(
                        str(session_id),
                        last_question,
                        ctx,
                        selected_option=last_option,
                        provenance_id=last_provenance,
                    )
                )
                assert "error" not in last, last
                if last.get("report") is not None:
                    settled = last
                    break
                assert last.get("harness_next") == "continue_evaluate"
            else:
                raise AssertionError("MCP chat run did not settle")

            assert settled is not None
            assert settled["status"] == "ACTIVE"
            assert settled["stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
            assert settled["inquire_stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
            assert settled["report"]["result_kind"] == "concluded"
            assert settled["report"]["inquire_stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
            assert settled["report"]["inquire_stop_reason"] != "verified_resolved_consequence"
            assert settled["harness_next"] != "continue_evaluate"
            warning_codes = [w.get("code") for w in (settled.get("warnings") or [])]
            assert "inquire_verification_not_run" in warning_codes
            first_run_id = settled.get("evaluation_run_id")
            assert first_run_id

            replay = _parse_tool_json(
                await continue_fn(
                    str(session_id),
                    last_question,
                    ctx,
                    selected_option=last_option,
                    provenance_id=last_provenance,
                )
            )
            assert "error" not in replay, replay
            assert replay["status"] == "ACTIVE"
            assert replay["report"]["inquire_stop_reason"] == CHAT_ISOLATED_VERIFICATION_NOT_RUN
            assert replay["harness_next"] != "continue_evaluate"
    finally:
        reset_mcp_runtime_for_tests()

    async with test_session_factory() as db:
        admitted = await db.scalar(
            select(func.count())
            .select_from(InquiryAdmittedAssertion)
            .where(InquiryAdmittedAssertion.session_id == session_id)
        )
        n_runs = await db.scalar(
            select(func.count())
            .select_from(ReasoningEvaluationRun)
            .where(ReasoningEvaluationRun.decision_tree_id == tree.id)
        )
        n_events = await db.scalar(
            select(func.count())
            .select_from(InquirySessionEvent)
            .where(
                InquirySessionEvent.session_id == session_id,
                InquirySessionEvent.event_type == EVENT_CHAT_REPORT_ISSUED,
            )
        )
        stored = await db.get(ReasoningEvaluationRun, UUID(str(first_run_id)))
        session_row = await db.get(InquirySession, session_id)

    assert int(admitted or 0) == 2
    assert int(n_runs or 0) == 1
    assert int(n_events or 0) == 1
    assert stored is not None
    assert stored.report.get("result_kind") == "concluded"
    assert stored.report.get("inquire_stop_reason") == CHAT_ISOLATED_VERIFICATION_NOT_RUN
    stored_warnings = [w.get("code") for w in (stored.ingest_warnings or [])]
    assert "inquire_verification_not_run" in stored_warnings
    assert session_row is not None
    assert session_row.status == "ACTIVE"
