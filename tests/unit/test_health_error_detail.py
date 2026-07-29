"""L-01: health endpoints must not leak exception strings to clients."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_health_db_failure_returns_stable_error_code(app, monkeypatch):
    """Provider/database exception text must not appear in the response body."""
    leak = "could not connect to server: Connection refused host=prod-db.internal port=5432"

    async def boom(_session):
        raise RuntimeError(leak)

    from smeme.api import health as health_mod

    fake_db = MagicMock()
    fake_db.execute = AsyncMock(side_effect=boom)

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[health_mod.get_db] = fake_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health/db")
    finally:
        app.dependency_overrides.pop(health_mod.get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "disconnected"
    assert body["error"] == "database_unavailable"
    assert leak not in response.text
    assert "prod-db.internal" not in response.text
    assert "Connection refused" not in response.text
