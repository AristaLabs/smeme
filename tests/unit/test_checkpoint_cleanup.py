"""Unit tests for checkpoint cleanup (§4.8).

Per docs/planning/decision_tree-generation-ux-refinement.md §9.3.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager
from smeme.decision_tree.generation.agentic.services import checkpoint_manager


class TestDeleteCheckpointsForThread:
    """delete_checkpoints_for_thread behavior."""

    @pytest.mark.asyncio
    async def test_pool_not_initialized_returns_zero(self):
        """When pool is None, returns 0 without raising."""
        with patch.object(checkpointer_manager, "_pool", None):
            n = await checkpointer_manager.delete_checkpoints_for_thread("thread-123")
        assert n == 0

    @pytest.mark.asyncio
    async def test_deletes_all_three_tables(self):
        """Deletes from checkpoint_blobs, checkpoint_writes, checkpoints."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 2
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_pool = AsyncMock()
        mock_pool.connection = MagicMock(return_value=mock_conn)

        with patch.object(checkpointer_manager, "_pool", mock_pool):
            n = await checkpointer_manager.delete_checkpoints_for_thread("tid-456")

        assert n == 6  # 2 rows × 3 tables
        assert mock_conn.execute.call_count == 3


class TestAbandonGeneration:
    """User-initiated abandon from dashboard."""

    @pytest.mark.asyncio
    async def test_abandon_not_found_returns_false(self):
        mock_db = AsyncMock()
        with patch.object(
            checkpoint_manager, "get_generation", new_callable=AsyncMock, return_value=None
        ):
            ok = await checkpoint_manager.abandon_generation(
                mock_db, generation_id=MagicMock(), user_id=MagicMock()
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_abandon_tracks_and_cleans_up(self):
        mock_db = AsyncMock()
        gen = MagicMock()
        gen.id = MagicMock()
        gen.langgraph_thread_id = "thread-abandon-1"
        gen.current_phase = "research"
        user_id = MagicMock()

        with (
            patch.object(
                checkpoint_manager, "get_generation", new_callable=AsyncMock, return_value=gen
            ),
            patch(
                "smeme.decision_tree.generation.agentic.services.checkpointer_manager.delete_checkpoints_for_thread",
                new_callable=AsyncMock,
            ) as mock_del,
            patch(
                "smeme.decision_tree.generation.agentic.services.track_wizard_abandon",
                new_callable=AsyncMock,
            ) as mock_abandon,
        ):
            ok = await checkpoint_manager.abandon_generation(
                mock_db, generation_id=gen.id, user_id=user_id
            )

        assert ok is True
        mock_abandon.assert_awaited_once()
        mock_del.assert_awaited_once_with("thread-abandon-1")
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_abandon_deferred_skips_inline_checkpoint_delete(self):
        mock_db = AsyncMock()
        gen = MagicMock()
        gen.id = MagicMock()
        gen.langgraph_thread_id = "thread-defer-1"
        gen.current_phase = "design"
        user_id = MagicMock()

        with (
            patch.object(
                checkpoint_manager, "get_generation", new_callable=AsyncMock, return_value=gen
            ),
            patch(
                "smeme.decision_tree.generation.agentic.services._finish_abandon_cleanup",
                new_callable=AsyncMock,
            ),
            patch(
                "smeme.decision_tree.generation.agentic.services.asyncio.create_task",
                return_value=None,
            ) as mock_task,
            patch(
                "smeme.decision_tree.generation.agentic.services.track_wizard_abandon",
                new_callable=AsyncMock,
            ) as mock_abandon,
            patch(
                "smeme.decision_tree.generation.agentic.services.checkpointer_manager.delete_checkpoints_for_thread",
                new_callable=AsyncMock,
            ) as mock_del,
        ):
            ok = await checkpoint_manager.abandon_generation(
                mock_db,
                generation_id=gen.id,
                user_id=user_id,
                defer_heavy_cleanup=True,
            )

        assert ok is True
        mock_abandon.assert_not_called()
        mock_del.assert_not_called()
        mock_task.assert_called_once()


class TestCompleteGenerationCallsCheckpointCleanup:
    """complete_generation triggers checkpoint cleanup."""

    @pytest.mark.asyncio
    async def test_complete_generation_calls_delete_checkpoints(self):
        """complete_generation calls delete_checkpoints_for_thread after DB delete."""
        mock_db = AsyncMock()
        thread_id = "test-thread-xyz"

        with patch.object(
            checkpointer_manager, "delete_checkpoints_for_thread", new_callable=AsyncMock
        ) as mock_del:
            mock_del.return_value = 5

            # Patch at the point of use so our mock gets called
            with patch(
                "smeme.decision_tree.generation.agentic.services.checkpointer_manager",
                checkpointer_manager,
            ):
                user_id = uuid4()
                owned = MagicMock()
                with patch.object(
                    checkpoint_manager,
                    "get_generation_by_thread_id",
                    new_callable=AsyncMock,
                    return_value=owned,
                ):
                    await checkpoint_manager.complete_generation(
                        mock_db, thread_id, user_id=user_id
                    )

            mock_del.assert_called_once_with(thread_id)


class TestCleanupExpiredCallsCheckpointCleanup:
    """cleanup_expired_generations triggers checkpoint cleanup per thread."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_calls_delete_per_thread(self):
        """For each expired generation, delete_checkpoints_for_thread is called."""
        mock_db = AsyncMock()
        call_count = [0]

        gen1 = MagicMock()
        gen1.langgraph_thread_id = "expired-1"
        gen1.user_id = "user-1"
        gen1.current_phase = "research"
        gen1.id = "gen-1"
        gen1.is_expired.return_value = True

        gen2 = MagicMock()
        gen2.langgraph_thread_id = "expired-2"
        gen2.user_id = "user-2"
        gen2.current_phase = "design"
        gen2.id = "gen-2"
        gen2.is_expired.return_value = True

        async def mock_execute(stmt):
            call_count[0] += 1
            if call_count[0] == 1:
                r = MagicMock()
                r.scalars.return_value.all.return_value = [gen1, gen2]
                return r
            r = MagicMock()
            r.rowcount = 2
            return r

        mock_db.execute = mock_execute

        with patch.object(
            checkpointer_manager, "delete_checkpoints_for_thread", new_callable=AsyncMock
        ) as mock_del, patch(
            "smeme.decision_tree.generation.agentic.services.track_wizard_abandon",
            new_callable=AsyncMock,
        ):
            mock_del.return_value = 0
            deleted = await checkpoint_manager.cleanup_expired_generations(
                mock_db, grace_period_minutes=60
            )

        assert deleted == 2
        assert mock_del.call_count == 2
        mock_del.assert_any_call("expired-1")
        mock_del.assert_any_call("expired-2")
