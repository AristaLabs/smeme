"""Ownership gates for in-progress agentic generation sessions.

Handlers that accept a LangGraph ``thread_id`` must resolve the in-progress row
for the authenticated user before reading or mutating checkpoints.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Form, HTTPException

from smeme.core.dependencies import AsyncSessionDep, CurrentUser
from smeme.decision_tree.generation.agentic.services import checkpoint_manager
from smeme.decision_tree.models import InProgressDecisionTreeGeneration


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Generation not found")


async def require_owned_generation_by_thread_id(
    db: AsyncSessionDep,
    user: CurrentUser,
    thread_id: Annotated[str, Form()],
) -> InProgressDecisionTreeGeneration:
    """FastAPI dependency: Form ``thread_id`` must belong to the current user."""
    generation = await checkpoint_manager.get_generation_by_thread_id(
        db,
        thread_id,
        user_id=user.id,
    )
    if generation is None:
        raise _not_found()
    return generation


OwnedGenerationByThreadFormDep = Annotated[
    InProgressDecisionTreeGeneration,
    Depends(require_owned_generation_by_thread_id),
]


async def require_owned_generation_for_thread(
    db: AsyncSessionDep,
    user: CurrentUser,
    thread_id: str,
) -> InProgressDecisionTreeGeneration:
    """Path/query helper: ``thread_id`` must belong to the current user."""
    generation = await checkpoint_manager.get_generation_by_thread_id(
        db,
        thread_id,
        user_id=user.id,
    )
    if generation is None:
        raise _not_found()
    return generation


def assert_workflow_state_owned_by(
    state: Mapping[str, Any] | None,
    user_id: UUID,
) -> None:
    """Reject checkpoint state whose stored owner does not match the caller.

    LangGraph config ``user_id`` is attacker-controlled at the handler boundary;
    the checkpointed state ``user_id`` is the authoritative owner invariant.
    """
    if not state:
        raise _not_found()
    state_owner = state.get("user_id")
    if state_owner is None or str(state_owner) != str(user_id):
        raise _not_found()
