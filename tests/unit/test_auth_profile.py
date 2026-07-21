"""Unit tests for auth profile routes.

Covers:
- GET /auth/profile/dashboard renders for authenticated users
- PUT /auth/profile/me rejects username change (Business creator aliases not shipped)
- PUT /auth/profile/me rejects email change (400)
- PUT /auth/profile/me via HTMX rejects email change with inline HTML (200)
- PUT /auth/profile/me via HTMX updates creator fields with success fragment
- Clerk account portal URL includes redirect_url back to /auth/profile/dashboard
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from smeme.core.config import settings
from smeme.core.models import User
from smeme.app_factory import create_core_app as create_app
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def profile_user(test_session_factory):
    """Active user for profile tests."""
    uid = uuid4().hex[:8]
    email = f"profile_test_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"profileuser_{uid}",
            bio="Test bio",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    yield user

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest_asyncio.fixture
async def app_with_db(test_session_factory):
    from smeme.core.database import get_db

    application = create_app()

    async def override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    application.dependency_overrides[get_db] = override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app_with_db):
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# GET /auth/profile/dashboard
# =============================================================================


async def test_profile_dashboard_returns_200(client, app_with_db, profile_user):
    with auth_as(app_with_db, profile_user):
        r = await client.get("/auth/profile/dashboard")
    assert r.status_code == 200
    assert b"profile" in r.content.lower() or b"account" in r.content.lower()


async def test_profile_dashboard_requires_auth(client):
    r = await client.get("/auth/profile/dashboard")
    # Unauthenticated → redirect or 4xx
    assert r.status_code in (302, 401, 403)


# =============================================================================
# PUT /auth/profile/me — username change rejected (Business aliases not shipped)
# =============================================================================


async def test_update_profile_username_change_rejected_json(
    client, app_with_db, profile_user, test_session_factory
):
    new_username = f"updated_{uuid4().hex[:6]}"
    with auth_as(app_with_db, profile_user):
        r = await client.put(
            "/auth/profile/me",
            json={"username": new_username},
        )

    assert r.status_code == 400
    assert "business" in r.json()["detail"].lower()

    async with test_session_factory() as session:
        result = await session.execute(select(User).where(User.id == profile_user.id))
        unchanged = result.scalar_one()
    assert unchanged.username == profile_user.username


# =============================================================================
# PUT /auth/profile/me — email change rejected
# =============================================================================


async def test_update_profile_email_change_rejected_json(client, app_with_db, profile_user):
    with auth_as(app_with_db, profile_user):
        r = await client.put(
            "/auth/profile/me",
            json={"email": "newemail@example.com"},
        )
    # Must NOT silently succeed
    assert r.status_code == 400
    assert "clerk" in r.json()["detail"].lower() or "managed" in r.json()["detail"].lower()


async def test_update_profile_email_change_rejected_htmx(client, app_with_db, profile_user):
    with auth_as(app_with_db, profile_user):
        r = await client.put(
            "/auth/profile/me",
            json={"email": "newemail@example.com"},
            headers={"HX-Request": "true"},
        )
    # HTMX path returns 200 with an inline error fragment
    assert r.status_code == 200
    assert b"clerk" in r.content.lower() or b"managed" in r.content.lower()


# =============================================================================
# PUT /auth/profile/me — HTMX success fragment
# =============================================================================


async def test_update_profile_htmx_returns_success_fragment(
    client, app_with_db, profile_user,
):
    with auth_as(app_with_db, profile_user):
        r = await client.put(
            "/auth/profile/me",
            json={"bio": "Updated bio via HTMX test"},
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200
    assert b"Profile updated" in r.content or b"success" in r.content.lower()


async def test_update_profile_rejects_unsafe_creator_urls(
    client, app_with_db, profile_user,
):
    with auth_as(app_with_db, profile_user):
        r = await client.put(
            "/auth/profile/me",
            json={"website_url": "javascript:alert(1)"},
        )

    assert r.status_code == 422
    assert "http://" in r.text or "https://" in r.text


async def test_current_active_user_rejects_inactive_user(profile_user, monkeypatch):
    from smeme.auth import users as auth_users

    profile_user.is_active = False

    async def fake_optional_user(*args, **kwargs):
        return profile_user

    monkeypatch.setattr(auth_users, "get_current_user_optional", fake_optional_user)

    with pytest.raises(HTTPException) as exc:
        await auth_users.get_current_active_user(request=None, db=None, user_manager=None)

    assert exc.value.status_code == 403


async def test_profile_dashboard_hides_creator_card_by_default(client, app_with_db, profile_user):
    with auth_as(app_with_db, profile_user):
        r = await client.get("/auth/profile/dashboard")
    assert r.status_code == 200
    assert b"Creator profile" not in r.content
    assert b"Show public creator page" not in r.content


# =============================================================================
# Clerk portal URL includes redirect_url
# =============================================================================


async def test_clerk_portal_url_includes_redirect_url():
    """clerk_account_portal_url_with_redirect must append redirect_url parameter."""
    with (
        patch.object(settings, "clerk_sign_in_url", "https://accounts.example.dev/sign-in"),
        patch.object(settings, "base_url", "https://app.example.com"),
    ):
        url = settings.clerk_account_portal_url_with_redirect("/auth/profile/dashboard")

    assert url is not None
    assert "redirect_url=" in url
    assert "auth%2Fprofile%2Fdashboard" in url or "/auth/profile/dashboard" in url


async def test_clerk_portal_url_returns_none_without_clerk_sign_in_url():
    with patch.object(settings, "clerk_sign_in_url", None):
        url = settings.clerk_account_portal_url_with_redirect("/auth/profile/dashboard")
    assert url is None
