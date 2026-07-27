"""Clerk session verification and local ``User`` sync (see CLERK_* settings).

D026: first-time provision (web or MCP) requires verified primary email +
Clerk ``legal_accepted_at``. Existing linked ``users.clerk_user_id`` rows are
grandfathered (no re-fetch / no audit requirement).
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from clerk_backend_api import Clerk
from clerk_backend_api.security import (
    AuthenticateRequestOptions,
    AuthStatus,
    authenticate_request_async,
)
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from smeme.core.config import settings
from smeme.core.logging import get_logger
from smeme.core.models import User

if TYPE_CHECKING:
    from smeme.auth.manager import UserManager

logger = get_logger(__name__)


class ProvisionFailureReason(str, Enum):
    """Locked D026 ``auth_reason`` values for failed *new* provision attempts."""

    EMAIL_NOT_VERIFIED = "email_not_verified"
    PRIMARY_EMAIL_MISSING = "primary_email_missing"
    LEGAL_CONSENT_REQUIRED = "legal_consent_required"
    LEGAL_CONFIG_INCOMPLETE = "legal_config_incomplete"
    CLERK_LOOKUP_FAILED = "clerk_lookup_failed"


@dataclass(frozen=True)
class ClerkProfile:
    """Normalized Clerk user fields needed for local provision gates."""

    clerk_user_id: str
    email: str
    email_verified: bool
    legal_accepted_at: datetime | None


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of resolving Clerk ``sub`` → local ``User``."""

    user: User | None = None
    failure_reason: ProvisionFailureReason | None = None
    telemetry_event: str | None = None


class ProvisionError(Exception):
    """Typed first-provision failure (maps to locked MCP ``auth_reason``)."""

    def __init__(self, reason: ProvisionFailureReason, message: str | None = None) -> None:
        self.reason = reason
        super().__init__(message or reason.value)


def clear_clerk_browser_cookies(response: Response) -> None:
    """Remove Clerk session cookies from the browser response."""
    from urllib.parse import urlparse

    keys = ("__session", "__client_uat", "clerk_active_context")
    host = urlparse(settings.effective_base_url).hostname

    for key in keys:
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


def _slug_username(base: str) -> str:
    s = base.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:32] or "user").lstrip("_") or "user"


def _verification_status_value(verification: Any) -> str | None:
    if verification is None:
        return None
    status = getattr(verification, "status", None)
    if status is None:
        return None
    if isinstance(status, str):
        return status.strip().lower() or None
    value = getattr(status, "value", None)
    if isinstance(value, str):
        return value.strip().lower() or None
    return str(status).strip().lower() or None


