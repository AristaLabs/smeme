"""Service layer for managing QNR generation workflow sessions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.logging import get_logger
from smeme.qnr.models import InProgressQNRGeneration

from .checkpointer import checkpointer_manager
from .telemetry import track_wizard_abandon

if TYPE_CHECKING:
    from smeme.billing.quota import WizardStartBlock
    from smeme.core.models import User


# ---------------------------------------------------------------------------
# Exceptions raised by start_new_generation
# ---------------------------------------------------------------------------


class WizardStartBlockedError(Exception):
    """Locked quota re-check inside start_new_generation found the wizard is blocked.

    Raised instead of silently returning so callers cannot accidentally ignore
    the result.  ``block`` carries the structured reason the same way
    ``check_wizard_start_block`` does.
    """

    def __init__(self, block: WizardStartBlock) -> None:
        self.block = block
        super().__init__(block.message)


class GenerationConcurrencyError(Exception):
    """Per-user advisory lock was not acquired.

    Means another ``start_new_generation`` call for the same user is currently
    inside its check-then-insert transaction.  The window is milliseconds wide;
    callers should surface a "please try again" message.
    """


_WIZARD_START_LOCK_PREFIX = "wizard_start:"


def _wizard_start_lock_key(user_id: UUID) -> str:
    """Namespaced lock key for the per-user wizard-start advisory lock."""
    return f"{_WIZARD_START_LOCK_PREFIX}{user_id}"


logger = get_logger(__name__)


async def _finish_abandon_cleanup(
    *,
    user_id: UUID,
    thread_id: str,
    phase: str,
    generation_id: UUID,
) -> None:
    """Background: LangGraph checkpoint rows + wizard abandon telemetry."""
    from smeme.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await track_wizard_abandon(
                db,
                user_id=user_id,
                thread_id=thread_id,
                phase=phase,
                reason="user",
                generation_id=generation_id,
            )
        deleted = await checkpointer_manager.delete_checkpoints_for_thread(thread_id)
        logger.info(
            "Deferred abandon cleanup finished",
            extra={
                "thread_id": thread_id,
                "checkpoint_rows_deleted": deleted,
            },
        )
    except Exception:
        logger.exception(
            "Deferred abandon cleanup failed",
            extra={"thread_id": thread_id, "generation_id": str(generation_id)},
        )


class QNRGenerationCheckpointManager:
    """Manages lifecycle of in-progress QNR generation sessions."""

    async def start_new_generation(
        self,
        db: AsyncSession,
        user: User,
        user_prompt: str,
        graph_version: str = "v2",
        ttl_days: int = 7,
    ) -> InProgressQNRGeneration:
        """Atomically gate and create a new in-progress generation record.

        Acquires a per-user Postgres advisory lock (transaction-scoped) before
        re-checking all wizard-start quotas.  Because the lock, the quota
        re-check, and the INSERT all occur inside the same transaction, two
        concurrent requests for the same user cannot both pass the quota check
        and both insert a row — the second request either waits for the first to
        commit (seeing the new in-progress row) or fails fast if the lock cannot
        be acquired.

        Raises:
            GenerationConcurrencyError: Per-user lock was not acquired.
                Another start_new_generation call is mid-transaction for this
                user.  The window is milliseconds; callers should surface a
                "please try again" message.
            WizardStartBlockedError: Locked quota re-check determined the wizard
                cannot start (in_progress cap, workflow cap, or monthly cap hit).
                ``exc.block`` carries the structured WizardStartBlock reason.
        """
        from smeme.billing.quota import check_wizard_start_block

        # ------------------------------------------------------------------ #
        # 1. Acquire per-user advisory lock (transaction-scoped).             #
        #    pg_try_advisory_xact_lock returns immediately: True = acquired,  #
        #    False = another transaction holds the lock.  The lock is          #
        #    released automatically when this transaction commits or rolls     #
        #    back, so there is no risk of a leaked lock.                       #
        # ------------------------------------------------------------------ #
        lock_key = _wizard_start_lock_key(user.id)
        lock_result = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": lock_key},
        )
        if not lock_result.scalar():
            msg = f"Advisory lock not acquired for user {user.id}; another start is in flight."
            raise GenerationConcurrencyError(msg)

        # ------------------------------------------------------------------ #
        # 2. Re-check all quota dimensions while holding the lock.            #
        #    list_user_generations runs in the same transaction, so it sees   #
        #    any in-progress row inserted by a request that committed just     #
        #    before us — exactly the race we are closing.                     #
        # ------------------------------------------------------------------ #
        in_progress = await self.list_user_generations(db=db, user_id=user.id)
        block = await check_wizard_start_block(db, user, in_progress_count=len(in_progress))
        if block:
            raise WizardStartBlockedError(block)

        # ------------------------------------------------------------------ #
        # 3. Insert the in-progress row.  The lock is still held, so no      #
        #    concurrent request can slip past the quota check above until     #
        #    this commit releases it.                                         #
        # ------------------------------------------------------------------ #
        thread_id = str(uuid4())
        prompt_preview = user_prompt[:200]

        generation = InProgressQNRGeneration(
            user_id=user.id,
            langgraph_thread_id=thread_id,
            user_prompt_preview=prompt_preview,
            graph_version=graph_version,
            current_phase="research",
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )

        db.add(generation)
        await db.commit()  # Lock released here
        await db.refresh(generation)

        logger.info(
            "Started new QNR generation",
            extra={
                "user_id": str(user.id),
                "thread_id": thread_id,
                "graph_version": graph_version,
            },
        )

        return generation

    async def get_generation(
        self,
        db: AsyncSession,
        generation_id: UUID,
        user_id: UUID,
    ) -> InProgressQNRGeneration | None:
        """Get an in-progress generation by ID (with user ownership check).

        Args:
            db: Database session
            generation_id: Generation record ID
            user_id: User ID (for ownership verification)

        Returns:
            Generation record or None if not found/not owned by user
        """
        stmt = select(InProgressQNRGeneration).where(
            InProgressQNRGeneration.id == generation_id,
            InProgressQNRGeneration.user_id == user_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_generation_by_thread_id(
        self,
        db: AsyncSession,
        thread_id: str,
    ) -> InProgressQNRGeneration | None:
        """Get an in-progress generation by LangGraph thread ID.

        Args:
            db: Database session
            thread_id: LangGraph thread ID

        Returns:
            Generation record or None if not found
        """
        stmt = select(InProgressQNRGeneration).where(
            InProgressQNRGeneration.langgraph_thread_id == thread_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_user_generations(
        self,
        db: AsyncSession,
        user_id: UUID,
        include_expired: bool = False,
    ) -> list[InProgressQNRGeneration]:
        """List all in-progress generations for a user.

        Args:
            db: Database session
            user_id: User ID
            include_expired: Whether to include expired generations

        Returns:
            List of generation records, newest first
        """
        stmt = (
            select(InProgressQNRGeneration)
            .where(InProgressQNRGeneration.user_id == user_id)
            .order_by(InProgressQNRGeneration.started_at.desc())
        )

        if not include_expired:
            stmt = stmt.where(InProgressQNRGeneration.expires_at > datetime.now(UTC))

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_phase(
        self,
        db: AsyncSession,
        thread_id: str,
        phase: str,
    ) -> None:
        """Update the current phase and checkpoint time.

        Args:
            db: Database session
            thread_id: LangGraph thread ID
            phase: New phase (research|conclusions|design|build)
        """
        generation = await self.get_generation_by_thread_id(db, thread_id)
        if generation:
            generation.current_phase = phase
            generation.update_checkpoint_time()
            await db.commit()

            logger.debug(
                "Updated generation phase",
                extra={
                    "thread_id": thread_id,
                    "phase": phase,
                },
            )

    async def mark_checkpoint(
        self,
        db: AsyncSession,
        thread_id: str,
    ) -> None:
        """Update last_checkpoint_at timestamp.

        Call this after each workflow checkpoint to track activity.

        Args:
            db: Database session
            thread_id: LangGraph thread ID
        """
        generation = await self.get_generation_by_thread_id(db, thread_id)
        if generation:
            generation.update_checkpoint_time()
            await db.commit()

    async def abandon_generation(
        self,
        db: AsyncSession,
        generation_id: UUID,
        user_id: UUID,
        *,
        defer_heavy_cleanup: bool = False,
    ) -> bool:
        """User-initiated delete: remove in-progress row; optionally defer checkpoint purge."""
        generation = await self.get_generation(db, generation_id, user_id)
        if not generation:
            return False

        thread_id = generation.langgraph_thread_id
        phase = generation.current_phase
        gen_id = generation.id

        stmt = delete(InProgressQNRGeneration).where(
            InProgressQNRGeneration.langgraph_thread_id == thread_id
        )
        await db.execute(stmt)
        await db.commit()

        if defer_heavy_cleanup:
            asyncio.create_task(
                _finish_abandon_cleanup(
                    user_id=user_id,
                    thread_id=thread_id,
                    phase=phase,
                    generation_id=gen_id,
                )
            )
        else:
            await track_wizard_abandon(
                db,
                user_id=user_id,
                thread_id=thread_id,
                phase=phase,
                reason="user",
                generation_id=gen_id,
            )
            await checkpointer_manager.delete_checkpoints_for_thread(thread_id)

        logger.info(
            "User abandoned in-progress generation",
            extra={
                "user_id": str(user_id),
                "generation_id": str(generation_id),
                "thread_id": thread_id,
                "deferred_cleanup": defer_heavy_cleanup,
            },
        )
        return True

    async def complete_generation(
        self,
        db: AsyncSession,
        thread_id: str,
    ) -> None:
        """Delete generation record and LangGraph checkpoints after successful completion.

        Args:
            db: Database session
            thread_id: LangGraph thread ID
        """
        stmt = delete(InProgressQNRGeneration).where(
            InProgressQNRGeneration.langgraph_thread_id == thread_id
        )
        await db.execute(stmt)
        await db.commit()

        deleted = await checkpointer_manager.delete_checkpoints_for_thread(thread_id)
        logger.info(
            "Completed and cleaned up generation",
            extra={"thread_id": thread_id, "checkpoint_rows_deleted": deleted},
        )

    async def cleanup_expired_generations(
        self,
        db: AsyncSession,
        grace_period_minutes: int = 60,
    ) -> int:
        """Clean up expired or stale generations and their LangGraph checkpoints.

        Args:
            db: Database session
            grace_period_minutes: Don't delete if checkpointed within this window

        Returns:
            Number of generations deleted
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=grace_period_minutes)

        stale_stmt = select(InProgressQNRGeneration).where(
            (InProgressQNRGeneration.expires_at < datetime.now(UTC))
            | (InProgressQNRGeneration.last_checkpoint_at < cutoff_time)
        )
        stale_result = await db.execute(stale_stmt)
        stale_generations = list(stale_result.scalars().all())

        thread_ids = [g.langgraph_thread_id for g in stale_generations]

        for generation in stale_generations:
            reason = "expired" if generation.is_expired() else "stale"
            await track_wizard_abandon(
                db,
                user_id=generation.user_id,
                thread_id=generation.langgraph_thread_id,
                phase=generation.current_phase,
                reason=reason,
                generation_id=generation.id,
            )

        for tid in thread_ids:
            await checkpointer_manager.delete_checkpoints_for_thread(tid)

        stmt = delete(InProgressQNRGeneration).where(
            (InProgressQNRGeneration.expires_at < datetime.now(UTC))
            | (InProgressQNRGeneration.last_checkpoint_at < cutoff_time)
        )
        result = await db.execute(stmt)
        await db.commit()

        deleted_count = result.rowcount

        if deleted_count > 0:
            logger.info(
                "Cleaned up expired generations",
                extra={"count": deleted_count, "thread_ids": thread_ids},
            )

        return deleted_count


# Global instance
checkpoint_manager = QNRGenerationCheckpointManager()
