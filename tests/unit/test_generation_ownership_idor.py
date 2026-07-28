"""Cross-tenant ownership regression tests for H-01 IDOR endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio

IDOR_ENDPOINTS = (
    ("/decision-trees/agentic/research/submit", {"research_context_edited": "x", "action": "continue"}),
    ("/decision-trees/agentic/conclusions/submit", {"possible_conclusions_edited": "x"}),
    ("/decision-trees/agentic/retry-design", {}),
    ("/decision-trees/agentic/design/submit", {"decision_tree_design_edited": "x"}),
    ("/decision-trees/agentic/retry-build", {}),
)


def _mock_user():
    user = MagicMock()
    user.id = uuid4()
    user.is_premium = True
    user.subscription_period_start = None
    user.subscription_period_end = None
    return user


@pytest.mark.parametrize(("path", "extra_form"), IDOR_ENDPOINTS)
async def test_generation_post_rejects_foreign_thread_id(app, path, extra_form):
    """Authenticated second user cannot act on another user's thread_id."""
    attacker = _mock_user()
    victim_thread_id = str(uuid4())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            auth_as(app, attacker),
            patch(
                "smeme.decision_tree.generation.agentic.ownership.checkpoint_manager.get_generation_by_thread_id",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_get,
        ):
            response = await client.post(
                path,
                data={"thread_id": victim_thread_id, **extra_form},
                headers={"HX-Request": "true"},
            )

    assert response.status_code == 404
    mock_get.assert_awaited()
    kwargs = mock_get.await_args.kwargs
    assert kwargs.get("user_id") == attacker.id


async def test_require_owned_generation_passes_user_id_filter():
    from smeme.decision_tree.generation.agentic.ownership import (
        require_owned_generation_by_thread_id,
    )

    user = _mock_user()
    db = AsyncMock()
    owned = MagicMock()
    thread_id = str(uuid4())

    with patch(
        "smeme.decision_tree.generation.agentic.ownership.checkpoint_manager.get_generation_by_thread_id",
        new_callable=AsyncMock,
        return_value=owned,
    ) as mock_get:
        result = await require_owned_generation_by_thread_id(
            db=db,
            user=user,
            thread_id=thread_id,
        )

    assert result is owned
    mock_get.assert_awaited_once_with(db, thread_id, user_id=user.id)


async def test_assert_workflow_state_owned_by_rejects_mismatch():
    from fastapi import HTTPException

    from smeme.decision_tree.generation.agentic.ownership import assert_workflow_state_owned_by

    owner = uuid4()
    with pytest.raises(HTTPException) as exc:
        assert_workflow_state_owned_by({"user_id": str(uuid4())}, owner)
    assert exc.value.status_code == 404


async def test_assert_workflow_state_owned_by_accepts_owner():
    from smeme.decision_tree.generation.agentic.ownership import assert_workflow_state_owned_by

    owner = uuid4()
    assert_workflow_state_owned_by({"user_id": str(owner)}, owner)
