"""Unit tests for account deletion retry sweeper."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from smeme.auth.account_delete import DeleteAccountResult, DeleteAccountStatus
from smeme.auth.account_deletion_retry import retry_pending_account_deletions
from smeme.core.models import AccountDeletionFailure, User

pytestmark = pytest.mark.asyncio


def _make_failure(
    *,
    user_id=None,
    clerk_user_id: str | None = None,
    attempt_count: int = 1,
) -> AccountDeletionFailure:
    return AccountDeletionFailure(
        id=uuid4(),
        user_id=user_id,
        clerk_user_id=clerk_user_id,
        error_message="purge failed",
        attempt_count=attempt_count,
        resolved_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_sweeper_resolves_when_user_row_gone():
    failure = _make_failure(user_id=None, clerk_user_id="clerk_missing")
    mock_db = AsyncMock()

    failure_result = MagicMock()
    failure_result.scalars.return_value.all.return_value = [failure]

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[failure_result, user_result])

    resolved = await retry_pending_account_deletions(mock_db)

    assert resolved == 1
    assert failure.resolved_at is not None
    assert failure.error_message == "user_row_gone"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweeper_retries_successful_purge():
    user = User(
        id=uuid4(),
        email="gone@example.com",
        hashed_password="x",
        clerk_user_id="clerk_abc",
    )
    failure = _make_failure(user_id=user.id, clerk_user_id=user.clerk_user_id)
    mock_db = AsyncMock()

    failure_result = MagicMock()
    failure_result.scalars.return_value.all.return_value = [failure]

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    mock_db.execute = AsyncMock(side_effect=[failure_result, user_result])

    with patch(
        "smeme.auth.account_deletion_retry.delete_user_account",
        new_callable=AsyncMock,
        return_value=DeleteAccountResult(status=DeleteAccountStatus.DELETED),
    ):
        resolved = await retry_pending_account_deletions(mock_db)

    assert resolved == 1
    assert failure.resolved_at is not None
    mock_db.commit.assert_awaited_once()
