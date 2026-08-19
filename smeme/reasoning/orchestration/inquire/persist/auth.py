"""Owner-scoped inquiry session loads."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import InquirySession, User
from smeme.mcp.inquire.handlers import InquireHandlerError


async def load_owned_session(
    db: AsyncSession,
    *,
    user: User,
    inquiry_session_id: UUID,
    for_update: bool = False,
) -> InquirySession:
    """Return the session if owned by ``user``; else generic not_found."""
    stmt = select(InquirySession).where(InquirySession.id == inquiry_session_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None or session.owner_user_id != user.id:
        raise InquireHandlerError(
            "not_found",
            "Inquiry session not found, or you are not its owner.",
        )
    return session
