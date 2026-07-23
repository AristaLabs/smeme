"""Hard-delete user account and owned data (see docs/planning/account-deletion-flow.md)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from clerk_backend_api import Clerk
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.billing.providers import cancel_subscription_if_needed
from smeme.core.config import settings
from smeme.core.logging import get_logger
from smeme.core.models import DecisionTree, DecisionTreeSession, Memo, User, UserAuditLog
from smeme.decision_tree.generation.agentic.checkpointer import checkpointer_manager
from smeme.decision_tree.helpers.workflow_delete import delete_workflow_family
from smeme.decision_tree.models import InProgressDecisionTreeGeneration

logger = get_logger(__name__)

DELETE_ACCOUNT_CONFIRM_PHRASE = "delete my account permanently"

_LOCK_PREFIX = "account_delete:"


class AccountDeletionLockError(Exception):
    """Phase B try-lock not acquired for this user."""


class AccountDeletionPurgeError(Exception):
    """Relational purge failed; local user data may still exist."""


class DeleteAccountStatus(str, Enum):
    DELETED = "deleted"
    ALREADY_DELETED = "already_deleted"


@dataclass(frozen=True, slots=True)
class DeleteAccountResult:
    status: DeleteAccountStatus


def phrase_matches(user_input: str, canonical: str = DELETE_ACCOUNT_CONFIRM_PHRASE) -> bool:
    return user_input.strip().casefold() == canonical.strip().casefold()


def should_delete_clerk_identity(actor: str) -> bool:
    return actor in ("profile", "admin")


async def _try_account_delete_lock(db: AsyncSession, user_id: UUID) -> bool:
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"{_LOCK_PREFIX}{user_id}"},
    )
    return bool(result.scalar())


async def _purge_checkpoints_for_user(db: AsyncSession, user_id: UUID) -> None:
    rows = (
        (
            await db.execute(
                select(InProgressDecisionTreeGeneration).where(
                    InProgressDecisionTreeGeneration.user_id == user_id
                )
            )
        )
        .scalars()
        .all()
    )
    for generation in rows:
        try:
            deleted = await checkpointer_manager.delete_checkpoints_for_thread(
                generation.langgraph_thread_id
            )
            logger.info(
                "account_delete: checkpoint purge thread_id=%s rows=%s user_id=%s",
                generation.langgraph_thread_id,
                deleted,
                user_id,
            )
        except Exception as exc:
            logger.warning(
                "account_delete: checkpoint purge failed thread_id=%s user_id=%s: %s",
                generation.langgraph_thread_id,
                user_id,
                exc,
            )
    if rows:
        await db.execute(
            delete(InProgressDecisionTreeGeneration).where(
                InProgressDecisionTreeGeneration.user_id == user_id
            )
        )


async def _purge_workflows(db: AsyncSession, user_id: UUID) -> None:
    roots = (
        (
            await db.execute(
                select(DecisionTree).where(
                    DecisionTree.author_id == user_id,
                    DecisionTree.parent_decision_tree_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for root in roots:
        await delete_workflow_family(db, root, author_id=user_id)


async def _purge_orphan_sessions(db: AsyncSession, user_id: UUID) -> None:
    session_ids = (
        (
            await db.execute(
                select(DecisionTreeSession.id).where(DecisionTreeSession.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    if not session_ids:
        return
    await db.execute(delete(Memo).where(Memo.session_id.in_(session_ids)))
    await db.execute(delete(DecisionTreeSession).where(DecisionTreeSession.user_id == user_id))


async def _redact_audit_log(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(UserAuditLog)
        .where(UserAuditLog.user_id == user_id)
        .values(event_metadata={"redacted": True})
    )


def _deletion_reason(actor: str) -> str:
    return {
        "profile": "user_initiated",
        "clerk_webhook": "clerk_user_deleted",
        "admin": "admin_initiated",
    }.get(actor, actor)


async def _insert_account_deleted_audit(
    db: AsyncSession,
    user: User,
    *,
    actor: str,
    stripe_cancelled: bool,
) -> None:
    metadata: dict[str, str | bool] = {}
    if user.clerk_user_id:
        metadata["clerk_user_id"] = user.clerk_user_id
    if stripe_cancelled:
        metadata["stripe_cancelled"] = True
    db.add(
        UserAuditLog(
            user_id=user.id,
            event_type="account.deleted",
            actor=actor,
            reason=_deletion_reason(actor),
            event_metadata=metadata,
        )
    )


async def _purge_user_relational_data(
    db: AsyncSession,
    user: User,
    *,
    actor: str,
    stripe_cancelled: bool,
) -> None:
    await _purge_checkpoints_for_user(db, user.id)
    await _purge_workflows(db, user.id)
    await _purge_orphan_sessions(db, user.id)
    await _redact_audit_log(db, user.id)
    await _insert_account_deleted_audit(db, user, actor=actor, stripe_cancelled=stripe_cancelled)


async def _delete_clerk_user(clerk_user_id: str) -> None:
    if not settings.clerk_secret_key:
        logger.warning(
            "account_delete: cannot delete Clerk user %s — CLERK_SECRET_KEY not configured",
            clerk_user_id,
        )
        return
    clerk = Clerk(bearer_auth=settings.clerk_secret_key)
    try:
        await clerk.users.delete_async(user_id=clerk_user_id)
        logger.info("account_delete: deleted Clerk user %s", clerk_user_id)
    except Exception as exc:
        logger.error(
            "account_delete: Clerk delete failed for %s: %s — record for ops retry",
            clerk_user_id,
            exc,
        )
        raise


async def record_account_deletion_failure(
    *,
    user_id: UUID | None,
    clerk_user_id: str | None,
    error_message: str,
) -> None:
    """Persist dead-letter row on its own session (caller may have rolled back)."""
    from smeme.core.database import AsyncSessionLocal
    from smeme.core.models import AccountDeletionFailure

    try:
        async with AsyncSessionLocal() as session:
            existing = None
            if clerk_user_id:
                result = await session.execute(
                    select(AccountDeletionFailure)
                    .where(
                        AccountDeletionFailure.clerk_user_id == clerk_user_id,
                        AccountDeletionFailure.resolved_at.is_(None),
                    )
                    .limit(1)
                )
                existing = result.scalar_one_or_none()

            if existing:
                existing.attempt_count += 1
                existing.error_message = error_message[:2000]
                session.add(existing)
            else:
                session.add(
                    AccountDeletionFailure(
                        user_id=user_id,
                        clerk_user_id=clerk_user_id,
                        error_message=error_message[:2000],
                        attempt_count=1,
                    )
                )
            await session.commit()
    except Exception:
        logger.exception(
            "account_delete: could not record deletion failure user_id=%s clerk_user_id=%s",
            user_id,
            clerk_user_id,
        )


async def _phase_b_purge(
    db: AsyncSession,
    user_id: UUID,
    *,
    actor: str,
    stripe_cancelled: bool,
) -> DeleteAccountStatus:
    if not await _try_account_delete_lock(db, user_id):
        raise AccountDeletionLockError(user_id)

    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    locked_user = result.scalar_one_or_none()
    if locked_user is None:
        return DeleteAccountStatus.ALREADY_DELETED

    await _purge_user_relational_data(
        db,
        locked_user,
        actor=actor,
        stripe_cancelled=stripe_cancelled,
    )
    await db.delete(locked_user)
    return DeleteAccountStatus.DELETED


async def delete_user_account(
    db: AsyncSession,
    user: User,
    *,
    actor: str,
    external_side_effects: bool = True,
) -> DeleteAccountResult:
    """Phase A → B → C account closure pipeline.

    See ``docs/planning/account-deletion-flow.md``.
    """
    user_id = user.id
    clerk_user_id = user.clerk_user_id
    stripe_cancelled = False

    if external_side_effects:
        stripe_cancelled = await cancel_subscription_if_needed(user)

    try:
        if db.in_transaction():
            async with db.begin_nested():
                status = await _phase_b_purge(
                    db, user_id, actor=actor, stripe_cancelled=stripe_cancelled
                )
            await db.commit()
        else:
            async with db.begin():
                status = await _phase_b_purge(
                    db, user_id, actor=actor, stripe_cancelled=stripe_cancelled
                )
    except AccountDeletionLockError:
        raise
    except Exception as exc:
        logger.exception("account_delete: purge failed user_id=%s actor=%s", user_id, actor)
        await record_account_deletion_failure(
            user_id=user_id,
            clerk_user_id=clerk_user_id,
            error_message=str(exc),
        )
        raise AccountDeletionPurgeError(str(exc)) from exc

    if status == DeleteAccountStatus.ALREADY_DELETED:
        return DeleteAccountResult(status=DeleteAccountStatus.ALREADY_DELETED)

    if should_delete_clerk_identity(actor) and clerk_user_id:
        try:
            await _delete_clerk_user(clerk_user_id)
        except Exception:
            await record_account_deletion_failure(
                user_id=None,
                clerk_user_id=clerk_user_id,
                error_message="clerk_api_delete_failed",
            )

    logger.info("account_delete: completed user_id=%s actor=%s", user_id, actor)
    return DeleteAccountResult(status=DeleteAccountStatus.DELETED)
