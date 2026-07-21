"""Clerk inbound webhook handler.

Clerk delivers webhook events signed via Svix (https://docs.svix.com).
``user.deleted`` triggers a hard local purge via ``delete_user_account``
(see ``docs/planning/account-deletion-flow.md``).

Endpoint: POST /auth/clerk/webhook
No authentication — the Svix signature in the request headers is the
only trust mechanism.  Register this URL in the Clerk Dashboard → Webhooks.

Required env var: CLERK_WEBHOOK_SECRET  (starts with ``whsec_``)
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from svix.webhooks import Webhook, WebhookVerificationError

from smeme.auth.account_delete import (
    AccountDeletionLockError,
    AccountDeletionPurgeError,
    delete_user_account,
)
from smeme.core.config import settings
from smeme.core.dependencies import AsyncSessionDep
from smeme.core.logging import get_logger
from smeme.core.models import User

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])


@router.post("/auth/clerk/webhook", include_in_schema=False)
async def clerk_webhook(request: Request, db: AsyncSessionDep) -> Response:
    """Receive and verify Clerk webhook events.

    Verifies the Svix signature before processing.  Returns 200 for all
    successfully verified events (even unrecognised types) so Clerk does not
    retry unnecessarily.  Returns 400 on signature failure so Clerk can flag
    the delivery as errored.  Returns 500 when ``user.deleted`` purge fails
    so Svix retries.
    """
    if not settings.clerk_webhook_secret:
        logger.warning("Clerk webhook received but CLERK_WEBHOOK_SECRET is not configured")
        return Response(status_code=500)

    payload = await request.body()
    headers = dict(request.headers)

    try:
        wh = Webhook(settings.clerk_webhook_secret)
        event = wh.verify(payload, headers)
    except WebhookVerificationError as exc:
        logger.warning("Clerk webhook signature verification failed: %s", exc)
        return Response(status_code=400)

    if isinstance(event, (bytes, str)):
        event = json.loads(event)

    event_type: str = event.get("type", "")
    logger.info("Clerk webhook received: type=%s", event_type)

    if event_type == "user.deleted":
        try:
            await _handle_user_deleted(db, event)
        except (AccountDeletionLockError, AccountDeletionPurgeError) as exc:
            logger.error("user.deleted: account purge failed: %s", exc)
            return Response(status_code=500)

    return Response(status_code=200)


async def _handle_user_deleted(db: AsyncSessionDep, event: dict) -> None:  # type: ignore[type-arg]
    """Hard-delete local user data when Clerk reports identity removal."""
    data = event.get("data", {})
    clerk_user_id: str | None = data.get("id")

    if not clerk_user_id:
        logger.warning("user.deleted event missing data.id — skipping")
        return

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        logger.info(
            "user.deleted: no local User found for clerk_user_id=%s — nothing to do",
            clerk_user_id,
        )
        return

    outcome = await delete_user_account(db, user, actor="clerk_webhook")
    logger.info(
        "user.deleted: purge complete status=%s user_id=%s clerk_user_id=%s",
        outcome.status.value,
        user.id,
        clerk_user_id,
    )
