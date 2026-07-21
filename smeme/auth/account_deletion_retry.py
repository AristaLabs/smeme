"""Retry sweeper for failed account deletion purges."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.auth.account_delete import (
    AccountDeletionLockError,
    AccountDeletionPurgeError,
    DeleteAccountStatus,
    delete_user_account,
)
from smeme.core.logging import get_logger
from smeme.core.models import AccountDeletionFailure, User

logger = get_logger(__name__)

MAX_SWEEPER_ATTEMPTS = 10


async def retry_pending_account_deletions(db: AsyncSession, *, limit: int = 20) -> int:
    """Re-run purge for unresolved ``account_deletion_failures`` rows.

    Returns the number of rows resolved. Intended for cron / ops script.
    """
    rows = (
        (
            await db.execute(
                select(AccountDeletionFailure)
                .where(AccountDeletionFailure.resolved_at.is_(None))
                .where(AccountDeletionFailure.attempt_count < MAX_SWEEPER_ATTEMPTS)
                .order_by(AccountDeletionFailure.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    resolved = 0
    touched = 0
    for failure in rows:
        user: User | None = None
        if failure.user_id:
            user = (
                await db.execute(select(User).where(User.id == failure.user_id))
            ).scalar_one_or_none()
        if user is None and failure.clerk_user_id:
            user = (
                await db.execute(select(User).where(User.clerk_user_id == failure.clerk_user_id))
            ).scalar_one_or_none()

        if user is None:
            failure.resolved_at = datetime.now(UTC)
            failure.error_message = "user_row_gone"
            db.add(failure)
            resolved += 1
            touched += 1
            continue

        try:
            outcome = await delete_user_account(db, user, actor="clerk_webhook")
            if outcome.status in (DeleteAccountStatus.DELETED, DeleteAccountStatus.ALREADY_DELETED):
                failure.resolved_at = datetime.now(UTC)
                db.add(failure)
                resolved += 1
                touched += 1
        except (AccountDeletionLockError, AccountDeletionPurgeError) as exc:
            failure.attempt_count += 1
            failure.error_message = str(exc)[:2000]
            db.add(failure)
            touched += 1
            logger.warning(
                "account_deletion_retry: still failing failure_id=%s attempts=%s",
                failure.id,
                failure.attempt_count,
            )

    if touched:
        await db.commit()
    return resolved
