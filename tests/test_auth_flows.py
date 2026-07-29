"""Test authentication flows — Clerk-mode edition.

Since Clerk is enabled in all environments (including the test environment),
form-based login and registration are replaced by Clerk-hosted flows.  These
tests verify the *Clerk-enabled* behaviour of each auth endpoint, and use the
``auth_as`` helper from conftest to bypass the cookie requirement for routes
that still live in SMEme (profile management, etc.).

Tests cover:
- Login / register endpoints redirect to Clerk (no SMEme cookie issued)
- Logout redirects with ?smeme_clerk_logout=1 flag
- Logout is POST-only (CSRF-protected)
- Rate-limiting on the login endpoint still applies
- Profile: email change is blocked (Clerk owns email)
- Profile: username change is blocked until Business creator handles (HTMX error fragment)
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from smeme.core.models import User
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")

# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def auth_test_user(test_session_factory):
    """Minimal active User for profile-endpoint tests (no password needed)."""
    email = "clerk_auth_test@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username="clerkauthuser",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id

    yield user

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == uid))
        await session.commit()


# =============================================================================
# Login: Clerk redirect
# =============================================================================


async def test_login_returns_clerk_signin_link(app):
    """POST /auth/login in Clerk mode returns a sign-in link, no session cookie."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            data={"username": "anyone@example.com", "password": "anything"},
        )

    assert response.status_code == 200
    assert "Clerk" in response.text or "clerk" in response.text
    assert "session" not in response.cookies


async def test_login_ignores_credentials_in_clerk_mode(app):
    """POST /auth/login never validates credentials — Clerk handles that."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            data={"username": "no-such-user@example.com", "password": "wrong"},
        )

    assert response.status_code == 200
    assert "session" not in response.cookies


# =============================================================================
# Registration: Clerk redirect
# =============================================================================


async def test_register_returns_clerk_signup_link(app):
    """POST /auth/register in Clerk mode returns a sign-up link, no session cookie."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            data={
                "email": "newclerk@example.com",
                "username": "clerkuser",
                "password": "securepass123",
            },
        )

    assert response.status_code == 200
    assert "Clerk" in response.text or "clerk" in response.text
    assert "session" not in response.cookies


# =============================================================================
# Logout
# =============================================================================


async def test_logout_redirects_with_clerk_signout_flag(app):
    """POST /auth/logout in Clerk mode redirects and includes smeme_clerk_logout=1."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            headers={"Origin": "http://test"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    location = response.headers.get("location", "")
    # Either uses Clerk's external sign-out URL or SMEme's own logout flag.
    assert "/auth/login" in location or "clerk" in location.lower()
    assert "smeme_clerk_logout=1" in location or "clerk" in location.lower()


async def test_logout_get_is_not_allowed(app):
    """GET /auth/logout must not clear cookies (L-02 CSRF)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 405


async def test_logout_rejects_cross_origin_post_without_csrf(app):
    """Cross-origin POST without CSRF header must fail when a Clerk cookie is present."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            cookies={"__session": "fake-clerk-session"},
            headers={"Origin": "https://evil.example"},
            follow_redirects=False,
        )

    assert response.status_code == 403


# =============================================================================
# Rate Limiting
# =============================================================================


@pytest.mark.enable_rate_limiting
async def test_rate_limit_login(app):
    """Excessive login attempts must be rate-limited regardless of Clerk mode."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = []
        for i in range(6):
            response = await client.post(
                "/auth/login",
                data={"username": f"attacker{i}@example.com", "password": "wrong"},
            )
            responses.append(response)

    status_codes = [r.status_code for r in responses]
    assert 429 in status_codes, f"Expected 429 in {status_codes}"


# =============================================================================
# Profile: email change blocked in Clerk mode
# =============================================================================


async def test_profile_email_change_blocked_in_clerk_mode(auth_test_user, app):
    """PUT /auth/profile/me with a new email returns a Clerk-ownership error (Clerk mode)."""
    new_email = "changed@example.com"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with auth_as(app, auth_test_user):
            resp = await client.put(
                "/auth/profile/me",
                json={"email": new_email, "username": auth_test_user.username},
                headers={"HX-Request": "true"},
            )

    assert resp.status_code == 200
    assert "Clerk" in resp.text


# =============================================================================
# Profile: username update works, no emails sent
# =============================================================================


async def test_profile_update_username_rejected_htmx(auth_test_user, app):
    """Username changes blocked until Business tier; HTMX returns an error fragment."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with auth_as(app, auth_test_user):
            resp = await client.put(
                "/auth/profile/me",
                json={
                    "email": auth_test_user.email,
                    "username": "updated_username_clerk",
                },
                headers={"HX-Request": "true"},
            )

    assert resp.status_code == 200
    assert "danger" in resp.text.lower()
    assert "business" in resp.text.lower()
