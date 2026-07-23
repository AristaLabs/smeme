"""Permanent workflow (version family) deletion."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from smeme.core.models import DecisionTree, DecisionTreeSession, Memo
from smeme.decision_tree.helpers.db_queries import get_version_family_from_db

DELETE_CONFIRM_PHRASE = "delete workflow permanently"

__all__ = ["DELETE_CONFIRM_PHRASE", "delete_workflow_family"]


async def delete_workflow_family(
    db: AsyncSession,
    decision_tree: DecisionTree,
    *,
    author_id: UUID,
) -> list[DecisionTree]:
    """
    Hard-delete an entire DecisionTree version family and related author-owned session data.

    Removes memos and sessions explicitly (no CASCADE on ``decision_tree_sessions.decision_tree_id``).
    Reasoning artifacts, corpora, lexicon drafts, and evaluation runs CASCADE from ``decision_trees``.

    Returns the deleted family members (for logging / flash messages).
    """
    if decision_tree.author_id != author_id:
        raise PermissionError("Not authorized to delete this workflow")

    family = await get_version_family_from_db(db, decision_tree)
    family_ids = [v.id for v in family]

    session_result = await db.execute(
        select(DecisionTreeSession.id).where(DecisionTreeSession.decision_tree_id.in_(family_ids))
    )
    session_ids = [row[0] for row in session_result.all()]

    if session_ids:
        await db.execute(delete(Memo).where(Memo.session_id.in_(session_ids)))

    await db.execute(
        delete(DecisionTreeSession).where(DecisionTreeSession.decision_tree_id.in_(family_ids))
    )

    # Break parent links so all family rows can be removed in one statement.
    await db.execute(
        update(DecisionTree)
        .where(DecisionTree.id.in_(family_ids))
        .values(parent_decision_tree_id=None)
    )
    await db.execute(delete(DecisionTree).where(DecisionTree.id.in_(family_ids)))

    return family
