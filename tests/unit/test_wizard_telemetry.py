"""Unit tests for wizard generation telemetry (Spike 1)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from smeme.qnr.generation.agentic import telemetry


class TestRecordWizardEvent:
    @pytest.mark.asyncio
    async def test_persists_event(self):
        db = AsyncMock()
        user_id = uuid4()
        await telemetry.record_wizard_event(
            db,
            user_id=user_id,
            event_type="wizard.phase.submit",
            phase="research",
            thread_id="thread-1",
            duration_ms=1200,
            metadata={"action": "continue"},
        )
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        event = db.add.call_args[0][0]
        assert event.user_id == user_id
        assert event.event_type == "wizard.phase.submit"
        assert event.phase == "research"
        assert event.duration_ms == 1200
        assert event.event_metadata["action"] == "continue"


class TestGetDropOffReport:
    @pytest.mark.asyncio
    async def test_funnel_and_spike2_gate_not_ready(self):
        db = AsyncMock()
        now = datetime.now(UTC)

        counts_rows = [
            MagicMock(event_type="wizard.phase.enter", phase="brief", count=10),
            MagicMock(event_type="wizard.phase.submit", phase="brief", count=8),
            MagicMock(event_type="wizard.phase.enter", phase="research", count=8),
            MagicMock(event_type="wizard.phase.submit", phase="research", count=5),
            MagicMock(event_type="wizard.complete", phase="complete", count=2),
        ]
        latency_rows = [
            MagicMock(phase="brief", avg_ms=1500.0, max_ms=3000, samples=8),
        ]

        execute_results = [
            MagicMock(all=MagicMock(return_value=counts_rows)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=now - timedelta(days=2))),
            MagicMock(all=MagicMock(return_value=latency_rows)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        report = await telemetry.get_drop_off_report(db)

        brief = next(r for r in report["funnel_by_phase"] if r["phase"] == "brief")
        assert brief["enters"] == 10
        assert brief["submits"] == 8
        assert brief["drop_off"] == 2
        assert brief["drop_off_pct"] == 20.0

        research = next(r for r in report["funnel_by_phase"] if r["phase"] == "research")
        assert research["enters"] == 8
        assert research["submits"] == 5

        assert report["completions"] == 2
        assert report["spike2_gate"]["ready_to_re_rank"] is False
        assert report["spike2_gate"]["completions"] == 2
        assert report["spike2_gate"]["days_collecting"] == 2

    @pytest.mark.asyncio
    async def test_spike2_gate_ready_by_completions(self):
        db = AsyncMock()
        now = datetime.now(UTC)

        counts_rows = [
            MagicMock(event_type="wizard.complete", phase="complete", count=50),
        ]

        execute_results = [
            MagicMock(all=MagicMock(return_value=counts_rows)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=now - timedelta(days=1))),
            MagicMock(all=MagicMock(return_value=[])),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        report = await telemetry.get_drop_off_report(db)
        assert report["spike2_gate"]["ready_to_re_rank"] is True

    @pytest.mark.asyncio
    async def test_spike2_gate_ready_by_days(self):
        db = AsyncMock()
        now = datetime.now(UTC)

        execute_results = [
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(scalar_one_or_none=MagicMock(return_value=now - timedelta(days=7))),
            MagicMock(all=MagicMock(return_value=[])),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        report = await telemetry.get_drop_off_report(db)
        assert report["spike2_gate"]["ready_to_re_rank"] is True


class TestWizardPhaseTimer:
    def test_duration_ms_non_negative(self):
        timer = telemetry.WizardPhaseTimer()
        assert timer.duration_ms >= 0
