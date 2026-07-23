"""Database query helpers for DecisionTree operations."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes, selectinload

from smeme.core.models import DecisionTree, DecisionTreeResearchCorpus, DecisionTreeSession
from smeme.decision_tree.models import DTGraph

logger = logging.getLogger(__name__)


async def get_decision_tree_research_corpus_row(
    db: AsyncSession, decision_tree_id: UUID
) -> DecisionTreeResearchCorpus | None:
    """Load persisted research corpus row for a DecisionTree, if any."""
    r = await db.execute(
        select(DecisionTreeResearchCorpus).where(
            DecisionTreeResearchCorpus.decision_tree_id == decision_tree_id
        )
    )
    return r.scalar_one_or_none()


async def get_decision_tree_by_id(db: AsyncSession, decision_tree_id: UUID) -> DecisionTree | None:
    """
    Fetch DecisionTree by ID with eagerly loaded relationships.

    Eagerly loads parent and children to avoid lazy loading in templates.
    """
    result = await db.execute(
        select(DecisionTree)
        .options(
            selectinload(DecisionTree.parent),
            selectinload(DecisionTree.children),
        )
        .where(DecisionTree.id == decision_tree_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession, user_id: UUID, decision_tree_id: UUID
) -> DecisionTreeSession:
    """Get existing session or create new one."""
    result = await db.execute(
        select(DecisionTreeSession)
        .where(
            DecisionTreeSession.user_id == user_id,
            DecisionTreeSession.decision_tree_id == decision_tree_id,
        )
        .order_by(DecisionTreeSession.created_at.desc())
    )
    session = result.scalar_one_or_none()

    if session:
        return session

    session = DecisionTreeSession(user_id=user_id, decision_tree_id=decision_tree_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session_by_id(db: AsyncSession, session_id: UUID) -> DecisionTreeSession | None:
    """Fetch session by ID."""
    result = await db.execute(
        select(DecisionTreeSession).where(DecisionTreeSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def save_session(db: AsyncSession, session: DecisionTreeSession) -> None:
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


async def list_user_sessions(
    db: AsyncSession, user_id: UUID, limit: int = 20
) -> list[DecisionTreeSession]:
    """List user's recent DecisionTree sessions with version relationships."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(DecisionTreeSession)
        .options(
            selectinload(DecisionTreeSession.decision_tree).selectinload(
                DecisionTree.parent
            ),  # Load DecisionTree with parent
            selectinload(DecisionTreeSession.decision_tree).selectinload(
                DecisionTree.children
            ),  # Load DecisionTree with children
            selectinload(DecisionTreeSession.memos),  # Eager load memos for dashboard display
        )
        .where(DecisionTreeSession.user_id == user_id)
        .order_by(DecisionTreeSession.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def parse_graph_data(decision_tree: DecisionTree) -> DTGraph:
    """Parse DecisionTree graph_data into validated DTGraph model."""
    # DecisionTree.graph_data is already a dict from JSON column
    return DTGraph.model_validate(decision_tree.graph_data)


async def get_current_public_decision_trees(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> list[DecisionTree]:
    """
    Get public decision trees (any version that is public).

    Note: Only one version per family can be public at a time (enforced by publish logic).
    We don't filter by is_current because the original public version should remain
    visible even after a new private version is created.

    Args:
        db: Database session
        limit: Maximum number of decision trees to return
        offset: Number of decision trees to skip

    Returns:
        List of public decision trees, ordered by updated_at desc
    """
    result = await db.execute(
        select(DecisionTree)
        .where(
            DecisionTree.is_public == True,  # noqa: E712 - SQLAlchemy comparison
            DecisionTree.is_archived == False,  # noqa: E712 - Exclude archived decision trees
        )
        .order_by(DecisionTree.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def _get_root_decision_tree_id(db: AsyncSession, decision_tree: DecisionTree) -> UUID:
    """
    Walk up the parent chain to find the root DecisionTree ID using database queries.

    This avoids MissingGreenlet errors by using database queries instead of
    relationship traversal, which requires fully loaded relationship chains.

    Args:
        db: Database session
        decision_tree: Any DecisionTree in the family

    Returns:
        UUID of the root DecisionTree (v1)
    """
    # Start with the current DecisionTree ID
    root_id = decision_tree.id
    current_id = decision_tree.id

    # Walk up the parent chain using database queries
    # This is more efficient and avoids lazy loading issues
    while True:
        # Query for the current DecisionTree to get its parent_id
        result = await db.execute(
            select(DecisionTree.parent_decision_tree_id).where(DecisionTree.id == current_id)
        )
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
    decision_tree: DecisionTree,
) -> list[DecisionTree]:
    """
    Get all versions in a decision tree's family using database queries.

    This avoids the MissingGreenlet errors that can occur when traversing
    loaded relationships in async contexts. This gets all decision trees that share
    the same root ancestor.

    Args:
        db: Database session
        decision_tree: Any DecisionTree in the family

    Returns:
        List of all decision trees in the family, sorted by version_number
    """
    root_id = await _get_root_decision_tree_id(db, decision_tree)

    # Collect all DecisionTree IDs in the family by recursively finding all descendants
    family_ids = {root_id}
    to_check = {root_id}

    while to_check:
        current_ids = list(to_check)
        to_check = set()

        # Find all direct children of current nodes
        result = await db.execute(
            select(DecisionTree.id).where(DecisionTree.parent_decision_tree_id.in_(current_ids))
        )

        child_ids = {row[0] for row in result.all()}
        # Add new children to family and to_check for next iteration
        for child_id in child_ids:
            if child_id not in family_ids:
                family_ids.add(child_id)
                to_check.add(child_id)

    # Now get all decision trees in the family
    result = await db.execute(
        select(DecisionTree)
        .where(DecisionTree.id.in_(family_ids))
        .order_by(DecisionTree.version_number)
    )

    return list(result.scalars().all())


async def get_newer_public_version(
    db: AsyncSession,
    current_decision_tree: DecisionTree,
) -> DecisionTree | None:
    """
    Get newer public version if one exists.

    Returns the newest public version in the family that's newer than current,
    or None if no newer public version exists.

    This is a specialized wrapper around get_version_family_from_db() for
    finding version updates.

    Args:
        db: Database session
        current_decision_tree: The current DecisionTree to check against
        (parent relationships should be eagerly loaded)

    Returns:
        Newer public DecisionTree or None
    """
    # Get entire family and filter in Python (simpler than complex query)
    family = await get_version_family_from_db(db, current_decision_tree)

    # Filter for newer public versions
    newer_public = [
        decision_tree
        for decision_tree in family
        if decision_tree.is_public
        and decision_tree.version_number > current_decision_tree.version_number
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
) -> list[DecisionTreeSession]:
    """
    Get user's sessions where the DecisionTree has been superseded by a new version.

    Args:
        user_id: User's UUID
        completed_only: Only return completed sessions
        in_progress_only: Only return in-progress sessions (started but not completed)

    Returns:
        List of DecisionTreeSession objects with decision_tree.is_current = False
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(DecisionTreeSession)
        .options(
            selectinload(DecisionTreeSession.decision_tree).selectinload(DecisionTree.children),
            selectinload(DecisionTreeSession.decision_tree).selectinload(DecisionTree.parent),
            selectinload(DecisionTreeSession.memos),
        )
        .join(DecisionTree, DecisionTreeSession.decision_tree_id == DecisionTree.id)
        .where(
            DecisionTreeSession.user_id == user_id,
            DecisionTree.is_current == False,  # noqa: E712 - SQLAlchemy needs == False
        )
        .order_by(DecisionTreeSession.updated_at.desc())
    )

    if completed_only:
        query = query.where(DecisionTreeSession.completed_at.isnot(None))
    elif in_progress_only:
        query = query.where(
            DecisionTreeSession.started_at.isnot(None),
            DecisionTreeSession.completed_at.is_(None),
        )

    result = await db.execute(query)
    return list(result.scalars().all())


async def list_user_decision_trees(
    db: AsyncSession,
    user_id: UUID,
    include_all_versions: bool = False,
) -> list[DecisionTree]:
    """
    List decision trees authored by a user.

    Args:
        user_id: User's UUID
        include_all_versions: If True, return all versions; if False, only current versions

    Returns:
        List of decision trees ordered by updated_at desc
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(DecisionTree)
        .options(
            selectinload(DecisionTree.parent),
            selectinload(DecisionTree.children),
            selectinload(DecisionTree.sessions),
        )
        .where(
            DecisionTree.author_id == user_id,
            DecisionTree.is_archived == False,  # noqa: E712 - Exclude archived decision trees
        )
        .order_by(DecisionTree.updated_at.desc())
    )

    if not include_all_versions:
        query = query.where(DecisionTree.is_current == True)  # noqa: E712

    result = await db.execute(query)
    return list(result.scalars().all())
