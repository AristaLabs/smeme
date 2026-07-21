"""Unit tests for QNR dashboard, session-start routes, and in-app docs.

Covers:
- GET /qnr/dashboard returns 200 for authenticated user
- Dashboard renders the user's own current non-archived QNR titles
- Dashboard requires authentication
- GET /docs (hub), /docs/creator-dashboard, /docs/mcp require auth; return 200 when signed in
- POST /qnr/start creates a QNRSession row with no payment gate
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from smeme.core.models import QNR, QNRSession, User
from smeme.app_factory import create_core_app as create_app
from smeme.mcp.urls import MCP_SAAS_PUBLIC_MCP_URL
from tests.conftest import auth_as

pytestmark = pytest.mark.asyncio(loop_scope="session")


# =============================================================================
# Fixtures
# =============================================================================


def _minimal_graph(title: str = "Test QNR") -> dict:
    from smeme.qnr.models import (
        ConclusionData,
        GraphEdge,
        GraphNode,
        QNRGraph,
        QNRMetadata,
        QuestionData,
    )

    g = QNRGraph(
        nodes=[
            GraphNode(
                id="q1",
                type="question",
                data=QuestionData(text="Q?", type="radio", options=["Yes", "No"], required=True),
            ),
            GraphNode(id="c1", type="conclusion", data=ConclusionData(title="A", summary="a")),
            GraphNode(id="c2", type="conclusion", data=ConclusionData(title="B", summary="b")),
        ],
        edges=[
            GraphEdge(source="q1", target="c1", condition="Yes"),
            GraphEdge(source="q1", target="c2", condition="No"),
        ],
        metadata=QNRMetadata(title=title),
    )
    return g.model_dump(mode="json")


@pytest_asyncio.fixture
async def dashboard_user(test_session_factory):
    """Free-tier user with one active QNR."""
    uid = uuid4().hex[:8]
    email = f"dash_{uid}@example.com"

    async with test_session_factory() as session:
        user = User(
            email=email,
            hashed_password="unused_in_clerk_mode",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"dashuser_{uid}",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        my_qnr = QNR(
            author_id=user.id,
            title=f"My QNR {uid}",
            graph_data=_minimal_graph(f"My QNR {uid}"),
            is_public=False,
            is_current=True,
            is_archived=False,
        )
        session.add(my_qnr)
        await session.commit()
        await session.refresh(my_qnr)

    yield {"user": user, "my_qnr": my_qnr}

    async with test_session_factory() as session:
        await session.execute(delete(QNRSession).where(QNRSession.qnr_id == my_qnr.id))
        await session.execute(delete(QNR).where(QNR.id == my_qnr.id))
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
# GET /qnr/dashboard
# =============================================================================


async def test_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/qnr/dashboard")
    assert r.status_code == 200


async def test_dashboard_requires_auth(client):
    r = await client.get("/qnr/dashboard")
    assert r.status_code in (302, 401, 403)


async def test_dashboard_shows_authored_qnr_title(client, app_with_db, dashboard_user):
    """The user's own current non-archived QNR title appears in the response body."""
    title = dashboard_user["my_qnr"].title
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/qnr/dashboard")
    assert r.status_code == 200
    assert title.encode() in r.content


async def test_dashboard_prunes_completed_generation_rows(monkeypatch, dashboard_user):
    """Saved workflows should not continue occupying the in-progress dashboard slot."""
    from smeme.qnr import routes as qnr_routes
    from smeme.qnr.generation.agentic import workflow as workflow_module
    from smeme.qnr.generation.agentic.services import checkpoint_manager

    qnr_id = dashboard_user["my_qnr"].id
    generation = SimpleNamespace(
        id=uuid4(),
        langgraph_thread_id="completed-thread",
    )
    cleaned_threads: list[str] = []

    class FakeWorkflow:
        async def aget_state(self, config):
            return SimpleNamespace(
                values={"qnr_id": str(qnr_id), "final_status": "has_errors"},
            )

    async def fake_get_compiled_workflow():
        return FakeWorkflow()

    async def fake_complete_generation(db, thread_id):
        cleaned_threads.append(thread_id)

    monkeypatch.setattr(workflow_module, "get_compiled_workflow", fake_get_compiled_workflow)
    monkeypatch.setattr(checkpoint_manager, "complete_generation", fake_complete_generation)

    active = await qnr_routes._prune_completed_dashboard_generations(
        db=object(),
        current_user=dashboard_user["user"],
        generations=[generation],
    )

    assert active == []
    assert cleaned_threads == ["completed-thread"]


