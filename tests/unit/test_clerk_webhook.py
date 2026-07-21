"""Unit tests for the Clerk webhook handler (user.deleted).

Uses a locally-generated Svix signature so no live Clerk account is needed.
The test database is used to create / verify real User rows.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from svix.webhooks import Webhook

from smeme.core.models import User, UserAuditLog
from smeme.app_factory import create_core_app as create_app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TEST_WEBHOOK_SECRET = "whsec_" + "a" * 32  # 32-byte base64-encoded dummy secret


def _signed_headers(payload: bytes, secret: str) -> dict[str, str]:
    """Return Svix-signed headers for *payload* using *secret*.

    ``svix.Webhook.sign`` requires the payload as a ``str`` (not bytes).
    The verifier decodes bytes → str before checking, so both sides must
    operate on the same decoded string.
    """
    wh = Webhook(secret)
    msg_id = f"msg_{uuid4().hex}"
    now = datetime.now(UTC)
    sig = wh.sign(msg_id, now, payload.decode())
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(now.timestamp())),
        "svix-signature": sig,
        "content-type": "application/json",
    }


def _deletion_payload(clerk_user_id: str) -> bytes:
    return json.dumps(
        {
            "type": "user.deleted",
            "object": "event",
            "timestamp": int(time.time() * 1000),
            "data": {"deleted": True, "id": clerk_user_id, "object": "user"},
        }
    ).encode()


@contextmanager
def _webhook_patches(stripe_cancel_mock=None):
    """Context manager that patches clerk_webhook_secret and account-delete side effects."""
    cfg = __import__("smeme.core.config", fromlist=["settings"]).settings
    cancel_mock = stripe_cancel_mock or MagicMock(return_value=MagicMock(status="canceled"))
    with patch.object(cfg, "clerk_webhook_secret", _TEST_WEBHOOK_SECRET):
        with patch.object(cfg, "stripe_secret_key", "sk_test_fake"):
            with patch("stripe.Subscription.cancel", cancel_mock):
                with patch(
                    "smeme.auth.account_delete.checkpointer_manager.delete_checkpoints_for_thread",
                    new_callable=AsyncMock,
                    return_value=0,
                ):
                    yield cancel_mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def webhook_user(test_session_factory):
    """Create a live Clerk-linked user and clean up after the test."""
    uid = uuid4().hex[:8]
    clerk_id = f"user_clerk_{uid}"
    email = f"webhook_test_{uid}@example.com"
    ph = PasswordHelper()

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password=ph.hash("irrelevant"),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"whtest_{uid}",
            clerk_user_id=clerk_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    yield {"user": user, "clerk_user_id": clerk_id}

    from sqlalchemy import delete

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


@pytest_asyncio.fixture
async def premium_webhook_user(test_session_factory):
    """Create a Clerk-linked user who also has an active Stripe subscription."""
    uid = uuid4().hex[:8]
    clerk_id = f"user_clerk_premium_{uid}"
    email = f"webhook_premium_{uid}@example.com"
    ph = PasswordHelper()

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password=ph.hash("irrelevant"),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"whpremium_{uid}",
            clerk_user_id=clerk_id,
            stripe_customer_id=f"cus_test_{uid}",
            stripe_subscription_id=f"sub_test_{uid}",
            subscription_status="active",
            is_premium=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    yield {"user": user, "clerk_user_id": clerk_id}

    from sqlalchemy import delete

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClerkWebhookUserDeleted:
    async def test_hard_deletes_user_on_valid_deletion_event(
        self, webhook_user, test_session_factory
    ):
        """A valid user.deleted webhook hard-deletes the local User row."""
        clerk_user_id = webhook_user["clerk_user_id"]
        user_id = webhook_user["user"].id

        payload = _deletion_payload(clerk_user_id)
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        with _webhook_patches():
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert response.status_code == 200

        async with test_session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            assert result.scalar_one_or_none() is None

        async with test_session_factory() as session:
            rows = (
                await session.execute(
                    select(UserAuditLog)
                    .where(UserAuditLog.event_type == "account.deleted")
                    .order_by(UserAuditLog.created_at)
                )
            ).scalars().all()

        assert len(rows) >= 1
        deleted_event = rows[-1]
        assert deleted_event.actor == "clerk_webhook"
        assert deleted_event.reason == "clerk_user_deleted"
        assert deleted_event.event_metadata.get("clerk_user_id") == clerk_user_id

    async def test_cancels_stripe_subscription_on_deletion(
        self, premium_webhook_user, test_session_factory
    ):
        """When the deleted user has an active Stripe subscription it is cancelled."""
        clerk_user_id = premium_webhook_user["clerk_user_id"]
        user = premium_webhook_user["user"]
        sub_id = user.stripe_subscription_id

        payload = _deletion_payload(clerk_user_id)
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        cancel_mock = MagicMock(return_value=MagicMock(status="canceled"))
        with _webhook_patches(cancel_mock):
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert response.status_code == 200
        cancel_mock.assert_called_once_with(sub_id)

        async with test_session_factory() as session:
            result = await session.execute(select(User).where(User.id == user.id))
            assert result.scalar_one_or_none() is None

    async def test_stripe_error_does_not_prevent_user_deletion(
        self, premium_webhook_user, test_session_factory
    ):
        """A Stripe API failure is logged but the user row is still hard-deleted."""

        clerk_user_id = premium_webhook_user["clerk_user_id"]
        user_id = premium_webhook_user["user"].id

        payload = _deletion_payload(clerk_user_id)
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        # Stripe raises an unexpected error
        cancel_mock = MagicMock(side_effect=Exception("Stripe is down"))
        with _webhook_patches(cancel_mock):
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert response.status_code == 200

        async with test_session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            assert result.scalar_one_or_none() is None

    async def test_no_stripe_call_when_user_has_no_subscription(
        self, webhook_user, test_session_factory
    ):
        """Users without a Stripe subscription don't trigger a Stripe API call."""
        payload = _deletion_payload(webhook_user["clerk_user_id"])
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        cancel_mock = MagicMock()
        with _webhook_patches(cancel_mock):
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/auth/clerk/webhook", content=payload, headers=headers)

        cancel_mock.assert_not_called()

    async def test_returns_400_on_invalid_signature(self, webhook_user):
        """A tampered payload is rejected with 400 before any DB work."""
        payload = b'{"type":"user.deleted","data":{"id":"user_fake","object":"user"}}'
        bad_headers = {
            "svix-id": "msg_fake",
            "svix-timestamp": str(int(time.time())),
            "svix-signature": "v1,invalidsignature==",
            "content-type": "application/json",
        }

        with patch.object(
            __import__("smeme.core.config", fromlist=["settings"]).settings,
            "clerk_webhook_secret",
            _TEST_WEBHOOK_SECRET,
        ):
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=bad_headers
                )

        assert response.status_code == 400

    async def test_returns_500_when_secret_not_configured(self):
        """Without a configured secret the endpoint returns 500 (misconfiguration guard)."""
        payload = b'{"type":"user.deleted","data":{"id":"user_x","object":"user"}}'

        with patch.object(
            __import__("smeme.core.config", fromlist=["settings"]).settings,
            "clerk_webhook_secret",
            None,
        ):
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook",
                    content=payload,
                    headers={"content-type": "application/json"},
                )

        assert response.status_code == 500

    async def test_idempotent_when_user_already_deleted(
        self, webhook_user, test_session_factory
    ):
        """Second user.deleted delivery is a no-op when the user row is gone."""
        clerk_user_id = webhook_user["clerk_user_id"]
        user_id = webhook_user["user"].id

        payload = _deletion_payload(clerk_user_id)
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        with _webhook_patches():
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )
                second = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert first.status_code == 200
        assert second.status_code == 200

        async with test_session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            assert result.scalar_one_or_none() is None

    async def test_unknown_event_type_is_accepted_and_ignored(self):
        """Unrecognised event types get 200 so Clerk does not retry."""
        payload = json.dumps(
            {"type": "user.created", "object": "event", "data": {"id": "user_xyz"}}
        ).encode()
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        with _webhook_patches():
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert response.status_code == 200

    async def test_graceful_when_clerk_id_not_in_db(self):
        """A valid event for an unknown Clerk ID is silently accepted (no local row)."""
        payload = _deletion_payload("user_nonexistent_abc123")
        headers = _signed_headers(payload, _TEST_WEBHOOK_SECRET)

        with _webhook_patches():
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/auth/clerk/webhook", content=payload, headers=headers
                )

        assert response.status_code == 200
