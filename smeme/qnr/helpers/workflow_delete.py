"""Permanent workflow (version family) deletion."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import QNR, Memo, QNRSession
from smeme.qnr.helpers.db_queries import get_version_family_from_db

DELETE_CONFIRM_PHRASE = "delete workflow permanently"

__all__ = ["DELETE_CONFIRM_PHRASE", "delete_workflow_family"]


async def delete_workflow_family(
    db: AsyncSession,
    qnr: QNR,
    *,
    author_id: UUID,
) -> list[QNR]:
    """
    Hard-delete an entire QNR version family and related author-owned session data.

    Removes memos and sessions explicitly (no CASCADE on ``qnr_sessions.qnr_id``).
    Reasoning artifacts, corpora, lexicon drafts, and evaluation runs CASCADE from ``qnrs``.

    Returns the deleted family members (for logging / flash messages).
    """
    if qnr.author_id != author_id:
        raise PermissionError("Not authorized to delete this workflow")

    family = await get_version_family_from_db(db, qnr)
    family_ids = [v.id for v in family]

    session_result = await db.execute(
        select(QNRSession.id).where(QNRSession.qnr_id.in_(family_ids))
    )
    session_ids = [row[0] for row in session_result.all()]

    if session_ids:
        await db.execute(delete(Memo).where(Memo.session_id.in_(session_ids)))

    await db.execute(delete(QNRSession).where(QNRSession.qnr_id.in_(family_ids)))

    # Break parent links so all family rows can be removed in one statement.
    await db.execute(update(QNR).where(QNR.id.in_(family_ids)).values(parent_qnr_id=None))
    await db.execute(delete(QNR).where(QNR.id.in_(family_ids)))

    return family