async def test_dashboard_hides_archive_ui(client, app_with_db, dashboard_user):
    """Archive affordances removed from product."""
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/qnr/dashboard")
    assert r.status_code == 200
    assert b"archive-confirm" not in r.content
    assert b'id="archived-heading"' not in r.content
    assert b"Restore archived workflow" not in r.content
    assert b"delete-confirm" in r.content


async def test_docs_index_requires_auth(client):
    r = await client.get("/docs")
    assert r.status_code in (302, 401, 403)


async def test_docs_index_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs")
    assert r.status_code == 200
    assert b"Deploy" in r.content and b"Listed" in r.content
    from smeme.docs.constants import DOCS_VERSION

    assert DOCS_VERSION.encode() in r.content
    assert b"/docs/creator-dashboard" in r.content
    assert b"/docs/download-workflow" in r.content
    assert b"/docs/mcp" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()


async def test_docs_introduction_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/introduction")
    assert r.status_code == 200
    assert b"How to fix" in r.content
    assert b"Deploy, list" in r.content


async def test_docs_creator_dashboard_requires_auth(client):
    r = await client.get("/docs/creator-dashboard")
    assert r.status_code in (302, 401, 403)


async def test_docs_creator_dashboard_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/creator-dashboard")
    assert r.status_code == 200
    assert b"Deploy, validate" in r.content
    assert b"How to fix" in r.content
    assert b"Live" in r.content and b"Stale" in r.content
    assert b"marketplace" not in r.content.lower()
    assert b"revenue" not in r.content.lower()


async def test_docs_download_workflow_requires_auth(client):
    r = await client.get("/docs/download-workflow")
    assert r.status_code in (302, 401, 403)


async def test_docs_download_workflow_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/download-workflow")
    assert r.status_code == 200
    assert b"Download your workflow" in r.content
    assert b"smeme_export_version" in r.content
    assert b"Re-import" in r.content


async def test_docs_mcp_requires_auth(client):
    r = await client.get("/docs/mcp")
    assert r.status_code in (302, 401, 403)


async def test_docs_mcp_returns_200(client, app_with_db, dashboard_user):
    with auth_as(app_with_db, dashboard_user["user"]):
        r = await client.get("/docs/mcp")
    assert r.status_code == 200
    assert b"Connect your agent" in r.content
    assert b"smeme_reasoning" in r.content
    assert b"install-claude" in r.content
    assert b"install-chatgpt" in r.content
    assert b"Developer mode" in r.content
    assert b"create dialog" in r.content
    assert b"Advanced settings" in r.content
    assert b"Customize" in r.content
    assert b"chatgpt.com" in r.content
    assert b"browser" in r.content
    assert MCP_SAAS_PUBLIC_MCP_URL.encode() in r.content
    assert b"does not install SMEme" in r.content


async def test_mcp_discoverable_toggle_requires_owner(client, app_with_db, dashboard_user, test_session_factory):
    """Non-owner cannot toggle discoverability (403)."""
    from sqlalchemy import delete

    uid = uuid4().hex[:8]
    async with test_session_factory() as session:
        other = User(
            email=f"other_{uid}@example.com",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            is_superuser=False,
            username=f"other_{uid}",
        )
        session.add(other)
        await session.commit()
        await session.refresh(other)

    qid = dashboard_user["my_qnr"].id
    with auth_as(app_with_db, other):
        r = await client.post(
            "/qnr/mcp/discoverable",
            data={"qnr_id": str(qid), "enabled": "true"},
            follow_redirects=False,
        )
    assert r.status_code == 403

    async with test_session_factory() as session:
        await session.execute(delete(User).where(User.id == other.id))
        await session.commit()


# =============================================================================
# POST /qnr/start — no payment gate
# =============================================================================


async def test_start_qnr_creates_session_without_payment_gate(
    client, app_with_db, dashboard_user, test_session_factory
):
    """POST /qnr/start must create a QNRSession and return 200 with no billing redirect.

    Before Phase 1 this route checked price_cents and redirected free-tier users
    to /billing/session-pay/...  That gate is gone; any authenticated user can
    start a session on any QNR directly.
    """
    user = dashboard_user["user"]
    qnr_id = dashboard_user["my_qnr"].id

    with auth_as(app_with_db, user):
        r = await client.post("/qnr/start", data={"qnr_id": str(qnr_id)})

    # Must not redirect to billing
    assert r.status_code == 200
    assert "session-pay" not in str(r.headers.get("location", ""))
    assert "session-pay" not in r.text

    # A QNRSession row must exist in the DB
    async with test_session_factory() as session:
        result = await session.execute(
            select(QNRSession).where(
                QNRSession.user_id == user.id,
                QNRSession.qnr_id == qnr_id,
            )
        )
        qnr_session = result.scalar_one_or_none()

    assert qnr_session is not None