def _legal_accepted_at_utc(raw: Any) -> datetime | None:
    """Clerk ``legal_accepted_at`` is Unix seconds (nullable int)."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        ts = int(raw)
        if ts <= 0:
            return None
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)
    return None


def normalize_clerk_profile(clerk_user_id: str, cu: Any) -> ClerkProfile:
    """Extract email + verification + legal acceptance from a Clerk User object."""
    pid = getattr(cu, "primary_email_address_id", None)
    addresses = list(getattr(cu, "email_addresses", None) or [])
    primary = None
    if pid:
        for ea in addresses:
            if getattr(ea, "id", None) == pid:
                primary = ea
                break

    # D026 requires the Clerk-designated primary address.  Do not fall back to
    # a secondary verified address: that would silently bypass the
    # ``primary_email_missing`` gate when Clerk has no usable primary ID.
    if primary is None:
        return ClerkProfile(
            clerk_user_id=clerk_user_id,
            email="",
            email_verified=False,
            legal_accepted_at=_legal_accepted_at_utc(getattr(cu, "legal_accepted_at", None)),
        )

    email = (getattr(primary, "email_address", None) or "").strip().lower()
    status = _verification_status_value(getattr(primary, "verification", None))
    return ClerkProfile(
        clerk_user_id=clerk_user_id,
        email=email,
        email_verified=status == "verified",
        legal_accepted_at=_legal_accepted_at_utc(getattr(cu, "legal_accepted_at", None)),
    )


async def fetch_clerk_profile(clerk_user_id: str) -> ClerkProfile:
    """Backend API lookup for MCP/web first-provision gates (JWT lacks these claims)."""
    if not (settings.clerk_secret_key or "").strip():
        raise ProvisionError(
            ProvisionFailureReason.CLERK_LOOKUP_FAILED, "Clerk secret not configured"
        )
    clerk_sdk = Clerk(bearer_auth=settings.clerk_secret_key)
    try:
        cu = await clerk_sdk.users.get_async(user_id=clerk_user_id)
    except Exception as e:
        logger.warning("Clerk users.get failed for %s: %s", clerk_user_id, e)
        raise ProvisionError(
            ProvisionFailureReason.CLERK_LOOKUP_FAILED,
            "Could not load Clerk user profile",
        ) from e
    if cu is None:
        raise ProvisionError(ProvisionFailureReason.CLERK_LOOKUP_FAILED, "Clerk user not found")
    return normalize_clerk_profile(clerk_user_id, cu)


def assert_provision_gates(profile: ClerkProfile) -> None:
    """Raise ``ProvisionError`` unless verified primary email + legal acceptance."""
    if not settings.mcp_first_legal_config_complete():
        raise ProvisionError(ProvisionFailureReason.LEGAL_CONFIG_INCOMPLETE)
    if not profile.email:
        raise ProvisionError(ProvisionFailureReason.PRIMARY_EMAIL_MISSING)
    if not profile.email_verified:
        raise ProvisionError(ProvisionFailureReason.EMAIL_NOT_VERIFIED)
    if profile.legal_accepted_at is None:
        raise ProvisionError(ProvisionFailureReason.LEGAL_CONSENT_REQUIRED)


def _apply_legal_audit(user: User, profile: ClerkProfile) -> None:
    user.legal_accepted_at = profile.legal_accepted_at
    user.terms_version = (settings.legal_terms_version or "").strip() or None
    user.privacy_version = (settings.legal_privacy_version or "").strip() or None


def emit_provision_telemetry(
    event: str,
    *,
    clerk_user_id: str | None = None,
    auth_reason: str | None = None,
) -> None:
    payload: dict[str, Any] = {"stage": "local_user_provision", "event": event}
    if clerk_user_id:
        payload["clerk_user_id"] = clerk_user_id
    if auth_reason:
        payload["auth_reason"] = auth_reason
    logger.info("MCP/local provision telemetry %s", json.dumps(payload, separators=(",", ":")))


async def _create_user_from_profile(db: AsyncSession, profile: ClerkProfile) -> User:
    from fastapi_users.password import PasswordHelper

    from smeme.auth.constants import RESERVED_USERNAMES

    email = profile.email
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
        clerk_user_id=profile.clerk_user_id,
        last_login_at=datetime.now(UTC),
    )
    _apply_legal_audit(user, profile)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("Created local User %s for Clerk id %s", user.id, profile.clerk_user_id)
    return user


async def _link_legacy_or_create(db: AsyncSession, profile: ClerkProfile) -> tuple[User, str]:
    result = await db.execute(select(User).where(User.email == profile.email))
    existing = result.scalar_one_or_none()
    if existing:
        existing.clerk_user_id = profile.clerk_user_id
        existing.is_verified = True
        existing.is_active = True
        existing.last_login_at = datetime.now(UTC)
        _apply_legal_audit(existing, profile)
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return existing, "linked_legacy_user"

    user = await _create_user_from_profile(db, profile)
    return user, "created"


async def resolve_local_user_for_clerk(
    db: AsyncSession,
    clerk_user_id: str,
    *,
    enforce_new_user_gates: bool,
    user_manager: UserManager | None = None,
) -> ProvisionResult:
    """Resolve Clerk ``sub`` to local ``User``.

    Existing linked rows are always returned (grandfathered) without Clerk fetch.
    New create/link runs D026 gates when ``enforce_new_user_gates`` is True.
    """
    _ = user_manager

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    row = result.scalar_one_or_none()
    if row:
        row.last_login_at = datetime.now(UTC)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        # Do not emit ``grandfathered`` on every login — return the event name only.
        return ProvisionResult(user=row, telemetry_event="grandfathered")

    if not enforce_new_user_gates:
        return ProvisionResult(user=None)

    try:
        profile = await fetch_clerk_profile(clerk_user_id)
        assert_provision_gates(profile)
        user, event = await _link_legacy_or_create(db, profile)
        emit_provision_telemetry(event, clerk_user_id=clerk_user_id)
        return ProvisionResult(user=user, telemetry_event=event)
    except ProvisionError as exc:
        event = (
            "lookup_failed"
            if exc.reason == ProvisionFailureReason.CLERK_LOOKUP_FAILED
            else "blocked"
        )
        emit_provision_telemetry(
            event,
            clerk_user_id=clerk_user_id,
            auth_reason=exc.reason.value,
        )
        return ProvisionResult(failure_reason=exc.reason)
    except IntegrityError:
        await db.rollback()
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        winner = result.scalar_one_or_none()
        if winner is not None:
            emit_provision_telemetry("race_reused", clerk_user_id=clerk_user_id)
            return ProvisionResult(user=winner, telemetry_event="race_reused")
        emit_provision_telemetry(
            "lookup_failed",
            clerk_user_id=clerk_user_id,
            auth_reason=ProvisionFailureReason.CLERK_LOOKUP_FAILED.value,
        )
        return ProvisionResult(failure_reason=ProvisionFailureReason.CLERK_LOOKUP_FAILED)


async def get_or_create_user_for_clerk(
    db: AsyncSession,
    user_manager: UserManager,
    clerk_user_id: str,
) -> User | None:
    """Resolve Clerk ``sub`` to a local ``User``; create or link by email as needed."""
    outcome = await resolve_local_user_for_clerk(
        db,
        clerk_user_id,
        enforce_new_user_gates=True,
        user_manager=user_manager,
    )
    return outcome.user


async def clerk_authenticated_user(
    request: Request,
    db: AsyncSession,
    user_manager: UserManager,
) -> User | None:
    """Return local ``User`` if the request carries a valid Clerk session JWT."""
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


async def clerk_authenticated_provision(
    request: Request,
    db: AsyncSession,
    user_manager: UserManager,
) -> ProvisionResult:
    """Like ``clerk_authenticated_user`` but returns typed provision outcome."""
    opts = AuthenticateRequestOptions(
        secret_key=settings.clerk_secret_key,
        authorized_parties=settings.clerk_authorized_parties(),
    )
    state = await authenticate_request_async(request, opts)
    if state.status != AuthStatus.SIGNED_IN or not state.payload:
        return ProvisionResult()

    clerk_uid = state.payload.get("sub")
    if not clerk_uid or not isinstance(clerk_uid, str):
        return ProvisionResult()

    return await resolve_local_user_for_clerk(
        db,
        clerk_uid,
        enforce_new_user_gates=True,
        user_manager=user_manager,
    )
