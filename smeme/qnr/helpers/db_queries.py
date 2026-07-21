"""Database query helpers for QNR operations."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from smeme.core.models import QNR, QnrResearchCorpus, QNRSession
from smeme.qnr.models import QNRGraph

logger = logging.getLogger(__name__)


async def get_qnr_research_corpus_row(db: AsyncSession, qnr_id: UUID) -> QnrResearchCorpus | None:
    """Load persisted research corpus row for a QNR, if any."""
    r = await db.execute(select(QnrResearchCorpus).where(QnrResearchCorpus.qnr_id == qnr_id))
    return r.scalar_one_or_none()


async def get_qnr_by_id(db: AsyncSession, qnr_id: UUID) -> QNR | None:
    """
    Fetch QNR by ID with eagerly loaded relationships.

    Eagerly loads parent and children to avoid lazy loading in templates.
    """
    result = await db.execute(
        select(QNR)
        .options(
            selectinload(QNR.parent),
            selectinload(QNR.children),
        )
        .where(QNR.id == qnr_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_session(db: AsyncSession, user_id: UUID, qnr_id: UUID) -> QNRSession:
    """Get existing session or create new one."""
    result = await db.execute(
        select(QNRSession)
        .where(QNRSession.user_id == user_id, QNRSession.qnr_id == qnr_id)
        .order_by(QNRSession.created_at.desc())
    )
    session = result.scalar_one_or_none()

    if session:
        return session

    session = QNRSession(user_id=user_id, qnr_id=qnr_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session_by_id(db: AsyncSession, session_id: UUID) -> QNRSession | None:
    """Fetch session by ID."""
    result = await db.execute(select(QNRSession).where(QNRSession.id == session_id))
    return result.scalar_one_or_none()


async def save_session(db: AsyncSession, session: QNRSession) -> None:
    """
    Save session changes to database.

    Handles JSONB column mutation tracking explicitly.
    """
    # Mark user_responses as modified if it exists (JSONB column)
    if hasattr(session, "user_responses") and session.user_responses is not None:
        attributes.flag_modified(session, "user_responses")

    db.add(session)
    await db.commit()
    await db.refresh(session)


async def list_user_sessions(db: AsyncSession, user_id: UUID, limit: int = 20) -> list[QNRSession]:
    """List user's recent QNR sessions with version relationships."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(QNRSession)
        .options(
            selectinload(QNRSession.qnr).selectinload(QNR.parent),  # Load QNR with parent
            selectinload(QNRSession.qnr).selectinload(QNR.children),  # Load QNR with children
            selectinload(QNRSession.memos),  # Eager load memos for dashboard display
        )
        .where(QNRSession.user_id == user_id)
        .order_by(QNRSession.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def parse_graph_data(qnr: QNR) -> QNRGraph:
    """Parse QNR graph_data into validated QNRGraph model."""
    # QNR.graph_data is already a dict from JSON column
    return QNRGraph.model_validate(qnr.graph_data)


async def get_current_public_qnrs(db: AsyncSession, limit: int = 50, offset: int = 0) -> list[QNR]:
    """
    Get public QNRs (any version that is public).

    Note: Only one version per family can be public at a time (enforced by publish logic).
    We don't filter by is_current because the original public version should remain
    visible even after a new private version is created.

    Args:
        db: Database session
        limit: Maximum number of QNRs to return
        offset: Number of QNRs to skip

    Returns:
        List of public QNRs, ordered by updated_at desc
    """
    result = await db.execute(
        select(QNR)
        .where(
            QNR.is_public == True,  # noqa: E712 - SQLAlchemy comparison
            QNR.is_archived == False,  # noqa: E712 - Exclude archived QNRs
        )
        .order_by(QNR.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def _get_root_qnr_id(db: AsyncSession, qnr: QNR) -> UUID:
    """
    Walk up the parent chain to find the root QNR ID using database queries.

    This avoids MissingGreenlet errors by using database queries instead of
    relationship traversal, which requires fully loaded relationship chains.

    Args:
        db: Database session
        qnr: Any QNR in the family

    Returns:
        UUID of the root QNR (v1)
    """
    # Start with the current QNR ID
    root_id = qnr.id
    current_id = qnr.id

    # Walk up the parent chain using database queries
    # This is more efficient and avoids lazy loading issues
    while True:
        # Query for the current QNR to get its parent_id
        result = await db.execute(select(QNR.parent_qnr_id).where(QNR.id == current_id))
        parent_id = result.scalar_one_or_none()

        # If no parent, we've reached the root
        if not parent_id:
            break

        # Move up to the parent
        root_id = parent_id
        current_id = parent_id

    return root_id


async def get_version_family_from_db(
    db: AsyncSession,
    qnr: QNR,
) -> list[QNR]:
    """
    Get all versions in a QNR's family using database queries.

    This avoids the MissingGreenlet errors that can occur when traversing
    loaded relationships in async contexts. This gets all QNRs that share
    the same root ancestor.

    Args:
        db: Database session
        qnr: Any QNR in the family

    Returns:
        List of all QNRs in the family, sorted by version_number
    """
    root_id = await _get_root_qnr_id(db, qnr)

    # Collect all QNR IDs in the family by recursively finding all descendants
    family_ids = {root_id}
    to_check = {root_id}

    while to_check:
        current_ids = list(to_check)
        to_check = set()

        # Find all direct children of current nodes
        result = await db.execute(select(QNR.id).where(QNR.parent_qnr_id.in_(current_ids)))

        child_ids = {row[0] for row in result.all()}
        # Add new children to family and to_check for next iteration
        for child_id in child_ids:
            if child_id not in family_ids:
                family_ids.add(child_id)
                to_check.add(child_id)

    # Now get all QNRs in the family
    result = await db.execute(
        select(QNR).where(QNR.id.in_(family_ids)).order_by(QNR.version_number)
    )

    return list(result.scalars().all())


async def get_newer_public_version(
    db: AsyncSession,
    current_qnr: QNR,
) -> QNR | None:
    """
    Get newer public version if one exists.

    Returns the newest public version in the family that's newer than current,
    or None if no newer public version exists.

    This is a specialized wrapper around get_version_family_from_db() for
    finding version updates.

    Args:
        db: Database session
        current_qnr: The current QNR to check against
        (parent relationships should be eagerly loaded)

    Returns:
        Newer public QNR or None
    """
    # Get entire family and filter in Python (simpler than complex query)
    family = await get_version_family_from_db(db, current_qnr)

    # Filter for newer public versions
    newer_public = [
        qnr for qnr in family if qnr.is_public and qnr.version_number > current_qnr.version_number
    ]

    # Return newest (highest version number)
    if newer_public:
        return max(newer_public, key=lambda q: q.version_number)

    return None


async def get_outdated_sessions_for_user(
    db: AsyncSession,
    user_id: UUID,
    completed_only: bool = False,
    in_progress_only: bool = False,
) -> list[QNRSession]:
    """
    Get user's sessions where the QNR has been superseded by a new version.

    Args:
        user_id: User's UUID
        completed_only: Only return completed sessions
        in_progress_only: Only return in-progress sessions (started but not completed)

    Returns:
        List of QNRSession objects with qnr.is_current = False
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(QNRSession)
        .options(
            selectinload(QNRSession.qnr).selectinload(QNR.children),
            selectinload(QNRSession.qnr).selectinload(QNR.parent),
            selectinload(QNRSession.memos),
        )
        .join(QNR, QNRSession.qnr_id == QNR.id)
        .where(
            QNRSession.user_id == user_id,
            QNR.is_current == False,  # noqa: E712 - SQLAlchemy needs == False
        )
        .order_by(QNRSession.updated_at.desc())
    )

    if completed_only:
        query = query.where(QNRSession.completed_at.isnot(None))
    elif in_progress_only:
        query = query.where(
            QNRSession.started_at.isnot(None),
            QNRSession.completed_at.is_(None),
        )

    result = await db.execute(query)
    return list(result.scalars().all())


async def list_user_qnrs(
    db: AsyncSession,
    user_id: UUID,
    include_all_versions: bool = False,
) -> list[QNR]:
    """
    List QNRs authored by a user.

    Args:
        user_id: User's UUID
        include_all_versions: If True, return all versions; if False, only current versions

    Returns:
        List of QNRs ordered by updated_at desc
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(QNR)
        .options(
            selectinload(QNR.parent),
            selectinload(QNR.children),
            selectinload(QNR.sessions),
        )
        .where(
            QNR.author_id == user_id,
            QNR.is_archived == False,  # noqa: E712 - Exclude archived QNRs
        )
        .order_by(QNR.updated_at.desc())
    )

    if not include_all_versions:
        query = query.where(QNR.is_current == True)  # noqa: E712

    result = await db.execute(query)
    return list(result.scalars().all())
