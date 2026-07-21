"""Background maintenance: agentic checkpoints, wizard telemetry, account-deletion retry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from smeme.auth.account_deletion_retry import retry_pending_account_deletions
from smeme.core.database import AsyncSessionLocal
from smeme.core.logging import get_logger
from smeme.qnr.generation.agentic.checkpointer import checkpointer_manager
from smeme.qnr.generation.agentic.services import checkpoint_manager
from smeme.qnr.generation.agentic.telemetry import delete_wizard_events_older_than

logger = get_logger(__name__)

PERIODIC_INTERVAL_SECONDS = 24 * 3600
ORPHAN_SWEEP_INTERVAL = timedelta(days=7)
WIZARD_EVENTS_RETENTION_DAYS = 90

last_orphan_sweep_at: datetime | None = None


async def _wait_for_stop_or_interval(stop_event: asyncio.Event, seconds: float) -> bool:
    """Wait up to ``seconds`` or until ``stop_event`` is set.

    Returns:
        True if ``stop_event`` was set (shutdown requested), False on timeout.
    """
    if stop_event.is_set():
        return True
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


async def run_startup_cleanup() -> int:
    """Run expired-generation cleanup once at app startup."""
    async with AsyncSessionLocal() as db:
        deleted = await checkpoint_manager.cleanup_expired_generations(db)

    logger.info(
        "Startup checkpoint maintenance completed",
        extra={"expired_generations_deleted": deleted},
    )
    return deleted


async def run_periodic_cleanup() -> dict[str, int]:
    """Daily tick: expired generations, account-deletion retry; weekly orphan checkpoints + wizard retention."""
    global last_orphan_sweep_at

    async with AsyncSessionLocal() as db:
        expired_generations_deleted = await checkpoint_manager.cleanup_expired_generations(db)

    account_deletions_resolved = 0
    async with AsyncSessionLocal() as db:
        account_deletions_resolved = await retry_pending_account_deletions(db)

    orphan_checkpoint_rows_deleted = 0
    wizard_events_deleted = 0

    now = datetime.now(UTC)
    run_orphan_sweep = (
        last_orphan_sweep_at is None or (now - last_orphan_sweep_at) >= ORPHAN_SWEEP_INTERVAL
    )

    if run_orphan_sweep:
        orphan_checkpoint_rows_deleted = await checkpointer_manager.delete_orphaned_checkpoints()
        async with AsyncSessionLocal() as db:
            wizard_events_deleted = await delete_wizard_events_older_than(
                db,
                days=WIZARD_EVENTS_RETENTION_DAYS,
            )
        last_orphan_sweep_at = now

    logger.info(
        "Periodic checkpoint maintenance completed",
        extra={
            "expired_generations_deleted": expired_generations_deleted,
            "account_deletions_resolved": account_deletions_resolved,
            "orphan_checkpoint_rows_deleted": orphan_checkpoint_rows_deleted,
            "wizard_events_deleted": wizard_events_deleted,
        },
    )

    return {
        "expired_generations_deleted": expired_generations_deleted,
        "account_deletions_resolved": account_deletions_resolved,
        "orphan_checkpoint_rows_deleted": orphan_checkpoint_rows_deleted,
        "wizard_events_deleted": wizard_events_deleted,
    }


async def periodic_maintenance_loop(stop_event: asyncio.Event) -> None:
    """Event-aware maintenance loop (24h between ticks unless shutdown)."""
    while not stop_event.is_set():
        await run_periodic_cleanup()
        if await _wait_for_stop_or_interval(stop_event, PERIODIC_INTERVAL_SECONDS):
            break
