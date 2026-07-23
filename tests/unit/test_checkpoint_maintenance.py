"""Unit tests for checkpoint and wizard telemetry maintenance."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager
from smeme.decision_tree.generation.agentic.maintenance import (
    _wait_for_stop_or_interval,
    periodic_maintenance_loop,
    run_periodic_cleanup,
    run_startup_cleanup,
)
from smeme.decision_tree.generation.agentic.telemetry import delete_wizard_events_older_than


class TestDeleteOrphanedCheckpoints:
    """delete_orphaned_checkpoints behavior."""

    @pytest.mark.asyncio
    async def test_pool_not_initialized_returns_zero(self):
        with patch.object(checkpointer_manager, "_pool", None):
            n = await checkpointer_manager.delete_orphaned_checkpoints()
        assert n == 0

    @pytest.mark.asyncio
    async def test_deletes_from_all_three_tables_with_not_exists(self):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 3
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch.object(checkpointer_manager, "_pool", mock_pool):
            n = await checkpointer_manager.delete_orphaned_checkpoints()

        assert n == 9
        assert mock_conn.execute.call_count == 3
        for call in mock_conn.execute.call_args_list:
            sql = call.args[0]
            assert "NOT EXISTS" in sql
            assert "in_progress_decision_tree_generations" in sql
            assert "langgraph_thread_id" in sql


class TestDeleteWizardEventsOlderThan:
    """Wizard telemetry retention delete."""

    @pytest.mark.asyncio
    async def test_rejects_non_positive_days(self):
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="positive integer"):
            await delete_wizard_events_older_than(mock_db, days=0)

    @pytest.mark.asyncio
    async def test_deletes_with_python_cutoff(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 4
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "smeme.decision_tree.generation.agentic.telemetry.datetime",
        ) as mock_dt:
            fixed_now = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            n = await delete_wizard_events_older_than(mock_db, days=90)

        assert n == 4
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        stmt = mock_db.execute.await_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "wizard_generation_events" in compiled
        assert "created_at" in compiled


class TestRunStartupCleanup:
    """Startup maintenance hook."""

    @pytest.mark.asyncio
    async def test_startup_cleanup_invokes_expired_cleanup(self):
        mock_db = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.AsyncSessionLocal",
                return_value=mock_session,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.checkpoint_manager.cleanup_expired_generations",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_cleanup,
        ):
            deleted = await run_startup_cleanup()

        assert deleted == 0
        mock_cleanup.assert_awaited_once_with(mock_db)


class TestWaitForStopOrInterval:
    """Event-aware wait helper."""

    @pytest.mark.asyncio
    async def test_returns_true_when_stop_event_already_set(self):
        stop_event = asyncio.Event()
        stop_event.set()
        assert await _wait_for_stop_or_interval(stop_event, 3600) is True

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        stop_event = asyncio.Event()
        assert await _wait_for_stop_or_interval(stop_event, 0.01) is False

    @pytest.mark.asyncio
    async def test_returns_true_when_stop_event_set_during_wait(self):
        stop_event = asyncio.Event()

        async def set_soon() -> None:
            await asyncio.sleep(0.01)
            stop_event.set()

        setter = asyncio.create_task(set_soon())
        try:
            assert await _wait_for_stop_or_interval(stop_event, 1.0) is True
        finally:
            await setter


class TestPeriodicMaintenanceLoop:
    """Event-aware periodic loop and shutdown."""

    @pytest.mark.asyncio
    async def test_loop_exits_when_stop_event_set_during_wait(self):
        stop_event = asyncio.Event()
        wait_calls = 0

        async def fake_wait(event: asyncio.Event, seconds: float) -> bool:
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls == 1:
                stop_event.set()
            return stop_event.is_set()

        with (
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.run_periodic_cleanup",
                new_callable=AsyncMock,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance._wait_for_stop_or_interval",
                side_effect=fake_wait,
            ),
        ):
            await periodic_maintenance_loop(stop_event)

    @pytest.mark.asyncio
    async def test_shutdown_pattern_cancel_during_cleanup(self):
        stop_event = asyncio.Event()
        entered_cleanup = asyncio.Event()

        async def slow_cleanup() -> None:
            entered_cleanup.set()
            await asyncio.Event().wait()

        with patch(
            "smeme.decision_tree.generation.agentic.maintenance.run_periodic_cleanup",
            side_effect=slow_cleanup,
        ):
            task = asyncio.create_task(periodic_maintenance_loop(stop_event))
            await entered_cleanup.wait()
            stop_event.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_weekly_orphan_sweep_runs_on_first_periodic_tick(self):
        import smeme.decision_tree.generation.agentic.maintenance as maintenance_mod

        maintenance_mod.last_orphan_sweep_at = None
        mock_db = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.AsyncSessionLocal",
                return_value=mock_session,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.checkpoint_manager.cleanup_expired_generations",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.retry_pending_account_deletions",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_deletion_retry,
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.checkpointer_manager.delete_orphaned_checkpoints",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_orphan,
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.delete_wizard_events_older_than",
                new_callable=AsyncMock,
                return_value=5,
            ) as mock_wizard,
        ):
            result = await run_periodic_cleanup()

        assert result["orphan_checkpoint_rows_deleted"] == 2
        assert result["wizard_events_deleted"] == 5
        assert result["account_deletions_resolved"] == 1
        mock_deletion_retry.assert_awaited_once()
        mock_orphan.assert_awaited_once()
        mock_wizard.assert_awaited_once()
        assert maintenance_mod.last_orphan_sweep_at is not None

    @pytest.mark.asyncio
    async def test_weekly_orphan_sweep_skipped_within_interval(self):
        import smeme.decision_tree.generation.agentic.maintenance as maintenance_mod

        maintenance_mod.last_orphan_sweep_at = datetime.now(UTC) - timedelta(days=1)
        prior_sweep_at = maintenance_mod.last_orphan_sweep_at
        mock_db = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.AsyncSessionLocal",
                return_value=mock_session,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.checkpoint_manager.cleanup_expired_generations",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.retry_pending_account_deletions",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.checkpointer_manager.delete_orphaned_checkpoints",
                new_callable=AsyncMock,
            ) as mock_orphan,
            patch(
                "smeme.decision_tree.generation.agentic.maintenance.delete_wizard_events_older_than",
                new_callable=AsyncMock,
            ) as mock_wizard,
        ):
            result = await run_periodic_cleanup()

        assert result["expired_generations_deleted"] == 1
        assert result["account_deletions_resolved"] == 0
        assert result["orphan_checkpoint_rows_deleted"] == 0
        assert result["wizard_events_deleted"] == 0
        mock_orphan.assert_not_called()
        mock_wizard.assert_not_called()
        assert maintenance_mod.last_orphan_sweep_at == prior_sweep_at
