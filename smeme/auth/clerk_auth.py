"""Clerk session verification and local ``User`` sync (see CLERK_* settings)."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from clerk_backend_api import Clerk
from clerk_backend_api.security import (
    AuthenticateRequestOptions,
    AuthStatus,
    authenticate_request_async,
)
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from smeme.core.config import settings
from smeme.core.logging import get_logger
from smeme.core.models import User

if TYPE_CHECKING:
    from smeme.auth.manager import UserManager

logger = get_logger(__name__)


def clear_clerk_browser_cookies(response: Response) -> None:
    """Remove Clerk session cookies from the browser response.

    Expiration only works if ``Set-Cookie`` matches how Clerk originally set the cookie
    (``Path``, ``Domain``, ``Secure``, ``HttpOnly``, ``SameSite``). Clerk often uses
    ``SameSite=None; Secure``; Starlette's ``delete_cookie`` defaults to ``lax``, which
    would leave ``__session`` in place so the user still looks signed in after "logout".
    """
    from urllib.parse import urlparse

    # __session / __client_uat: auth; clerk_active_context: client hint (can leave user "active" UX if not cleared)
    keys = ("__session", "__client_uat", "clerk_active_context")
    host = urlparse(settings.effective_base_url).hostname

    for key in keys:
        # Try httponly True and False — Clerk may expose some client-readable cookies.
        for httponly in (True, False):
            response.delete_cookie(key, path="/", secure=False, httponly=httponly, samesite="lax")
            response.delete_cookie(key, path="/", secure=True, httponly=httponly, samesite="lax")
            response.delete_cookie(key, path="/", secure=True, httponly=httponly, samesite="none")
        if host in ("localhost", "127.0.0.1"):
            for httponly in (True, False):
                response.delete_cookie(
                    key,
                    path="/",
                    domain="localhost",
                    secure=False,
                    httponly=httponly,
                    samesite="lax",
                )
                # Treat localhost as a secure context for SameSite=None + Secure (common in dev).
                response.delete_cookie(
                    key,
                    path="/",
                    domain="localhost",
                    secure=True,
                    httponly=httponly,
                    samesite="none",
                )
        elif host:
            for httponly in (True, False):
                response.delete_cookie(
                    key, path="/", domain=host, secure=True, httponly=httponly, samesite="none"
                )
                if "." in host:
                    response.delete_cookie(
                        key,
                        path="/",
                        domain=f".{host}",
                        secure=True,
                        httponly=httponly,
                        samesite="none",
                    )


def _primary_email_from_clerk_user(cu) -> str | None:
    pid = getattr(cu, "primary_email_address_id", None)
    addresses = getattr(cu, "email_addresses", None) or []
    for ea in addresses:
        if pid and getattr(ea, "id", None) == pid:
            return getattr(ea, "email_address", None)
    if addresses:
        return getattr(addresses[0], "email_address", None)
    return None


def _slug_username(base: str) -> str:
    s = base.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:32] or "user").lstrip("_") or "user"


async def get_or_create_user_for_clerk(
    db: AsyncSession,
    user_manager: UserManager,
    clerk_user_id: str,
) -> User | None:
    """Resolve Clerk ``sub`` to a local ``User``; create or link by email as needed."""
    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    row = result.scalar_one_or_none()
    if row:
        row.last_login_at = datetime.now(UTC)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    clerk_sdk = Clerk(bearer_auth=settings.clerk_secret_key)
    try:
        cu = await clerk_sdk.users.get_async(user_id=clerk_user_id)
    except Exception as e:
        logger.warning("Clerk users.get failed for %s: %s", clerk_user_id, e)
        return None

    email = (_primary_email_from_clerk_user(cu) or "").strip().lower()
    if not email:
        logger.warning("Clerk user %s has no email; cannot create local User", clerk_user_id)
        return None

    # Link existing row (pre-Clerk migration) by email only when that row still exists.
    # Account hard-delete removes the row entirely — re-signup must create a fresh User
    # (see docs/planning/account-deletion-flow.md identity invariants I1–I4).
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        # Link the pre-Clerk row to this Clerk user. Prefer keeping an existing SMEme
        # username (stable /creator/{username} URLs until Business creator aliases ship).
        existing.clerk_user_id = clerk_user_id
        existing.is_verified = True
        existing.is_active = True
        existing.last_login_at = datetime.now(UTC)
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return existing

    from fastapi_users.password import PasswordHelper

    from smeme.auth.constants import RESERVED_USERNAMES

    # Internal slug from email local-part only (not Clerk username). User-facing handle
    # is email until Business tier ships editable creator aliases on the profile page.
    raw_name = email.split("@", 1)[0]
    username = _slug_username(raw_name)
    if username.lower() in RESERVED_USERNAMES:
        username = f"{username}_{secrets.token_hex(3)}"

    for _ in range(12):
        conflict = await db.execute(select(User.id).where(User.username == username))
        if conflict.scalar_one_or_none() is None:
            break
        username = f"{_slug_username(raw_name)}_{secrets.token_hex(3)}"

    password_helper = PasswordHelper()
    placeholder_hash = password_helper.hash(secrets.token_urlsafe(32))

    user = User(
        email=email,
        hashed_password=placeholder_hash,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        username=username,
        clerk_user_id=clerk_user_id,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Created local User %s for Clerk id %s", user.id, clerk_user_id)
    return user


async def clerk_authenticated_user(
    request: Request,
    db: AsyncSession,
    user_manager: UserManager,
) -> User | None:
    """Return local ``User`` if the request carries a valid Clerk session JWT.

    Uses ``clerk_backend_api.authenticate_request_async`` which validates the
    ``__session`` cookie (or ``Authorization: Bearer`` header) against Clerk's
    JWKS endpoint.

    ``authorized_parties`` is passed from ``settings.clerk_authorized_parties()``,
    which includes the app's own origin **and** the Clerk Account Portal host
    (derived from ``CLERK_SIGN_IN_URL``).  This is necessary because sessions
    created from the Account Portal set the JWT ``azp`` claim to the Account
    Portal domain (``https://<instance>.accounts.dev``), not the SMEme origin.
    Without the Account Portal host in ``authorized_parties``, first-time users
    who sign in via the Account Portal are rejected here and never get a local
    ``User`` row created.  See ``config.py::clerk_authorized_parties`` and
    LESSONS_LEARNED §Clerk ``azp`` Claim.
    """
    opts = AuthenticateRequestOptions(
        secret_key=settings.clerk_secret_key,
        authorized_parties=settings.clerk_authorized_parties(),
    )
    state = await authenticate_request_async(request, opts)
    if state.status != AuthStatus.SIGNED_IN or not state.payload:
        return None

    clerk_uid = state.payload.get("sub")
    if not clerk_uid or not isinstance(clerk_uid, str):
        return None

    return await get_or_create_user_for_clerk(db, user_manager, clerk_uid)
