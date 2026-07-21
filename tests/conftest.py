"""Shared pytest fixtures for SMEme tests.

Provides:
- event_loop: Session-scoped event loop to share database connections
- app: FastAPI application instance
- client: Async HTTP test client
- db_session: Database session with transaction rollback
- disable_rate_limiting: Auto-use fixture to disable rate limiting
- auth_as: Context manager that injects a User into auth dependency overrides
"""

import asyncio
from contextlib import contextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from smeme.app_factory import create_core_app
from smeme.core.config import settings

# Default test app is Core (public product surface). SaaS-only suites import
# ``create_saas_app`` / ``create_app`` from ``smeme.main`` explicitly.
create_app = create_core_app

# =============================================================================
# Event Loop Configuration
# =============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop.

    This is necessary because asyncpg connections are bound to event loops.
    Using a session-scoped loop ensures all tests share the same loop and
    can reuse database connections without "attached to different loop" errors.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Database Engine (Session Scoped)
# =============================================================================


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a session-scoped database engine.

    This ensures the engine is created within the test event loop,
    preventing "attached to different loop" errors.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args=(
            {
                "ssl": True,
                "server_settings": {"application_name": "smeme_tests"},
            }
            if "neon" in settings.database_url.lower()
            else {"server_settings": {"application_name": "smeme_tests"}}
        ),
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_session_factory(test_engine):
    """Create a session factory using the test engine."""
    return sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# =============================================================================
# Rate Limiting
# =============================================================================


@pytest.fixture(autouse=True)
def disable_rate_limiting(request):
    """Disable rate limiting for tests by default.

    Tests that need to verify rate limiting behavior can mark themselves
    with @pytest.mark.enable_rate_limiting to skip this fixture.
    """
    from smeme.core.rate_limiting import limiter

    # Check if this test wants rate limiting enabled
    if request.node.get_closest_marker("enable_rate_limiting"):
        yield
        return

    # Directly disable the limiter for this test
    original_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original_enabled


# =============================================================================
# App and Client Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def app(test_session_factory):
    """Create test application with overridden database dependency.

    This ensures the app uses our test session factory (which is tied to
    the test event loop) instead of the module-level engine.
    """
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
async def client(app):
    """Async HTTP test client for endpoint testing.

    Usage:
        async def test_endpoint(client):
            response = await client.get("/health")
            assert response.status_code == 200
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session(test_session_factory):
    """Database session for tests.

    Usage:
        async def test_db_operation(db_session):
            user = User(email="test@example.com", ...)
            db_session.add(user)
            await db_session.commit()
    """
    async with test_session_factory() as session:
        yield session


# =============================================================================
# Auth Helper
# =============================================================================


@contextmanager
def auth_as(app, user):
    """Inject *user* into the FastAPI auth dependency overrides for a code block.

    Use this in tests that need an authenticated user but cannot go through
    the normal login flow (e.g. because Clerk is enabled and there is no
    form-based session cookie).

    Usage::

        with auth_as(app, user_obj):
            response = await client.get("/protected-endpoint")
        assert response.status_code == 200

    The two overrides are removed when the context exits, so existing
    overrides (e.g. ``get_db``) are untouched.
    """
    from smeme.auth.users import get_current_active_user, get_current_user_optional

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_current_user_optional] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_current_user_optional, None)


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def test_graph_data():
    """Sample QNR graph data for testing.

    Returns a minimal valid graph with:
    - 2 question nodes
    - 1 conclusion node
    - Proper edges connecting them
    """
    return {
        "nodes": [
            {
                "id": "q1",
                "type": "question",
                "data": {
                    "text": "What is your primary goal?",
                    "type": "radio",
                    "options": ["Learning", "Building", "Exploring"],
                    "required": True,
                },
            },
            {
                "id": "q2",
                "type": "question",
                "data": {
                    "text": "How much experience do you have?",
                    "type": "radio",
                    "options": ["Beginner", "Intermediate", "Advanced"],
                    "required": True,
                },
            },
            {
                "id": "conclusion_1",
                "type": "conclusion",
                "data": {
                    "title": "Recommended Path",
                    "summary": "Based on your answers, here is your path.",
                    "recommendations": ["Start here", "Then do this"],
                    "severity": "info",
                },
            },
        ],
        "edges": [
            {"source": "q1", "target": "q2"},
            {"source": "q2", "target": "conclusion_1"},
        ],
        "metadata": {
            "title": "Test Questionnaire",
            "description": "A test QNR for unit tests",
            "category": "testing",
            "estimated_time": 5,
            "tags": ["test"],
        },
    }
